# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Controller backends for the VM hosts.

A controller specification given as the ``controller`` argument of
:obj:`~pytest_bluezenv.host_config` describes how the VM hosts get
their Bluetooth controllers.  :obj:`BtvirtController` is the default:
one ``btvirt`` process emulates a controller per host and provides
the virtual air link between them.  :obj:`HwController` passes real
controllers through to the VM hosts instead.
:obj:`~pytest_bluezenv.BumbleController` implements the same
interface with bumble-emulated controllers.

The :obj:`ControllerBase.backend` property names the
:obj:`ControllerBackend` class each specification starts.  A backend
is constructed per test environment, hands the test-runner arguments
that attach the controllers, and owns the emulated peer devices whose
lifetime follows the test host plugins.
"""

import abc
import logging
import os
import pwd
import subprocess
from pathlib import Path

from . import utils

__all__ = ["ControllerBase", "ControllerBackend", "BtvirtController", "HwController"]

log = logging.getLogger(__name__)


class ControllerBase(abc.ABC):
    """
    Base class for controller specifications usable with
    :obj:`~pytest_bluezenv.host_config` and
    :obj:`~pytest_bluezenv.parametrized_host_config`.

    A specification is shared by all tests of its configuration.  It
    must hold no per-environment state; started controllers belong to
    the per-environment :obj:`ControllerBackend`, constructed from
    the class named by its ``backend`` property.

    Example:

        .. code-block:: python

           class MyController(ControllerBase):
               def parametrize_id(self):
                   return "mine"

               @property
               def backend(self):
                   return MyBackend
    """

    def validate(self, num_hosts):
        """
        Check the specification against a host count.  Called at
        decoration time and when an environment is constructed.

        Args:
            num_hosts (int): number of VM hosts.

        Raises:
            ValueError: if the specification does not fit the hosts.
        """

    def parametrize_id(self):
        """
        Parametrize id fragment identifying this configuration.  The
        empty string adds no fragment.

        Returns:
            str: id fragment.
        """
        raise NotImplementedError

    def skip_reason(self):
        """
        Reason why tests using this controller cannot run, if any.

        Returns:
            str | None: skip reason, or None if the controller is
            available.
        """
        return None

    def executables(self):
        """
        Executables required from the BlueZ build tree.

        Returns:
            dict: ``(subdirectory, name)`` to ``required`` bool.
        """
        return {}

    @property
    @abc.abstractmethod
    def backend(self):
        """
        The :obj:`ControllerBackend` subclass started for
        environments using this specification.

        Returns:
            type[ControllerBackend]: backend class.
        """

    def __eq__(self, other):
        if not isinstance(other, ControllerBase):
            return NotImplemented
        return self._sort_key() == other._sort_key()

    def __lt__(self, other):
        if not isinstance(other, ControllerBase):
            return NotImplemented
        return self._sort_key() < other._sort_key()

    def __hash__(self):
        return hash(self._sort_key())

    def _sort_key(self):
        return (type(self).__name__, self.parametrize_id())


class ControllerBackend(abc.ABC):
    """
    Started controller service of one test environment.

    Subclasses start the controllers in their constructor, with the
    standard arguments below; the test environment attaches the
    controllers to the VM hosts using ``runner_args``, keeps the
    service alive between tests with the host plugins, and calls
    :obj:`~pytest_bluezenv.ControllerBackend.stop` when the
    environment goes away.

    Args:
        controller (ControllerBase): the specification this service
            was started from.
        path (pathlib.Path): environment directory for sockets and
            other files.
        num_hosts (int): number of VM hosts.
        timeout (float): timeout in seconds for startup operations.
        debug (bool): enable verbose controller logs.
    """

    def __init__(self, controller, path, num_hosts, timeout=None, debug=False):
        self.controller = controller
        self.path = path
        self.num_hosts = num_hosts
        self.timeout = timeout
        self.debug = debug

    @property
    @abc.abstractmethod
    def runner_args(self):
        """
        Returns:
            list[list[str]]: extra test-runner arguments attaching the
            controller of each host.
        """

    @abc.abstractmethod
    def stop(self):
        """
        Stop the service and release its resources.
        """

    def check_errors(self):
        """
        Check the service is still healthy.

        Returns:
            list: error descriptions, empty when healthy.
        """
        return []

    def start_devices(self):
        """
        Start the emulated peer devices of the tests, if any.  Called
        when the test hosts are set up.
        """

    def stop_devices(self):
        """
        Tear the emulated peer devices down.  Called when the test
        hosts are closed, before the environment stops.
        """

    def cleanup(self, path):
        """
        Remove leftover files of the service from the environment
        directory.  Called after the service has stopped.

        Args:
            path (pathlib.Path): environment directory.
        """


class BtvirtController(ControllerBase):
    """
    Controllers emulated by the BlueZ ``btvirt`` process, the default
    of :obj:`~pytest_bluezenv.host_config`.  One process serves one
    controller per VM host and bridges the virtual air link between
    them.

    ``btvirt`` is replaced by real controllers when hardware is
    requested with ``hw=True``, ``--force-usb`` or ``--force-pcie``.

    Example:

        .. code-block:: python

           @host_config([Bluetoothd()], controller=BtvirtController())
           def test_air_link(hosts): ...
    """

    def parametrize_id(self):
        return ""

    def executables(self):
        return {("emulator", "btvirt"): True}

    @property
    def backend(self):
        return _BtvirtBackend


class _BtvirtBackend(ControllerBackend):
    def __init__(self, controller, path, num_hosts, timeout=None, debug=False):
        super().__init__(controller, path, num_hosts, timeout=timeout, debug=debug)

        self._job = None
        self._log_stream = None
        try:
            exe = utils.find_exe("emulator", "btvirt")
            self._log_stream = utils.LogStream("btvirt")

            cmd = [exe, f"--server={self.path}"]
            if debug:
                cmd.append("-d")
            log.info("Starting btvirt: {}".format(utils.quoted(cmd)))

            self._job = subprocess.Popen(
                cmd,
                stdout=self._log_stream.stream,
                stderr=self._log_stream.stream,
                stdin=subprocess.DEVNULL,
                env=_asan_env(),
            )

            self._socket = self.path / "bt-server-bredrle"
            utils.wait_files([self._job], [self._socket])
        except Exception:
            self.stop()
            raise

    @property
    def runner_args(self):
        return [[f"-u{self._socket}"]] * self.num_hosts

    def stop(self):
        try:
            if self._job is not None:
                if self._job.poll() is None:
                    self._job.terminate()
                self._job.wait()
        finally:
            if self._log_stream is not None:
                self._log_stream.close()
            self._job = None

    def check_errors(self):
        if self._job.poll() is not None:
            cmd = utils.quoted(self._job.args)
            return ["'{}' terminated unexpectedly".format(cmd)]
        return []

    def cleanup(self, path):
        for f in Path(path).iterdir():
            if f.name.startswith("bt-server-"):
                f.unlink()


class HwController(ControllerBase):
    """
    Real controllers passed through to the VM hosts, one per host.

    Selected automatically in place of the default
    :obj:`BtvirtController` when ``host_config(hw=True)``,
    ``--force-usb`` or ``--force-pcie`` request hardware.

    Args:
        indices (sequence): controller names, such as ``"hci0"``, at
            least one per VM host.

    Raises:
        ValueError: if ``validate`` finds fewer controllers than
            hosts.
    """

    def __init__(self, indices):
        self.indices = tuple(indices)

    def validate(self, num_hosts):
        if num_hosts > len(self.indices):
            raise ValueError(
                "Controller passthrough enabled, but not enough controllers"
                " for each host"
            )

    def parametrize_id(self):
        return "hw"

    @property
    def backend(self):
        return _HwBackend

    @classmethod
    def controller_bus(cls, name):
        """
        Bus a controller is attached to.

        Returns:
            bus: "usb", "pci", or None if it is on neither of them
        """
        subsys = Path("/sys/class/bluetooth") / name / "device" / "subsystem"

        try:
            bus = subsys.resolve().name
        except OSError:
            return None

        return bus if bus in ("usb", "pci") else None

    @classmethod
    def check_controller(cls, name):
        """
        Check a controller can be passed through to a VM host.

        Returns:
            args: test-runner arguments passing the controller through

        Raises:
            ValueError: it cannot be passed through, telling why
        """
        bus = cls.controller_bus(name)

        if bus == "usb":
            return cls._check_usb_controller(name)
        elif bus == "pci":
            return cls._check_pcie_controller(name)

        raise ValueError(f"{name} is not an USB or a PCIe device")

    @classmethod
    def _check_usb_controller(cls, name):
        devpath = Path(f"/sys/class/bluetooth/{name}/device/../")
        with open(devpath / "busnum", "r") as f:
            busnum = "{:03}".format(int(f.read().strip()))
        with open(devpath / "devnum", "r") as f:
            devnum = "{:03}".format(int(f.read().strip()))

        devname = f"/dev/bus/usb/{busnum}/{devnum}"
        if not Path(devname).exists():
            raise ValueError(f"{devname} does not exist")

        try:
            with open(devname, "wb") as f:
                pass
        except IOError:
            user = pwd.getpwuid(os.getuid()).pw_name.strip()
            message = (
                f"error: cannot open {devname} for {name} USB redirection. "
                f"Run: 'sudo setfacl -m user:{user}:rw- {devname}' "
                f"to grant the permission"
            )
            raise ValueError(message)

        return ["-U", f"usb-host,hostbus={busnum},hostaddr={devnum}"]

    @classmethod
    def _check_pcie_controller(cls, name):
        device = Path(f"/sys/class/bluetooth/{name}/device").resolve()
        bdf = device.name

        # The device is bound to vfio-pci for the time a VM host uses it,
        # which is only allowed for the superuser
        if os.geteuid() != 0:
            raise ValueError(
                f"error: passing {name} ({bdf}) through to a VM host binds it"
                f" to vfio-pci, which requires running the tests as root"
            )

        if not (device / "iommu_group").exists():
            raise ValueError(
                f"error: {name} ({bdf}) has no IOMMU group, enable the IOMMU"
                f" to pass it through to a VM host"
            )

        return ["-P", f"vfio-pci,host={bdf}"]


class _HwBackend(ControllerBackend):
    def __init__(self, controller, path, num_hosts, timeout=None, debug=False):
        super().__init__(controller, path, num_hosts, timeout=timeout, debug=debug)

        self._runner_args = [
            HwController.check_controller(index)
            for index in controller.indices[:num_hosts]
        ]

    @property
    def runner_args(self):
        return self._runner_args

    def stop(self):
        pass


def _asan_env():
    env = dict(os.environ)
    env.setdefault(
        "ASAN_OPTIONS",
        "detect_leaks=1:leak_check_at_exit=0:print_summary=1:abort_on_error=1:"
        "use_madv_dontdump=1:disable_coredump=0:unmap_shadow_on_exit=1:"
        "strict_string_checks=1:detect_stack_use_after_return=1:"
        "check_initialization_order=1:strict_init_order=1",
    )
    env.setdefault(
        "UBSAN_OPTIONS", "print_stacktrace=1:print_summary=1:abort_on_error=1"
    )
    env.setdefault("LSAN_OPTIONS", "exitcode=0:log_threads=1")
    return env
