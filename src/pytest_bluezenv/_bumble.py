# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Bumble-emulated HCI controllers for VM hosts.

`bumble <https://pypi.org/project/bumble/>`_ emulates Bluetooth
controllers in Python.  A :obj:`BumbleController` configuration serves
one emulated controller per VM host on an H4 unix socket, replacing
the btvirt endpoint, and joins them with emulated peer devices
declared in the configuration on a shared virtual radio
(`bumble.link.LocalLink`).

bumble is asyncio-based, and its objects are bound to the event loop
they were created on.  The upper tester is synchronous, so bumble
objects live on a dedicated loop thread.  Tests interact with them via
:obj:`BumbleEnv.run` and plain bumble API.

The bumble package is imported lazily; it is not required when no
bumble controllers are configured.
"""

import asyncio
import concurrent.futures
import importlib.util
import inspect
import itertools
import logging
import sys
import threading

import pytest

from . import utils

__all__ = ["BumbleController", "BumbleDevice", "BumbleEnv"]

log = logging.getLogger("bumble_env")

# Public addresses of VM-host controllers.  btvirt uses 00:AA:01:...,
# keep a clearly separate range.
VM_ADDRESS_PREFIX = "00:AA:02"

# Prefix for addresses of emulated peer devices without an explicit
# address.  Locally administered, avoids the btvirt range.
DEVICE_ADDRESS_PREFIX = "F1"

_ENV_COUNTER = itertools.count()


def bumble_available():
    """
    Check whether the bumble package is usable here.

    Returns:
        bool: True if bumble can be imported.
    """
    if sys.version_info < (3, 10):
        return False
    return importlib.util.find_spec("bumble") is not None


class _Loop:
    """
    Session-wide asyncio event loop for bumble objects, in a daemon
    thread.  The loop must keep running while synchronous upper-tester
    calls block, which no pytest-native async support provides.
    """

    LOCK = threading.Lock()
    LOOP = None
    THREAD = None
    ERRORS = []

    @classmethod
    def get(cls):
        with cls.LOCK:
            if cls.THREAD is None or not cls.THREAD.is_alive():
                cls.LOOP = asyncio.new_event_loop()
                cls.LOOP.set_exception_handler(cls._on_error)
                cls.THREAD = threading.Thread(
                    target=cls.LOOP.run_forever,
                    name="pytest-bluezenv-bumble",
                    daemon=True,
                )
                cls.THREAD.start()
            return cls.LOOP

    @classmethod
    def alive(cls):
        with cls.LOCK:
            return cls.THREAD is not None and cls.THREAD.is_alive()

    @classmethod
    def submit(cls, awaitable, timeout=None):
        loop = cls.get()

        async def wrapper():
            return await awaitable

        future = asyncio.run_coroutine_threadsafe(wrapper(), loop)
        try:
            return future.result(None if timeout is None else float(timeout))
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError("bumble operation timed out")

    @classmethod
    def _on_error(cls, loop, context):
        with cls.LOCK:
            cls.ERRORS.append(context)
        loop.default_exception_handler(context)


class BumbleDevice:
    """
    Declarative emulated bumble peer device.

    A device is created on the virtual air link of the test
    configuration when the test starts, and removed when it ends.

    Args:
        config (dict): bumble device configuration, interpreted by
            ``bumble.device.DeviceConfiguration``.  See the bumble
            documentation for the supported keys.
        power_on (bool): whether to power the device on when the test
            starts.
        advertising (bool): whether to start advertising when the test
            starts.  If the configuration does not give
            ``advertising_data``, LE General Discoverable Flags and the
            device name are advertised, as required for BlueZ to
            report the device as discovered.
        setup (callable): called with the ``bumble.device.Device`` on
            the bumble event loop before it is powered on, to declare
            GATT services or set up pairing.  May be a coroutine
            function.

    Attributes:
        config (dict): bumble device configuration.
        power_on (bool): whether the device is powered on at test start.
        advertising (bool): whether the device advertises at test start.
        setup (callable): customizer run on the bumble event loop.

    Example:

        .. code-block:: python

           from bumble.profiles.battery_service import BatteryService


           def add_battery(device):
               device.add_service(BatteryService(lambda connection: 80))


           BumbleDevice(config={"name": "Sensor"}, setup=add_battery)
    """

    def __init__(self, config=None, power_on=True, advertising=True, setup=None):
        self.config = dict(config or {})
        self.power_on = bool(power_on)
        self.advertising = bool(advertising)
        self.setup = setup


class BumbleController:
    """
    Bumble-emulated HCI controllers for the VM hosts.

    Use as the ``controller`` argument of
    :obj:`~pytest_bluezenv.host_config` or
    :obj:`~pytest_bluezenv.parametrized_host_config`.  Each VM host
    gets an emulated `bumble.controller.Controller` on a shared
    virtual radio, in place of a btvirt controller.  Emulated peer
    devices declared in ``devices`` join the same radio and are
    available to tests through the :obj:`~pytest_bluezenv.bumble_env`
    fixture.

    Args:
        controllers: per-VM-host controller factory.  None (default)
            uses the stock ``bumble.controller.Controller``; a callable
            is used for every host; a sequence provides one factory or
            None per host, matching the host declarations.  A factory
            is called with the `bumble.controller.Controller` argument
            names (``name``, ``host_source``, ``host_sink``, ``link``,
            ``public_address``), so any Controller subclass is itself a
            valid factory.
        devices (dict): emulated peer devices on the same virtual
            radio, by name; values are :obj:`BumbleDevice` or plain
            bumble device config dicts.  Their lifetime follows the
            test host plugins: with ``reuse=False`` they are torn
            down after every test, with ``reuse=True`` they are kept
            until the reuse group changes.

    Example:

        .. testcode::

           from pytest_bluezenv import BumbleController, host_config, Bluetoothd

           @host_config(
               [Bluetoothd()],
               controller=BumbleController(
                   devices={"sensor": {"name": "BumbleSensor"}},
               ),
           )
           def test_sensor(hosts, bumble_env):
               host0, = hosts
               host0.bluetoothctl.send("scan on\\n")

    Raises:
        TypeError: if the arguments are not of the expected types.
    """

    name = "bumble"

    def __init__(self, controllers=None, devices=None):
        if controllers is None or callable(controllers):
            self.controllers = controllers
        elif isinstance(controllers, (list, tuple)):
            for factory in controllers:
                if factory is not None and not callable(factory):
                    raise TypeError("controllers entries must be callable or None")
            self.controllers = tuple(controllers)
        else:
            raise TypeError(
                "controllers must be None, a callable, or a sequence of them"
            )

        self.devices = {}
        if devices:
            for device_name, device in devices.items():
                if not isinstance(device, BumbleDevice):
                    device = BumbleDevice(config=device)
                self.devices[str(device_name)] = device

    def factories(self, num_hosts):
        """
        Resolve per-host controller factories.

        Args:
            num_hosts (int): number of VM hosts.
        Returns:
            tuple: factory or None for each host.
        Raises:
            ValueError: if a sequence of factories does not match the
                host count.
        """
        if self.controllers is None:
            return (None,) * num_hosts
        if callable(self.controllers):
            return (self.controllers,) * num_hosts
        if len(self.controllers) != num_hosts:
            raise ValueError(
                f"BumbleController got {len(self.controllers)} controllers "
                f"for {num_hosts} hosts"
            )
        return self.controllers

    def parametrize_id(self):
        """
        Parametrize id fragment identifying this configuration.

        Returns:
            str: id fragment, e.g. "bumble" or "bumble-FakeAddr".
        """
        if self.controllers is None:
            return self.name

        factories = (
            (self.controllers,) if callable(self.controllers) else self.controllers
        )
        names = []
        for factory in factories:
            name = (
                "Controller"
                if factory is None
                else getattr(factory, "__name__", type(factory).__name__)
            )
            if name not in names:
                names.append(name)
        return self.name + "-" + "+".join(names)


class _BumbleRuntime:
    """
    Bumble objects of one :obj:`~pytest_bluezenv.env.Environment`.

    Internal.  Holds the virtual radio and the VM-host controllers,
    which live as long as the environment, and the declared peer
    devices, which live as long as the test host plugins.
    """

    def __init__(self, spec, num_hosts, path, timeout=None, debug=False):
        self.spec = spec
        self.num_hosts = num_hosts
        self.path = path
        self.timeout = timeout
        self.debug = debug
        self.env_index = next(_ENV_COUNTER)
        self.socket_paths = [path / f"bumble-{i}" for i in range(self.num_hosts)]
        self.env = BumbleEnv(self)

        self.link = None
        self._transports = []
        self._vm_controllers = []
        self._test_devices = {}
        self._devices_started = False
        self._device_index = 0
        self._logging_saved = None
        self._errors_base = 0

    def start(self):
        if not bumble_available():
            raise RuntimeError(
                "bumble package not installed (pip install pytest-bluezenv[bumble])"
            )
        self._configure_logging()
        try:
            _Loop.submit(self._async_start(), self.timeout)
        except Exception:
            try:
                _Loop.submit(self._async_stop(), self.timeout)
            except Exception:
                pass
            self._restore_logging()
            # bound transports leave their socket files behind
            for sock in self.socket_paths:
                try:
                    sock.unlink()
                except OSError:
                    pass
            raise
        self._errors_base = len(_Loop.ERRORS)

    def stop(self):
        try:
            _Loop.submit(self._async_stop(), self.timeout)
        except Exception:
            log.exception("bumble runtime teardown failed")
        finally:
            self._restore_logging()
            for path in self.socket_paths:
                try:
                    path.unlink()
                except OSError:
                    pass

    def check_errors(self):
        errors = []

        if not _Loop.alive():
            errors.append("the bumble event loop thread is not running")

        with _Loop.LOCK:
            new_errors = _Loop.ERRORS[self._errors_base :]
            self._errors_base = len(_Loop.ERRORS)
        for context in new_errors:
            errors.append(
                "bumble event loop: {}".format(context.get("message", context))
            )

        return errors

    def start_devices(self):
        if self._devices_started:
            return
        for device_name, device_spec in self.spec.devices.items():
            device = _Loop.submit(
                self._async_add_device(device_name, device_spec), self.timeout
            )
            self._test_devices[device_name] = device
        self._devices_started = True

    def stop_devices(self):
        if not self._devices_started:
            return
        devices = self._test_devices
        self._test_devices = {}
        self._devices_started = False
        for name, (device, controller) in devices.items():
            try:
                _Loop.submit(
                    self._async_remove_device(device, controller), self.timeout
                )
                log.info(
                    "bumble device %s removed, link: %s",
                    name,
                    sorted(c.name for c in self.link.controllers),
                )
            except Exception:
                log.exception("failed to remove bumble device")

    async def _async_start(self):
        from bumble.controller import Controller
        from bumble.link import LocalLink
        from bumble.transport.unix import open_unix_server_transport

        self.link = LocalLink()

        factories = self.spec.factories(self.num_hosts)
        for i, socket_path in enumerate(self.socket_paths):
            transport = await open_unix_server_transport(str(socket_path))
            self._transports.append(transport)
            factory = factories[i] or Controller
            controller = factory(
                name=f"vm{i}",
                host_source=transport.source,
                host_sink=transport.sink,
                link=self.link,
                public_address=self._vm_address(i),
            )
            self._vm_controllers.append(controller)

    async def _async_stop(self):
        # The VM hosts are gone by environment teardown; drop the test
        # devices without attempting disconnection.
        for device, controller in self._test_devices.values():
            self.link.remove_controller(controller)
        self._test_devices = {}
        self._devices_started = False
        for controller in self._vm_controllers:
            self.link.remove_controller(controller)
        self._vm_controllers = []
        for transport in self._transports:
            await transport.close()
        self._transports = []

    async def _async_add_device(self, device_name, device_spec):
        from bumble import data_types
        from bumble.controller import Controller
        from bumble.core import AdvertisingData
        from bumble.device import Device, DeviceConfiguration
        from bumble.host import Host
        from bumble.transport.common import AsyncPipeSink

        config = dict(device_spec.config)
        if "address" not in config:
            config["address"] = self._device_address()

        device_config = DeviceConfiguration()
        device_config.load_from_dict(config)

        controller = Controller(
            name=f"device-{device_name}",
            link=self.link,
            public_address=device_config.address,
        )
        host = Host(controller, AsyncPipeSink(controller))
        device = Device(config=device_config, host=host)

        if device_spec.setup is not None:
            result = device_spec.setup(device)
            if inspect.isawaitable(result):
                await result

        if device_spec.power_on:
            await device.power_on()

        if device_spec.advertising:
            if "advertising_data" not in config:
                flags = bytes(
                    AdvertisingData(
                        [
                            data_types.Flags(
                                AdvertisingData.Flags.LE_GENERAL_DISCOVERABLE_MODE
                                | AdvertisingData.Flags.BR_EDR_NOT_SUPPORTED
                            )
                        ]
                    )
                )
                device.advertising_data = flags + device.advertising_data
            await device.start_advertising(auto_restart=True)

        return device, controller

    async def _async_remove_device(self, device, controller):
        from bumble import hci

        for connection in list(device.connections.values()):
            try:
                await device.disconnect(
                    connection,
                    hci.HCI_ErrorCode.REMOTE_USER_TERMINATED_CONNECTION_ERROR,
                )
            except Exception:
                log.debug("bumble device %s: disconnect failed", controller.name)
        try:
            await device.power_off()
        except Exception:
            log.debug("bumble device %s: power off failed", controller.name)
        self.link.remove_controller(controller)

    def _vm_address(self, host_index):
        return "{}:00:{:02X}:{:02X}".format(
            VM_ADDRESS_PREFIX, self.env_index & 0xFF, host_index & 0xFF
        )

    def _device_address(self):
        address = "{}:{:02X}:{:02X}:00:00:00".format(
            DEVICE_ADDRESS_PREFIX, self.env_index & 0xFF, self._device_index & 0xFF
        )
        self._device_index += 1
        return address

    def _configure_logging(self):
        # bumble logs HCI traffic and protocol events at debug level.  Let
        # them reach the standard test log, but keep them suppressed unless
        # debugging is enabled.
        logger = logging.getLogger("bumble")
        self._logging_saved = (logger.level, logger.propagate)
        logger.propagate = True
        logger.setLevel(logging.DEBUG if self.debug else logging.CRITICAL)

    def _restore_logging(self):
        if self._logging_saved is None:
            return
        level, propagate = self._logging_saved
        logger = logging.getLogger("bumble")
        logger.setLevel(level)
        logger.propagate = propagate
        self._logging_saved = None


class BumbleEnv:
    """
    Synchronous access to the bumble environment of a test.

    Provided by the :obj:`~pytest_bluezenv.bumble_env` fixture for
    tests configured with ``controller=BumbleController()``.  The
    declared emulated peer devices are available in
    :obj:`~pytest_bluezenv.BumbleEnv.devices` already powered on and
    advertising as configured.  Other bumble API is used by passing
    coroutines to :obj:`~pytest_bluezenv.BumbleEnv.run`.

    Attributes:
        devices (dict): ``bumble.device.Device`` of the emulated peer
            devices, by name.  Present for as long as the test host
            plugins: per-test, or across the tests of one reuse
            group with ``reuse=True``.
        controllers (tuple): ``bumble.controller.Controller`` serving
            each VM host, in host order.  ``public_address`` is the
            address the VM host kernel reports.
        link (bumble.link.LocalLink): the virtual radio shared by the
            VM-host controllers and the emulated peer devices.
        loop (asyncio.AbstractEventLoop): the event loop the bumble
            objects run on.  It runs in a separate thread, so tests use
            :obj:`~pytest_bluezenv.BumbleEnv.run` to submit work to it.
    """

    def __init__(self, runtime):
        self._runtime = runtime

    def _start_devices(self):
        self._runtime.start_devices()

    def _stop_devices(self):
        self._runtime.stop_devices()

    @property
    def devices(self):
        return {
            name: device for name, (device, _) in self._runtime._test_devices.items()
        }

    @property
    def controllers(self):
        return tuple(self._runtime._vm_controllers)

    @property
    def link(self):
        return self._runtime.link

    @property
    def loop(self):
        return _Loop.get()

    def run(self, awaitable, timeout=None):
        """
        Run a coroutine on the bumble event loop and wait for it.

        Blocks the caller while the bumble loop keeps processing HCI
        traffic.  Use with plain bumble API, e.g.
        ``bumble_env.run(device.start_advertising())``.

        Args:
            awaitable: coroutine or other awaitable to run.
            timeout (float): timeout in seconds (default: the
                environment timeout).
        Returns:
            The result of the awaitable.
        Raises:
            TimeoutError: if the operation did not complete in time.
            Exception: any exception raised by the awaitable.
        """
        if timeout is None:
            timeout = self._runtime.timeout or utils.DEFAULT_TIMEOUT
        return _Loop.submit(awaitable, timeout)


@pytest.fixture
def bumble_env(request):
    """
    Bumble environment for tests using ``controller=BumbleController()``.

    Provides synchronous access to the bumble objects of the test
    configuration: the emulated peer devices declared in the
    :obj:`~pytest_bluezenv.BumbleController`, the emulated controllers
    serving the VM hosts, and the virtual radio they share.  Plain
    bumble API is used by passing coroutines to
    :obj:`~pytest_bluezenv.BumbleEnv.run`.  The declared peer devices
    live as long as the test host plugins.

    Args:
        request (pytest.FixtureRequest): test fixture request.

    Yields:
        pytest_bluezenv.BumbleEnv: the bumble environment of the test.

    Example:

        .. testcode::

           from pytest_bluezenv import Bluetoothd, BumbleController, host_config

           @host_config([Bluetoothd()], controller=BumbleController(
               devices={"sensor": {"name": "BumbleSensor"}}))
           def test_sensor(hosts, bumble_env):
               host0, = hosts
               sensor = bumble_env.devices["sensor"]
               host0.bluetoothctl.send("scan on\\n")
               host0.bluetoothctl.expect("BumbleSensor")
               bumble_env.run(sensor.power_off())
    """
    vm = None

    for name in ("vm", "vm_once"):
        if name in request.fixturenames:
            vm = request.getfixturevalue(name)
            break

    if vm is None:
        raise pytest.fail(
            "bumble_env requires a test using the hosts or hosts_once "
            "fixture with controller=BumbleController()"
        )

    if vm.bumble is None:
        raise pytest.fail(
            "bumble_env requires host_config(controller=BumbleController())"
        )

    yield vm.bumble
