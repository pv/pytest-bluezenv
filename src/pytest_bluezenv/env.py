# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Test environment:

- one or more qemu instances running Linux kernel + BlueZ + other stack
- connected by btvirt, or real USB Bluetooth controllers
- Python RPC connection to each via unix socket <-> qemu chardev

"""

import struct
import sys
import os
import signal
import re
import pwd
import time
import argparse
import shutil
import glob
import threading
import tempfile
import operator
import logging
import socket
import pickle
import traceback
import resource
import warnings
import subprocess
from pathlib import Path
from subprocess import Popen, DEVNULL, PIPE, run

from gi.repository import GLib

from . import rpc, utils, _bumble

__all__ = ["HostPlugin", "HostProxy", "PluginProxy"]

log = logging.getLogger("env")


class HostPlugin:
    """
    Base class for plugins that run code in a VM host.

    Example:

        .. testcode::

           from pytest_bluezenv import HostPlugin

           class Ready(HostPlugin):
               name = "ready"

               def is_ready(self):
                   return True

    Attributes:
        name (str): unique name for the plugin
        depends (tuple[HostPlugin]): plugins to be loaded before this one
        value (object): object to appear as HostProxy attribute on parent side.
            If None, the plugin is represented by a proxy object that does RPC
            calls. Otherwise, must be a serializable value. If it is a subclass
            of :obj:`~pytest_bluezenv.PluginProxy`, ``set_connection`` is
            called after plugin load.

    """

    name = None
    depends = ()
    value = None

    def __init__(self):
        """
        Configure a plugin on the upper tester at collection time.

        """
        pass

    def presetup(self, config):
        """
        Configure a plugin on the upper tester before VM hosts start.

        Args:
            config (pytest.Config): pytest configuration object
        """
        pass

    def setup(self, impl):
        """
        Initialise a plugin in the VM host.

        Args:
            impl: lower-tester plugin manager.
        """
        pass

    def teardown(self):
        """Tear down a plugin in the VM host after its test instance."""
        pass


class HostProxy:
    """
    Upper-tester representation of one VM host with loadable plugins.

    Plugins are usually loaded by :obj:`~pytest_bluezenv.host_config`, but may
    also be loaded during a test.

    Loaded plugins appear as attributes on the host proxy.

    Example:

        .. testcode::

           from pytest_bluezenv import Bluetoothctl

           def test_bluetoothctl_show(hosts):
               host = hosts[0]
               host.load(Bluetoothctl())
               host.bluetoothctl.send("show\\n")
    """

    def __init__(self, path, timeout, name, progress_reporter=None, check_errors=None):
        """
        Create a VM-host proxy.

        Args:
            path (str): RPC socket path.
            timeout (float): default RPC timeout in seconds.
            name (str): VM-host logger name.
            progress_reporter: optional progress reporter for RPC calls.
            check_errors: optional callable raising when the VM host
                cannot come up anymore, e.g. its process died.
        """
        self._path = path
        self._active_conn = None
        self._timeout = timeout
        self._plugins = {}
        self._name = name
        self._progress_reporter = progress_reporter
        self._check_errors = check_errors

    def load(self, plugin: HostPlugin):
        """
        Load given plugin to the VM host synchronously.

        Args:
            plugin (HostPlugin): plugin to initialise.
        """
        self.start_load(plugin)
        self.wait_load()

    def set_instance_name(self, name):
        """
        Name this VM host instance on the parent side and on the VM.

        Args:
            name (str): instance name.
        """
        self.instance_name = name
        self._conn.call_noreply("set_instance_name", name)

    def start_load(self, plugin: HostPlugin):
        """
        Begin loading a plugin in the VM host. ``wait_load`` makes loaded
        plugins available.

        Args:
            plugin (HostPlugin): plugin to initialise.

        """
        if plugin.name in self._plugins:
            # Already loaded
            return
        self._conn.call_noreply("start_load", plugin)
        self._plugins[plugin.name] = None

    def wait_load(self, timeout=None):
        """
        Wait for plugin loads to complete, and make plugins available.

        Args:
            timeout (float): maximum wait in seconds. Default: RPC timeout.
        """
        for name, value in self._conn.call("wait_load", timeout=timeout).items():
            if value is None:
                value = PluginProxy()
            if isinstance(value, PluginProxy):
                value.set_connection(name, self._active_conn, self._progress_reporter)
            self._plugins[name] = value

    @property
    def _conn(self):
        if self._active_conn is None:
            self._active_conn = rpc.client_unix_socket(
                self._path,
                timeout=self._timeout,
                name=self._name,
                check=self._check_errors,
            )
        return self._active_conn

    def __getattr__(self, name):
        if name not in self._plugins:
            raise AttributeError(name)
        return self._plugins[name]

    def close(self):
        """
        Shutdown this VM host tester instance.
        """
        self._plugins = {}
        if self._active_conn is not None:
            self._active_conn.close()
            self._active_conn = None

    def _close_start(self):
        self._plugins = {}
        if self._active_conn is not None:
            self._active_conn.close_start()

    def _close_finish(self, force=False):
        if self._active_conn is not None:
            self._active_conn.close_finish(force=force)
            self._active_conn = None


class PluginProxy:
    """
    Upper-tester RPC proxy for a VM-host plugin.

    Attributes:
        _name (str): plugin name
        _conn (rpc.Connection): RPC connection
    """

    def __init__(self):
        self._name = None
        self._conn = None
        self._progress_reporter = None

    def set_connection(self, name, conn, progress_reporter=None):
        """
        Bind the proxy to a plugin name and its RPC connection.

        Args:
            name (str): plugin name this proxy represents.
            conn (rpc.Connection): RPC connection to the VM host. This is
                framework setup, not normal test-side use.
            progress_reporter: optional progress reporter for RPC calls.
        """
        self._name = name
        self._conn = conn
        self._progress_reporter = progress_reporter

    def __call__(self, *a, **kw):
        """
        Invoke the plugin's ``__call__`` method over RPC.

        Args:
            *a: positional arguments forwarded to the plugin.
            **kw: keyword arguments forwarded to the plugin.

        Returns:
            object: return value from the VM-host plugin.
        """
        return self._call("__call__", *a, **kw)

    def __getattr__(self, name):
        """
        Resolve a public VM-host plugin method as an RPC callable.

        Args:
            name (str): public plugin method name.

        Returns:
            callable: callable that forwards arguments and returns the
            VM-host method result.
        """
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **kw: self._call(name, *a, **kw)

    def _call(self, name, *args, **kwargs):
        reporter = self._progress_reporter
        if reporter is None:
            return self._conn.call("call_plugin", self._name, name, *args, **kwargs)
        # Progress reporting must never break the RPC call itself.
        report_kwargs = {k: v for k, v in kwargs.items() if k != "timeout"}
        token = None
        try:
            token = reporter.call_started(
                self._conn,
                f"{self._name}.{name}",
                kwargs.get("timeout"),
                args,
                report_kwargs,
            )
        except Exception:
            self._conn.log.debug("Progress reporting failed", exc_info=True)
        try:
            return self._conn.call("call_plugin", self._name, name, *args, **kwargs)
        finally:
            if token is not None:
                try:
                    reporter.call_finished(token)
                except Exception:
                    self._conn.log.debug("Progress reporting failed", exc_info=True)

    def _call_noreply(self, name, *a, **kw):
        self._conn.call_noreply("call_plugin", self._name, name, *a, **kw)


class Implementation:
    """
    VM-side main instance: setup/teardown plugins, plugin RPC server side
    """

    def __init__(self):
        self.plugins = {}
        self.plugin_order = []
        self.load_error = False

    def set_instance_name(self, name):
        """
        Set name for this tester instance
        """
        self.instance_name = name
        socket.sethostname(name)

    def start_load(self, plugin):
        """
        Start loading a plugin

        Args:
            plugin (HostPlugin): plugin to load
        """
        try:
            log.info(f"Plugin {plugin.name} load")
            plugin.setup(self)
        except:
            self.load_error = True
            raise
        self.plugins[plugin.name] = plugin
        self.plugin_order.append(plugin.name)
        log.info(f"Plugin {plugin.name} ready")

    def wait_load(self):
        """
        Wait until all plugins are loaded.

        Returns:
            dict: Mapping ``{name: plugin.value}``
        """
        if self.load_error:
            raise RuntimeError("load failed")
        log.debug(f"Plugins ready")
        return {p.name: getattr(p, "value", None) for p in self.plugins.values()}

    def _unload(self, name):
        self.plugin_order.remove(name)
        p = self.plugins.pop(name)
        method = getattr(p, "teardown", None)
        if method is not None:
            try:
                method()
            except BaseException as exc:
                tb = traceback.format_exc()
                log.error(f"Plugin {name} teardown error: {exc}\n{tb}")
                return False
        return True

    def call_plugin(self, name, method, *a, **kw):
        """
        Call a plugin method

        Args:
            name (str): plugin name
            method (str): method name
            *a: call arguments
            **kw: call keyword arguments

        Returns:
            object: plugin method call return value

        """
        return getattr(self.plugins[name], method)(*a, **kw)

    def teardown(self):
        """
        Unload all plugins
        """
        success = True
        while self.plugin_order:
            name = self.plugin_order[-1]
            log.info(f"Plugin {name} teardown")
            if not self._unload(name):
                success = False
            log.info(f"Plugin {name} teardown done")

        # Wait for child process core dumping
        _wait_core_dumps()

        if not success:
            raise RuntimeError("teardown failure")


def _wait_core_dumps():
    """
    Wait for core dumping processes.
    """

    # First check for completed child processes. Add 2 sec delay in
    # case core dumping started just in teardown and file isn't
    # created yet.
    for j in range(4):
        try:
            while True:
                pid, status = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    time.sleep(0.5)
                    break
        except ChildProcessError:
            break

    # If something is dumping core, wait for 'tee' writing the file
    for core in glob.glob("/run/shared/*.core"):
        log.info(f"Wait for core dump {core}")

        core_st = os.stat(core)
        while True:
            for fn in glob.glob("/proc/*/fd/*"):
                try:
                    st = os.stat(fn, follow_symlinks=True)
                    if (st.st_dev, st.st_ino) == (core_st.st_dev, core_st.st_ino):
                        found = fn
                        break
                except OSError:
                    pass
            else:
                break

            log.info(f"Waiting for core dump {core} ({found})")
            time.sleep(1)

    subprocess.run(["sync"])


def _find_vport(target_name, timeout=10):
    """
    Find RPC control virtio port. Ports may appear after boot, e.g. when
    the device announces them at a later simulated time.
    """
    end = time.monotonic() + timeout

    while True:
        ports = Path("/sys/class/virtio-ports")
        for port in ports.iterdir() if ports.is_dir() else ():
            try:
                with open(port / "name", "rb") as f:
                    name = f.read(64)
            except OSError:
                continue
            if name == target_name:
                return f"/dev/{port.name}"

        if time.monotonic() > end:
            raise RuntimeError(f"No virtio port {target_name} found")

        time.sleep(0.05)


class _RunnerLogHandler(logging.Handler):
    def __init__(self, stream):
        super().__init__()
        self.stream = stream

    def flush(self):
        self.stream.flush()

    def emit_simple(self, name, levelno, line, nsec):
        self.stream.write(f"\x00{name}\x01{levelno}\x02{nsec}\x03{line}\n")

    def emit(self, record):
        try:
            msg = record.getMessage()
            if record.exc_info:
                msg += "\n"
                msg += traceback.format_exception(*record.exc_info)
            name = record.name
            levelno = record.levelno
            nsec = getattr(record, "nsec", None)
            if nsec is None:
                nsec = int(record.created * 1e9)
            for line in msg.splitlines():
                self.emit_simple(name, levelno, line, nsec)
            self.stream.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)

    def start(self):
        self.flush_thread = threading.Thread(target=self._flush_thread, daemon=True)
        self.flush_thread.start()

    def _flush_thread(self):
        while True:
            time.sleep(0.5)
            self.stream.flush()


def _main_runner_instance():
    """
    VM-side tester main instance
    """
    from dbus.mainloop.glib import DBusGMainLoop

    # Start GLib mainloop early: dbus-python needs it
    loop = GLib.MainLoop()
    dbus_loop = DBusGMainLoop(set_as_default=True)
    loop_thread = threading.Thread(target=loop.run, daemon=True)
    loop_thread.start()

    utils.SIMPLE_LOG_HANDLER.start()
    try:
        dev = _find_vport(b"pytest-bluezenv-rpc\n")
        log.info(f"Test RPC server on {dev}")

        # If no messages were handled from /dev/vport, upper tester is
        # probably not connected. We can directly retry in this worker
        # as the tester has done no work yet.
        while rpc.server_file(dev, Implementation()) == 0:
            log.info(f"Waiting for upper tester...")
            time.sleep(0.5)
    finally:
        utils.SIMPLE_LOG_HANDLER.flush()
        loop.quit()
        log.info(f"Test RPC server quit")


def _is_uml_guest():
    """
    Whether running as a User Mode Linux guest: test-runner marks the
    kernel command line of its UML guests with TESTUML=1.
    """
    try:
        with open("/proc/cmdline") as f:
            return "TESTUML=1" in f.read().split()
    except OSError:
        return False


def _setup_vm_instance():
    # Mount shared path
    path = Path("/run/shared")
    if not path.is_dir():
        path.mkdir()
        run(["mount", "-t", "9p", "/dev/shared", str(path)], check=True)

    # Setup sys.path & defaults
    with open("/run/shared/defaults", "rb") as f:
        sys.path, utils.SRC_DIR, utils.BUILD_DIR, utils.DEFAULT_TIMEOUT = pickle.load(f)

    # Set up core dumps: use a pipe since 9p doesn't support user ID
    # maps and core dumping there is refused due to permissions
    with open("/proc/sys/kernel/core_pattern", "w") as f:
        f.write("|/usr/bin/env tee /run/shared/test-bluezenv-%h-%e-%t-%p.core")

    resource.setrlimit(
        resource.RLIMIT_CORE, (resource.RLIM_INFINITY, resource.RLIM_INFINITY)
    )

    # Set up default ASAN options
    os.environ["ASAN_OPTIONS"] = (
        "detect_leaks=1:leak_check_at_exit=0:print_summary=1:abort_on_error=1:"
        "use_madv_dontdump=1:disable_coredump=0:unmap_shadow_on_exit=1:"
        "strict_string_checks=1:detect_stack_use_after_return=1:"
        "check_initialization_order=1:strict_init_order=1:"
        "quarantine_size_mb=16"
    )
    os.environ["UBSAN_OPTIONS"] = "print_stacktrace=1:print_summary=1:abort_on_error=1"
    os.environ["LSAN_OPTIONS"] = "exitcode=0:log_threads=1"

    # Start (a)getty
    try:
        exe = utils.find_exe("", "agetty")
    except FileNotFoundError:
        log.warning("agetty not available")
        exe = None
    try:
        setsid = utils.find_exe("", "setsid")
    except FileNotFoundError:
        log.warning("setsid not available")
        setsid = None

    # User Mode Linux registers phantom /dev/ttyS0..63 host pty devices
    if (
        exe is not None
        and setsid is not None
        and not _is_uml_guest()
        and Path("/dev/ttyS1").exists()
    ):
        # Use shell script for restarting getty: uses less memory than Python
        script = Path("/tmp/getty.script")
        with open(script, "w") as f:
            f.write(
                f'#!/bin/sh\nwhile true; do "{setsid}" "{exe}" -n -h -L -l /bin/bash ttyS1; done'
            )

        os.chmod(script, 0o755)

        pid = os.fork()
        if pid == 0:
            os.setsid()
            os.execv(script, [script])
            os._exit(1)

    _start_chronyd()


def _start_chronyd():
    global _CHRONYD

    try:
        exe = utils.find_exe("", "chronyd")
    except FileNotFoundError:
        log.warning("chronyd not available")
        return

    if not Path("/dev/ptp0").exists():
        log.warning("/dev/ptp0 not available")
        return

    tmpdir = tempfile.mkdtemp(prefix=f"chronyd-")
    config = Path(tmpdir) / "chronyd.conf"

    with open(config, "w") as f:
        text = f"makestep 0.1 3\nrefclock PHC /dev/ptp0 poll -2\n"
        f.write(text)

    cmd = [exe, "-n", "-f", str(config), "-q"]
    log.debug("Synchronizing clock: {}".format(utils.quoted(cmd)))
    subprocess.run(cmd, check=True)

    cmd = [exe, "-n", "-f", str(config)]
    log.debug("Starting chronyd: {}".format(utils.quoted(cmd)))
    _CHRONYD = subprocess.Popen(cmd)


def _reset_vm_instance():
    # Power controller off to reset and match state at boot
    btmgmt = utils.find_exe("tools", "btmgmt")
    run([btmgmt, "power", "off"], check=True)


def _main_runner():
    """
    VM-side tester supervisor
    """
    log_port = _find_vport(b"pytest-bluezenv-log\n")
    log_stream = open(log_port, "w", encoding="utf-8", errors="surrogateescape")
    utils.SIMPLE_LOG_HANDLER = _RunnerLogHandler(log_stream)
    logging.basicConfig(level=0, handlers=[utils.SIMPLE_LOG_HANDLER])

    # Basic VM setup
    _setup_vm_instance()

    # Preload libraries
    import dbus
    import pexpect

    # Keep one instance running
    while True:
        log.info("Starting test instance")

        _reset_vm_instance()

        pid = os.fork()
        if pid == 0:
            os.setpgid(0, 0)
            _main_runner_instance()
            os._exit(0)
        else:
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass

            log.info("Terminating test instance")

            done = False

            while not done:
                for sig in [signal.SIGTERM, signal.SIGCONT, signal.SIGKILL]:
                    try:
                        os.kill(-pid, sig)
                        time.sleep(0.5 if sig == signal.SIGCONT else 0.1)
                    except ProcessLookupError:
                        done = True
                        break


ENV_INDEX = -1


class Environment:
    DEFAULT_MEM = None

    def __init__(
        self,
        kernel,
        num_hosts,
        hw_indices=None,
        timeout=20,
        mem=None,
        controller=True,
        btvirt_debug=False,
        progress_reporter=None,
    ):
        self.kernel = str(self.find_kernel(kernel))
        # A User Mode Linux kernel is an executable (ELF), not a bzImage
        self.uml = self.is_uml_kernel(self.kernel)

        if not mem and self.DEFAULT_MEM:
            mem = self.DEFAULT_MEM

        self.num_hosts = operator.index(num_hosts)
        self.jobs = []
        self.kill_jobs = set()
        self.log_streams = []
        self.hosts = []
        self.timeout = float(timeout)
        self.path = None
        self.reuse_group = None
        self.mem = mem
        self.controller = controller
        self.bumble = None
        self.btvirt_debug = btvirt_debug
        self.progress_reporter = progress_reporter

        if hw_indices is None:
            self.hw_indices = None
        elif hw_indices is not None and self.num_hosts <= len(hw_indices):
            self.hw_indices = tuple(hw_indices)
        else:
            raise ValueError(
                "Controller passthrough enabled, but not enough controllers"
                " for each host"
            )

        if sys.version_info >= (3, 12):
            self.runner = [sys.executable, "-P"]
        else:
            self.runner = [sys.executable]
        self.runner += [str((Path(__file__).parent / "runner.py").absolute())]

    @staticmethod
    def find_kernel(kernel):
        """
        Kernel image to use: given file, or the bzImage or (User Mode Linux)
        linux binary of a built kernel tree.
        """
        path = Path(kernel)
        if not path.is_dir():
            return path

        bzimage = path / "arch" / "x86" / "boot" / "bzImage"
        if not bzimage.exists() and Environment.is_uml_kernel(path / "linux"):
            return path / "linux"

        return bzimage

    @staticmethod
    def is_uml_kernel(kernel):
        """
        Whether the kernel is a User Mode Linux binary: an ELF executable
        with the .uml.setup.init section, as test-runner checks, unlike
        e.g. a vmlinux that QEMU can boot.
        """
        try:
            with open(kernel, "rb") as f:
                hdr = f.read(64)
                # 64-bit little-endian ELF, as built for x86_64
                if hdr[:6] != b"\x7fELF\x02\x01":
                    return False

                (shoff,) = struct.unpack_from("<Q", hdr, 0x28)
                shentsize, shnum, shstrndx = struct.unpack_from("<HHH", hdr, 0x3A)

                f.seek(shoff)
                shdrs = f.read(shnum * shentsize)
                if shentsize < 4 or len(shdrs) < shnum * shentsize:
                    return False
                strtab, strsize = struct.unpack_from(
                    "<QQ", shdrs, shstrndx * shentsize + 0x18
                )

                f.seek(strtab)
                names = f.read(strsize)
        except (OSError, struct.error):
            return False

        for i in range(shnum):
            (name,) = struct.unpack_from("<I", shdrs, i * shentsize)
            if names[name:].split(b"\0", 1)[0] == b".uml.setup.init":
                return True

        return False

    def start(self):
        self.path = Path(tempfile.mkdtemp(prefix="pytest-bluezenv-"))

        if self.uml:
            if self.hw_indices is not None:
                raise ValueError(
                    "Controller passthrough is not supported with User Mode Linux"
                )
            if isinstance(self.controller, _bumble.BumbleController):
                raise ValueError(
                    "Bumble controllers are not supported with User Mode Linux"
                )
            paths, names = self._start_uml()
            self._start_hosts(paths, names)
            return

        if isinstance(self.controller, _bumble.BumbleController):
            args = self._start_bumble()
        elif self.controller:
            if self.hw_indices is None:
                args = self._start_btvirt()
            else:
                args = self._start_hw()
        else:
            args = [[]] * self.num_hosts

        paths, names = self._start_runners(args)
        self._start_hosts(paths, names)

    def stop(self):
        # Stop in reverse start order: VM hosts before the btvirt serving
        # their devices, which User Mode Linux guests do not survive losing
        while self.jobs:
            job = self.jobs.pop()
            if job.poll() is None:
                if job in self.kill_jobs:
                    job.kill()
                else:
                    job.terminate()
                job.wait()
        self.kill_jobs.clear()

        if self.bumble is not None:
            runtime = self.bumble._runtime
            self.bumble = None
            runtime.stop()

        while self.log_streams:
            self.log_streams.pop().close()

        while self.hosts:
            try:
                self.hosts.pop().close()
            except rpc.RemoteError:
                # error already logged
                pass

        # Clean up tmpdir (btvirt, bumble, own sockets, rmdir)
        if self.path is not None:
            for f in list(self.path.iterdir()):
                if f.name.startswith(("bt-", "con-")):
                    f.unlink()
                if f.name.startswith("bumble-"):
                    f.unlink()
                if f.name.startswith("shared-"):
                    shutil.rmtree(f.resolve(), ignore_errors=True)
                    continue
                if f.name.startswith("pytest-bluezenv-"):
                    f.unlink()

            self.path.rmdir()
            self.path = None

    def check_job_errors(self):
        errors = []

        for job in self.jobs:
            if job.poll() is not None:
                cmd = utils.quoted(job.args)
                errors.append("'{}' terminated unexpectedly".format(cmd))

        if self.bumble is not None:
            errors += self.bumble._runtime.check_errors()

        return errors

    def _raise_job_errors(self):
        errors = self.check_job_errors()
        if errors:
            raise RuntimeError("\n".join(errors))

    def close_hosts(self):
        try:
            for h in self.hosts:
                h._close_start()
        finally:
            errors = []
            for h in self.hosts:
                try:
                    h._close_finish(force=bool(errors))
                except Exception as exc:
                    tb = "\n    ".join(traceback.format_exc().split("\n"))
                    errors.append(
                        f"{exc}\nError closing {h._name}: Traceback:\n    {tb}"
                    )

            errors += self.check_job_errors()

            if self.bumble is not None:
                self.bumble._stop_devices()

            if errors:
                errors = "\n".join(errors)
                raise RuntimeError(f"Errors closing hosts:\n{errors}")

    def _add_log(self, *a, cls=utils.LogStream, **kw):
        f = cls(*a, **kw)
        self.log_streams.append(f)
        return f.stream

    def _get_asan_env(self):
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

    def _start_btvirt(self):
        exe = utils.find_exe("emulator", "btvirt")
        logger = self._add_log("btvirt")

        cmd = [exe, f"--server={self.path}"]
        if self.btvirt_debug:
            cmd.append("-d")
        log.info("Starting btvirt: {}".format(utils.quoted(cmd)))

        job = Popen(
            cmd, stdout=logger, stderr=logger, stdin=DEVNULL, env=self._get_asan_env()
        )
        self.jobs.append(job)

        socket = self.path / "bt-server-bredrle"
        utils.wait_files([job], [socket])
        return [[f"-u{socket}"]] * self.num_hosts

    def _start_bumble(self):
        runtime = _bumble._BumbleRuntime(
            self.controller,
            self.num_hosts,
            self.path,
            timeout=self.timeout,
            debug=self.btvirt_debug,
        )
        log.info("Starting bumble controllers")
        runtime.start()
        self.bumble = runtime.env
        return [[f"-u{socket}"] for socket in runtime.socket_paths]

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

    def _start_hw(self):
        args = []

        for index in self.hw_indices[: self.num_hosts]:
            args.append(self.check_controller(index))

        return args

    def _uml_mem(self):
        """
        Memory size for UML's mem=, which takes a plain number as bytes
        where --vm-mem takes it as MiB, as QEMU does.
        """
        mem = str(self.mem or "256M").strip()
        return f"{mem}M" if mem.isdigit() else mem

    def _start_uml(self):
        """
        Start User Mode Linux VM hosts with test-runner, with btvirt serving
        their controllers and RPC and log channels as vhost-user devices.

        The hosts run on real time: time travel runs the guests in
        lock-step, one at a time, which makes tests exchanging traffic
        between hosts slower than real time.
        """
        global ENV_INDEX

        ENV_INDEX += 1

        btvirt = utils.find_exe("emulator", "btvirt")
        logger = self._add_log("btvirt")

        cmd = [btvirt]
        if self.btvirt_debug:
            cmd.append("-d")
        if self.controller:
            cmd += [f"-V{self.path}"]
        for idx in range(self.num_hosts):
            cmd += [
                f"--console={self.path}/con-{idx}"
                ":pytest-bluezenv-rpc:pytest-bluezenv-log"
            ]

        log.info("Starting btvirt: {}".format(utils.quoted(cmd)))
        job = Popen(
            cmd, stdout=logger, stderr=logger, stdin=DEVNULL, env=self._get_asan_env()
        )
        self.jobs.append(job)

        # Every socket the hosts connect to: btvirt creates the console
        # relay sockets after the console one, and the controller last
        files = []
        for idx in range(self.num_hosts):
            con = self.path / f"con-{idx}"
            files += [
                con,
                Path(f"{con}-pytest-bluezenv-rpc"),
                Path(f"{con}-pytest-bluezenv-log"),
            ]
        if self.controller:
            files.append(self.path / "bt-vhost-bredrle")
        utils.wait_files([job], files)

        test_runner = utils.find_exe("tools", "test-runner")
        socket_paths = []
        host_names = []

        for idx in range(self.num_hosts):
            shared_path = self.path / f"shared-{idx}"
            shared_path.mkdir()

            with open(shared_path / "defaults", "wb") as f:
                pickle.dump(
                    (
                        sys.path,
                        utils.SRC_DIR,
                        utils.BUILD_DIR,
                        utils.DEFAULT_TIMEOUT * 3 / 4,
                    ),
                    f,
                )

            # Kernel parameters, test-runner passes -o to User Mode Linux
            con = self.path / f"con-{idx}"
            params = [
                f"mem={self._uml_mem()}",
                f"BLUEZENV_SHARED={shared_path}",
                f"virtio_uml.device={con}:3",
            ]
            if self.controller:
                params += [f"virtio_uml.device={self.path}/bt-vhost-bredrle:40"]

            cmd = [test_runner, f"--kernel={self.kernel}", "--real-time"]
            for p in params:
                cmd += ["-o", p]
            cmd += ["--"] + self.runner

            log.info("Starting host: {}".format(utils.quoted(cmd)))

            host_names.append(f"host.{ENV_INDEX}.{idx}")

            logger = self._add_log(host_names[-1])
            job = Popen(cmd, stdout=logger, stderr=logger, stdin=DEVNULL)
            self.jobs.append(job)
            # User Mode Linux shuts down on SIGTERM in a context where its
            # virtio devices cannot be removed, and nothing is lost by
            # killing it as the runner keeps no state
            self.kill_jobs.add(job)

            log_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            log_sock.connect(f"{con}-pytest-bluezenv-log")
            self._add_log(
                host_names[-1],
                pattern=".*\x00([^\x00-\x03]+)\x01([^\x00-\x03]+)\x02([^\x00-\x03]+)\x03",
                stream=log_sock,
            )

            socket_paths.append(f"{con}-pytest-bluezenv-rpc")

        return socket_paths, host_names

    def _start_runners(self, args):
        global ENV_INDEX

        test_runner = utils.find_exe("tools", "test-runner")

        socket_paths = []
        host_names = []

        ENV_INDEX += 1

        for idx, arg in enumerate(args):
            socket_path = str(self.path / f"pytest-bluezenv-rpc-{idx}")
            socket_paths.append(socket_path)

            tty_path = str(self.path / f"pytest-bluezenv-tty-{idx}")
            log_path = str(self.path / f"pytest-bluezenv-log-{idx}")

            shared_path = self.path / f"shared-{idx}"
            shared_path.mkdir()

            # Python import paths & timeout
            with open(shared_path / "defaults", "wb") as f:
                pickle.dump(
                    (
                        sys.path,
                        utils.SRC_DIR,
                        utils.BUILD_DIR,
                        utils.DEFAULT_TIMEOUT * 3 / 4,
                    ),
                    f,
                )

            # RPC socket
            qemu_args = [
                "-chardev",
                f"socket,id=ser0,path={socket_path},server=on,wait=off",
            ]

            qemu_args += [
                "-device",
                "virtio-serial",
                "-device",
                "virtserialport,chardev=ser0,name=pytest-bluezenv-rpc",
            ]

            # Separate TTY access
            qemu_args += [
                "-chardev",
                f"socket,id=ser1,path={tty_path},server=on,wait=off",
            ]

            qemu_args += [
                "-device",
                "pci-serial,chardev=ser1",
            ]

            # Log socket
            qemu_args += [
                "-chardev",
                f"socket,id=ser2,path={log_path},server=on,wait=on",
            ]

            qemu_args += [
                "-device",
                "virtio-serial",
                "-device",
                "virtserialport,chardev=ser2,name=pytest-bluezenv-log",
            ]

            # Shared filesystem
            qemu_args += [
                "-fsdev",
                f"local,id=fsdev-shared,path={shared_path},readonly=off,security_model=none,multidevs=remap",
                "-device",
                "virtio-9p-pci,fsdev=fsdev-shared,mount_tag=/dev/shared",
            ]

            if self.mem:
                qemu_args += ["-m", str(self.mem)]

            extra_args = []
            for q in qemu_args:
                extra_args += ["-o", q]

            extra_args += ["-H"]

            cmd = (
                [test_runner, f"--kernel={self.kernel}"]
                + arg
                + extra_args
                + ["--"]
                + self.runner
            )

            log.info("Starting host: {}".format(utils.quoted(cmd)))
            log.info(f"TTY: socat {tty_path} STDIO,rawer")

            host_names.append(f"host.{ENV_INDEX}.{idx}")

            logger = self._add_log(host_names[-1])
            self.jobs.append(Popen(cmd, stdout=logger, stderr=logger, stdin=DEVNULL))

            # Start log reader
            utils.wait_files(self.jobs, [log_path])

            log_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            log_sock.connect(log_path)
            self._add_log(
                host_names[-1],
                pattern=".*\x00([^\x00-\x03]+)\x01([^\x00-\x03]+)\x02([^\x00-\x03]+)\x03",
                stream=log_sock,
            )

        utils.wait_files(self.jobs, socket_paths)

        return socket_paths, host_names

    def _start_hosts(self, socket_paths, host_names):
        if len(socket_paths) != self.num_hosts:
            raise RuntimeError("Wrong number of sockets")

        for path, name in zip(socket_paths, host_names):
            host = HostProxy(
                path,
                timeout=self.timeout,
                name=name,
                progress_reporter=self.progress_reporter,
                check_errors=self._raise_job_errors,
            )
            self.hosts.append(host)

    def __del__(self):
        self.stop()

    def __enter__(self):
        try:
            self.start()
        except:
            self.stop()
            raise
        return self

    def __exit__(self, type, value, tb):
        self.stop()
