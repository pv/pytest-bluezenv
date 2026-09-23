# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
VM host plugins
"""

import os
import sys
import subprocess
import collections
import logging
import tempfile
import time
import shutil
import queue
import signal
import functools
import threading
import traceback
import resource
import shutil
from pathlib import Path

import pytest
import pexpect
import dbus
from gi.repository import GLib

from . import env, utils, rpc

__all__ = [
    "host_config",
    "parametrized_host_config",
    "Bdaddr",
    "Bluetoothctl",
    "Bluetoothd",
    "Call",
    "DbusSession",
    "DbusSystem",
    "Obexd",
    "Pexpect",
    "Rcvbuf",
]


class Bdaddr(env.HostPlugin):
    """
    Host plugin providing ``host.bdaddr``. Loaded by default.
    """

    name = "bdaddr"

    def setup(self, impl):
        """
        Read the controller address and expose it as ``host.bdaddr``
        (VM side).

        Args:
            impl: lower-tester plugin manager.
        """
        self.value = utils.get_bdaddr()


class Rcvbuf(env.HostPlugin):
    """
    Host plugin setting pipe buffer size defaults. Loaded by default.

    Args:
        rcvbuf (int): default ``SO_RCVBUF`` (``rmem_default``) to set on
            the host.  Default: from the ``host_plugins.rcvbuf.default``
            ini option.
    """

    name = "rcvbuf"

    def __init__(self, rcvbuf=None):
        self.rcvbuf = rcvbuf

    def presetup(self, config):
        """
        Resolve the receive-buffer size from the ini default (parent side).
        """
        if self.rcvbuf is None:
            self.rcvbuf = config.getini("host_plugins.rcvbuf.default")

        self.rcvbuf = int(self.rcvbuf)

    def setup(self, impl):
        """
        Set the default socket receive buffer (VM side).

        Args:
            impl: lower-tester plugin manager.
        """
        self.log = logging.getLogger(self.name)

        self.log.info(f"Set SO_RCVBUF default = {self.rcvbuf}")
        with open("/proc/sys/net/core/rmem_default", "wb") as f:
            f.write(f"{self.rcvbuf}".encode("ascii"))


class Call(env.HostPlugin):
    """Host plugin providing ``host.call(func, *args, **kw)`` interface.

    Loaded by default.

    The ``host.call`` object is a :obj:`~pytest_bluezenv.Call.Proxy`
    that invokes the given function on the VM host side.

    Args:
        func (callable): function to run on the VM host.  It and its
            arguments must be picklable / importable on the VM.
        *args: positional arguments passed to ``func``.
        **kw: keyword arguments passed to ``func``; the extra keyword
            ``sync`` (default true) controls the return value.

    Returns:
        object: the return value of ``func`` if ``sync`` is true, else a
        :obj:`~pytest_bluezenv.Call.ResultProxy` whose ``wait()`` returns it
        later.

    Example:

        .. code-block:: python

           result = host0.call(my_func, 1, 2, 3)

    Example:

        .. code-block:: python

           result_async = host0.call(my_func, 1, 2, 3, sync=False)
           ...
           result = result_async.wait()

    """

    name = "call"

    def setup(self, impl):
        """
        Publish the call proxy as ``host.call`` (VM side).

        Args:
            impl: lower-tester plugin manager.
        """
        self._results = {}
        self._id = 0
        self.value = self.Proxy()

    def __call__(self, func, *a, **kw):
        """
        Run a function synchronously in the VM host.

        Args:
            func (callable): function to run.
            *a: positional arguments passed to ``func``.
            **kw: keyword arguments passed to ``func``.

        Returns:
            object: return value of ``func``.
        """
        return func(*a, **kw)

    def call_async(self, func, *a, **kw):
        """
        Run ``func`` on the VM and remember the result for ``wait_async``.
        Backs asynchronous (``sync=False``) calls.

        Args:
            func (callable): function to run.
            *a: positional arguments passed to ``func``.
            **kw: keyword arguments passed to ``func``.
        """
        value = None
        tb = None
        try:
            value = func(*a, **kw)
        except BaseException as exc:
            value = exc
            tb = traceback.format_exc()
            raise
        finally:
            self._id += 1
            self._results[self._id] = (value, tb)

    def wait_async(self, id_value):
        """
        Return and forget the stored result of an asynchronous call.

        Args:
            id_value (int): identifier returned for the asynchronous call.

        Returns:
            (value, traceback) If traceback is None, value is the function
            result, and otherwise value is a raised exception.

        """
        return self._results.pop(id_value)

    class Proxy(env.PluginProxy):
        """
        Upper-tester handle returned as ``host.call``. Calling it
        (``host.call(...)``) invokes a function on the VM host. See
        :obj:`~pytest_bluezenv.Call`.
        """

        def __init__(self):
            self._id = 0

        def __call__(self, func, *a, **kw):
            """
            Invoke ``func`` on the VM.

            Args:
                func (callable): function to run on the VM.
                *a: positional arguments to ``func``.
                ``**kw``: keyword arguments to ``func``; ``sync=False``
                    returns a :obj:`~pytest_bluezenv.Call.ResultProxy`
                    instead of blocking.

            Returns:
                object: the function result, or a
                :obj:`~pytest_bluezenv.Call.ResultProxy` when ``sync=False``.
            """
            if kw.pop("sync", True):
                return self._call("__call__", func, *a, **kw)
            else:
                self._conn.call_noreply(
                    "call_plugin", self._name, "call_async", func, *a, **kw
                )
                self._id += 1
                return Call.ResultProxy(self, self._id)

    class ResultProxy:
        """
        Handle for a ``sync=False`` :obj:`~pytest_bluezenv.Call`;
        ``wait()`` collects the result once the VM-side call has finished.
        """

        def __init__(self, plugin, id_value):
            """
            Store the parent-side call proxy and result identifier.

            Args:
                plugin (Call.Proxy): proxy that started the call.
                id_value (int): asynchronous call identifier.
            """
            self.plugin = plugin
            self.id_value = id_value

        def wait(self):
            """
            Wait for and return the result of the asynchronous call.

            Returns:
                object: return value of the VM-host function.

            Raises:
                RemoteError: the VM-host function raised. It is raised
                    here, when the result is collected, not at call time.
            """
            value, tb = self.plugin.wait_async(self.id_value)
            if tb is not None:
                raise rpc.RemoteError(value, tb)
            return value


class _Dbus(env.HostPlugin):
    def presetup(self, config):
        """
        Locate ``dbus-daemon`` on the parent host (skip the test if absent).
        """
        try:
            self.exe = utils.find_exe("", "dbus-daemon")
        except FileNotFoundError as exc:
            pytest.skip(reason=f"DBus: {exc!r}")

    def setup(self, impl):
        """
        Start a private ``dbus-daemon`` for this bus (VM side).
        """
        self.log = logging.getLogger(self.name)
        self.log_stream = utils.LogStream(self.name)

        self.tmpdir = utils.TmpDir(prefix=f"{self.name}-")
        self.config = Path(self.tmpdir.name) / "config.xml"

        socket = f"/run/dbus-{self.dbus_type}.socket"
        self.address = "unix:path={}".format(socket)

        # Have to set both, dbus-python needs both early
        os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = "unix:path=/run/dbus-system.socket"
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/dbus-session.socket"

        with open(self.config, "w") as f:
            text = f"""
            <!DOCTYPE busconfig PUBLIC
                    "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
                    "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
            <busconfig>
            <type>{self.dbus_type}</type>
            <listen>{self.address}</listen>
            <policy context="default">
            <allow user="*"/>
            <allow own="*"/>
            <allow send_type="method_call"/>
            <allow send_type="signal"/>
            <allow send_type="method_return"/>
            <allow send_type="error"/>
            <allow receive_type="method_call"/>
            <allow receive_type="signal"/>
            <allow receive_type="method_return"/>
            <allow receive_type="error"/>
            </policy>
            <limit name="reply_timeout">{round(utils.DEFAULT_TIMEOUT * 1000)}</limit>
            </busconfig>
            """
            f.write(text)

        cmd = [
            self.exe,
            "--nofork",
            "--nopidfile",
            "--nosyslog",
            f"--config-file={self.config}",
        ]

        self.log.debug(
            "Starting {} @ {}: {}".format(self.name, self.address, utils.quoted(cmd))
        )

        self.job = subprocess.Popen(
            cmd,
            stdout=self.log_stream.stream,
            stderr=subprocess.STDOUT,
        )
        utils.wait_files([self.job], [socket])
        self.log.debug(f"{self.name} ready")

    def teardown(self):
        """
        Stop the private ``dbus-daemon`` and clean up (VM side).
        """
        self.job.terminate()
        self.tmpdir.cleanup()


class DbusSystem(_Dbus):
    """
    Host plugin starting a private system D-Bus for VM-host plugins.

    Example:

        .. code-block:: python

           @host_config([DbusSystem(), MyPlugin()])
           def test_private_bus(hosts):
               ...

    Warning:
        dbus-python **MUST** be used only from the GLib main loop,
        as the library has concurrency bugs. All functions using it
        **MUST** either run from GLib main loop eg. via mainloop_wrap
    """

    name = "dbus-system"
    dbus_type = "system"


class DbusSession(_Dbus):
    """
    Host plugin starting a private session D-Bus for VM-host plugins.

    Example:

        .. code-block:: python

           @host_config([DbusSession(), MyPlugin()])
           def test_private_session_bus(hosts):
               ...

    Warning:
        dbus-python **MUST** be used only from the GLib main loop,
        as the library has concurrency bugs. All functions using it
        **MUST** either run from GLib main loop eg. via mainloop_wrap
    """

    name = "dbus-session"
    dbus_type = "session"


class Bluetoothd(env.HostPlugin):
    """
    Host plugin starting Bluetoothd.

    Args:
        debug (bool): pass ``-d`` to enable debug logging (default).
        conf (str): contents of ``main.conf``, written to a per-test
            config file.  Use it to set options such as ``ControllerMode``
            or ``Experimental``.
        args (sequence): extra command-line arguments for ``bluetoothd``.

    Depends on :obj:`~pytest_bluezenv.DbusSystem`.

    Example:

        .. code-block:: python

           @host_config([Bluetoothd(conf="[General]\\nExperimental = true")])
           def test_experimental(hosts):
               ...

    """

    name = "bluetoothd"
    depends = [DbusSystem()]

    def __init__(self, debug=True, conf=None, args=()):
        super().__init__()

        self.conf = conf
        self.args = tuple(args)
        if debug and "-d" not in self.args:
            self.args += ("-d",)

    def presetup(self, config):
        """
        Locate ``bluetoothd`` on the parent host (skip the test if absent).
        """
        try:
            self.exe = utils.find_exe("src", "bluetoothd")
        except FileNotFoundError as exc:
            pytest.skip(reason=f"Bluetoothd: {exc!r}")

    @utils.mainloop_wrap
    def setup(self, impl):
        """
        Start ``bluetoothd`` with a per-test config and state dir, and
        wait for the adapter to come up (VM side).
        """
        self.log = logging.getLogger(self.name)

        exe = self.exe

        self.tmpdir = utils.TmpDir(prefix="bluetoothd-state-")
        state_dir = Path(self.tmpdir.name) / "state"
        conf = Path(self.tmpdir.name) / "main.conf"

        state_dir.mkdir()

        if self.conf is None:
            with open(str(conf), "w") as f:
                pass
        else:
            with open(str(conf), "w") as f:
                f.write(self.conf)

        envvars = dict(os.environ)
        envvars["STATE_DIRECTORY"] = str(state_dir)

        cmd = [exe, "--nodetach", "-f", str(conf)] + list(self.args)

        self.log.info("Start bluetoothd: {}".format(utils.quoted(cmd)))

        self.log_stream = utils.LogStream("bluetoothd")
        self.job = subprocess.Popen(
            cmd,
            env=envvars,
            stdin=subprocess.DEVNULL,
            stdout=self.log_stream.stream,
            stderr=subprocess.STDOUT,
        )

        # Wait for the adapter to appear powered
        self.log.info("Wait for bluetoothd...")
        bus = utils.get_dbus()

        def cond():
            try:
                adapter = dbus.Interface(
                    bus.get_object("org.bluez", "/org/bluez/hci0"),
                    "org.freedesktop.DBus.Properties",
                )
                if adapter.Get("org.bluez.Adapter1", "Powered"):
                    return True
            except dbus.DBusException:
                return False

        utils.wait_until(cond)

        self.log.info("Bluetoothd ready")

    def teardown(self):
        """
        Stop ``bluetoothd`` and remove its state directory (VM side).
        """
        self.log.info("Stop bluetoothd")
        self.job.terminate()
        self.tmpdir.cleanup()


class Obexd(env.HostPlugin):
    """
    Host plugin starting obexd.

    Depends on :obj:`~pytest_bluezenv.Bluetoothd` and
    :obj:`~pytest_bluezenv.DbusSession`.

    Example:

        .. code-block:: python

           @host_config([Obexd()])
           def test_obex(hosts):
               ...
    """

    name = "obexd"
    depends = [Bluetoothd(), DbusSession()]

    def __init__(self):
        self.uuids = ("00001133-0000-1000-8000-00805f9b34fb",)

    def presetup(self, config):
        """
        Locate ``obexd`` on the parent host (skip the test if absent).
        """
        try:
            self.exe = utils.find_exe("obexd/src", "obexd")
        except FileNotFoundError as exc:
            pytest.skip(reason=f"Obexd: {exc!r}")

    @utils.mainloop_wrap
    def setup(self, impl):
        """
        Start ``obexd`` and wait for it to register with bluetoothd
        (VM side).
        """
        self.log = logging.getLogger(self.name)

        self.path = Path("/run/obex")
        self.path.mkdir()

        cmd = [self.exe, "--nodetach", f"--root={self.path}", "-d", "*"]
        self.log.info("Start obexd: {}".format(utils.quoted(cmd)))

        self.log_stream = utils.LogStream("obexd")
        self.job = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=self.log_stream.stream,
            stderr=subprocess.STDOUT,
        )

        # Wait for the service
        self.log.info("Wait for obexd...")
        bus = utils.get_dbus()
        adapter = dbus.Interface(
            bus.get_object("org.bluez", "/org/bluez/hci0"),
            "org.freedesktop.DBus.Properties",
        )

        def cond():
            uuids = [str(uuid) for uuid in adapter.Get("org.bluez.Adapter1", "UUIDs")]
            return all(uuid in uuids for uuid in self.uuids)

        utils.wait_until(cond)

        self.log.info("Obexd ready")

    def teardown(self):
        """
        Stop ``obexd`` and remove its root directory (VM side).
        """
        self.log.info("Stop obexd")
        self.job.terminate()
        shutil.rmtree(self.path)


class Pexpect(env.HostPlugin):
    r"""
    Host plugin for starting and controlling processes with pexpect,
    providing ``host.pexpect.spawn(...)`` interface.

    The ``host.pexpect`` object is a :obj:`~pytest_bluezenv.Pexpect.Proxy`.

    Example:

        .. code-block:: python

           btmgmt = host0.pexpect.spawn(find_exe("tools", "btmgmt"))
           btmgmt.send("info\n")
           btmgmt.expect("hci0")
           btmgmt.close()

    Example:

        .. code-block:: python

           with host0.pexpect.spawn(find_exe("tools", "btmgmt")) as btmgmt:
               btmgmt.send("info\n")
               btmgmt.expect("hci0")
    """

    name = "pexpect"
    depends = []

    def setup(self, impl):
        """
        Start the pexpect controller and publish it as ``host.pexpect``
        (VM side).

        Args:
            impl: lower-tester plugin manager.
        """
        self.ctls = {}
        self.ctl_id = 0
        self.log = logging.getLogger(self.name)

        self.log_stream = utils.LogStream(self.name)
        self.value = self.Proxy()

    def spawn(self, cmd):
        """
        Start a process on the host and record it. (VM side.)

        Args:
            cmd (list): command and arguments.

        Returns:
            int: spawned-process identifier. ``send``, ``expect`` and
            ``close`` take it to address the process.
        """
        from pexpect.popen_spawn import PopenSpawn

        self.log.info("Spawn {}".format(utils.quoted(cmd)))

        ctl = pexpect.popen_spawn.PopenSpawn(
            cmd,
            logfile=self.log_stream.stream,
            timeout=utils.DEFAULT_TIMEOUT,
        )
        self.ctl_id += 1
        self.ctls[self.ctl_id] = ctl
        return self.ctl_id

    def teardown(self):
        """
        Kill all processes spawned through this plugin (VM side).
        """
        for ctl in self.ctls.values():
            ctl.sendeof()
            ctl.kill(signal.SIGTERM)

    def close(self, ctl_id):
        """
        Close one spawned process and forget its handle.

        Args:
            ctl_id (int): spawned-process identifier.
        """
        ctl = self.ctls[ctl_id]
        ctl.sendeof()
        ctl.kill(signal.SIGTERM)
        del self.ctls[ctl_id]

    def expect(self, ctl_id, *a, **kw):
        """
        Wait for a pattern in one process' output.

        Args:
            ctl_id (int): spawned-process identifier.
            *a: positional arguments passed to ``pexpect.expect``.
            **kw: keyword arguments passed to ``pexpect.expect``.

        Returns:
            tuple: ``(index, groups)`` of the match, as in pexpect.
        """
        ctl = self.ctls[ctl_id]
        ret = ctl.expect(*a, **kw)
        self.log.debug("match found")
        return ret, ctl.match.groups()

    def send(self, ctl_id, *a, **kw):
        """
        Write to one process' standard input.

        Args:
            ctl_id (int): spawned-process identifier.
            *a: positional arguments passed to ``pexpect.send``.
            **kw: keyword arguments passed to ``pexpect.send``.

        Returns:
            int: number of bytes sent.
        """
        ctl = self.ctls[ctl_id]
        return ctl.send(*a, **kw)

    class Proxy(env.PluginProxy):
        """
        Upper-tester handle returned as ``host.pexpect``. ``spawn()``
        starts a process and returns a
        :obj:`~pytest_bluezenv.Pexpect.CtlProxy`.
        """

        def spawn(self, cmd):
            """
            Spawn a process on the VM; see
            :obj:`~pytest_bluezenv.Pexpect.spawn`.

            Args:
                cmd (sequence): command and arguments.

            Returns:
                Pexpect.CtlProxy: handle to the spawned process.
            """
            ctl_id = self._call("spawn", cmd)
            return Pexpect.CtlProxy(self, ctl_id)

    class CtlProxy:
        """
        Handle for one process spawned by :obj:`~pytest_bluezenv.Pexpect`.

        Attribute access dispatches over RPC, giving ``send``, ``expect``
        and ``close``.  Usable as a context manager (closes on exit).  The
        return values match the VM-side plugin methods.  ``expect()`` gives
        an ``(index, groups)`` tuple, see
        :obj:`~pytest_bluezenv.Pexpect.expect`. ``send()`` gives the number
        of bytes sent, see :obj:`~pytest_bluezenv.Pexpect.send`. ``close()``
        returns nothing.
        """

        def __init__(self, plugin, ctl_id):
            """
            Store a process handle.

            Args:
                plugin (Pexpect.Proxy): parent-side process plugin proxy.
                ctl_id (int): spawned-process identifier.
            """
            self._plugin = plugin
            self.ctl_id = ctl_id

        def __getattr__(self, name):
            return lambda *a, **kw: self._plugin._call(name, self.ctl_id, *a, **kw)

        def __enter__(self):
            return self

        def __exit__(self, type, value, tb):
            self.close()


class Bluetoothctl(env.HostPlugin):
    """
    Host plugin for starting and controlling ``bluetoothctl`` with pexpect.

    Example:

        .. code-block:: python

           @host_config([Bluetoothctl()])
           def test_info(hosts):
               hosts[0].bluetoothctl.send("show\\n")
    """

    name = "bluetoothctl"
    depends = [Bluetoothd()]

    def presetup(self, config):
        """
        Locate ``bluetoothctl`` on the parent host (skip if absent).
        """
        try:
            self.exe = utils.find_exe("client", "bluetoothctl")
        except FileNotFoundError as exc:
            pytest.skip(reason=f"Bluetoothctl: {exc!r}")

    def setup(self, impl):
        """
        Spawn ``bluetoothctl`` under pexpect (VM side).

        Args:
            impl: lower-tester plugin manager.
        """
        from pexpect.popen_spawn import PopenSpawn

        self.log = logging.getLogger(self.name)
        self.log_stream = utils.LogStream(self.name)

        # Note: pexpect.spawn doesn't work under load: using a PTY
        # appears to cause some messages be not received by
        # bluetoothctl
        self.ctl = pexpect.popen_spawn.PopenSpawn(
            self.exe, logfile=self.log_stream.stream, timeout=utils.DEFAULT_TIMEOUT
        )

    def teardown(self):
        """
        Close the ``bluetoothctl`` process (VM side).
        """
        self.ctl.sendeof()
        self.ctl.kill(signal.SIGTERM)

    def expect(self, *a, **kw):
        """
        Wait for a pattern in the ``bluetoothctl`` output.

        Args:
            *a: positional arguments passed to ``pexpect.expect``.
            **kw: keyword arguments passed to ``pexpect.expect``.

        Returns:
            tuple: ``(index, groups)`` of the match, as in pexpect.
        """
        ret = self.ctl.expect(*a, **kw)
        self.log.debug("match found")
        return ret, self.ctl.match.groups()

    def send(self, *a, **kw):
        """
        Write a command to the ``bluetoothctl`` prompt.

        Args:
            *a: positional arguments passed to ``pexpect.send``.
            **kw: keyword arguments passed to ``pexpect.send``.

        Returns:
            int: number of bytes sent.
        """
        return self.ctl.send(*a, **kw)


HOST_SETUPS = 0
DEFAULT_PLUGINS = [Rcvbuf(), Call()]
DEFAULT_PLUGINS_CONTROLLER = DEFAULT_PLUGINS + [Bdaddr()]


def _expand_plugins(plugins, controller):
    """
    Resolve plugin dependencies to linear load order
    """
    if controller:
        plugins = DEFAULT_PLUGINS_CONTROLLER + list(plugins)
    else:
        plugins = DEFAULT_PLUGINS + list(plugins)

    to_load = []
    seen = set()

    while plugins:
        deps = []
        for dep in plugins[0].depends or ():
            if type(dep).name not in seen:
                deps.append(dep)
                seen.add(type(dep).name)
                continue

        if deps:
            plugins = deps + plugins
            continue

        to_load.append(plugins.pop(0))

    return tuple(to_load)


def parametrized_host_config(
    param_host_setups, hw=False, mem=None, controller=True, ids=None, reuse=False
):
    """
    Declare parametrized host configurations.

    See https://docs.pytest.org/en/stable/how-to/parametrize.html for the
    concept.

    Args:
        param_host_setups (list): list of host setups
        hw (bool): whether to require hardware BT controller
        mem (str): amount of memory for the VM instances
        controller (bool): whether to add controller to the host
        ids (sequence): parameter IDs. Default: generated setup names.
        reuse (bool): whether to define a setup where the test host processes
            are not required to be torn down between tests. This is only useful
            for tests that do not perturb e.g. bluetoothd state too much.

    Returns:
        callable: decorator setting pytest attributes

    Example:

        .. code-block:: python

           bredr = [Bluetoothd()]
           le = [Bluetoothd(conf="[General]\\nControllerMode = le")]

           @parametrized_host_config(
                [[bredr], [le]],
                ids=["bredr", "le"],
            )
           def test_pairing_mode(hosts):
               ...
    """
    global HOST_SETUPS

    host_setups = []
    host_ids = []

    if ids is not None:
        if len(ids) != len(param_host_setups):
            raise ValueError("Wrong number of ids")
        host_ids = list(ids)

    num_hosts = set(len(setup) for setup in param_host_setups)
    if len(num_hosts) > 1:
        raise ValueError("Parametrized host setups must have same host count")
    num_hosts = num_hosts.pop()

    for host_setup in param_host_setups:
        setup = tuple(_expand_plugins(plugins, controller) for plugins in host_setup)

        name = f"hosts{HOST_SETUPS}"
        HOST_SETUPS += 1

        host_setup = dict(setup=setup, name=name, reuse=bool(reuse))
        host_setups.append(host_setup)

        if ids is None:
            host_ids.append(name)

    vm_setup = dict(
        num_hosts=num_hosts,
        hw=bool(hw),
        mem=str(mem) if mem else "",
        controller=bool(controller),
    )
    vm_ids = [
        "vm{}{}{}{}".format(
            len(setup),
            f"-{mem}" if mem else "",
            "-hw" if hw else "",
            "-noc" if not controller else "",
        )
    ]

    def decorator(func):
        func = pytest.mark.parametrize(
            "host_setup", host_setups, indirect=True, ids=host_ids
        )(func)
        func = pytest.mark.parametrize(
            "vm_setup", [vm_setup], indirect=True, ids=vm_ids
        )(func)
        return func

    return decorator


def host_config(*host_setup, hw=False, mem=None, controller=True, reuse=False):
    """
    Declare host configuration.

    Args:
        *host_setup: each argument is a list of plugins to be loaded on a host.
            The number of arguments specifies the number of hosts.
        hw (bool): whether to require hardware BT controller
        mem (str): amount of memory for the VM instances
        controller (bool): whether to add controller to the host
        reuse (bool): whether to define a setup where the test host processes
            are not required to be torn down between tests. This is only useful
            for tests that do not perturb e.g. bluetoothd state too much.

    Returns:
        callable: decorator setting pytest attributes

    Example:

        .. code-block:: python

           @host_config([Bluetoothd()], [Bluetoothd()])
           def test_something(hosts):
               host0, host1 = hosts

    Example:

        .. code-block:: python

           # Allow not restarting Bluetoothd between tests sharing this configuration
           base_config = host_config([Bluetoothd()], reuse=True)

           @base_config
           def test_one(hosts):
               host0, = hosts

           @base_config
           def test_two(hosts):
               # Note: uses same Bluetoothd() instance as above
               host0, = hosts

    """
    return parametrized_host_config(
        [host_setup], hw=hw, mem=mem, controller=controller, reuse=reuse
    )
