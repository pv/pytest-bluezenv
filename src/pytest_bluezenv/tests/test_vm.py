# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
VM-using tests.

Each test asserts that a pytest-bluezenv *mechanism* works: booting a host,
marshalling values over RPC, driving an interactive process, surfacing async
D-Bus events, and capturing btmon output.  BlueZ/kernel is only the substrate;
no test asserts that the Bluetooth protocol itself is correct.

VM startup is expensive, so the controller-based features share a single host
configuration with `reuse=True` (one QEMU boot serves several test functions),
and `--btmon` is folded into the same run.  Only the no-controller
configuration needs its own boot.

Skipped unless --kernel and a built BlueZ tree are given (see the vm_args
fixture).
"""

import glob
from pathlib import Path


def run_vm(pytester, vm_args, source, *extra):
    pytester.makepyfile(source)
    return pytester.runpytest(
        "-p", "pytest_bluezenv", "--vm-timeout", "180", *vm_args, *extra
    )


# -- controller group: one 2-host boot shared by four tests ------------------


CONTROLLER_FEATURES = r"""
    import operator
    import os

    import pytest

    from pytest_bluezenv import (
        RemoteError,
        Agent,
        Bluetoothctl,
        host_config,
        wait_until,
    )

    # One setup, reused by all three tests below: the VM boots once.
    base = host_config(
        [Bluetoothctl(), Agent()],
        [Bluetoothctl(), Agent()],
        reuse=True,
    )

    # The tests below share one reused VM, and test order is not
    # guaranteed. bluetoothd rejects a second StartDiscovery from the same
    # client, so discovery is only started when it is not already running.
    # The strict StartDiscovery:reply check runs in whichever test starts
    # discovery.
    def ensure_discovering(host):
        if not host.agent.adapter_get("Discovering"):
            host.agent.adapter_method("StartDiscovery")
            host.agent.expect("org.bluez.Adapter1.StartDiscovery:reply")

    @base
    def test_process_expect(hosts):
        host0, host1 = hosts

        host0.bluetoothctl.send("show\n")
        idx, m = host0.bluetoothctl.expect(r"Controller ([0-9A-F:]{17})", timeout=60)
        # Regex group captured on the VM and returned over RPC.
        assert m[0].decode().upper() == host0.bdaddr.upper()
        host0.bluetoothctl.expect("Powered: yes")

        # expect_all waits for all patterns in any order, and returns
        # the matched groups per pattern in the order given.
        host0.bluetoothctl.send("show\n")
        groups = host0.bluetoothctl.expect_all(
            ["Powered: (yes|no)", r"Controller ([0-9A-F:]{17})"], timeout=60
        )
        assert groups[0][0].decode() == "yes"
        assert groups[1][0].decode().upper() == host0.bdaddr.upper()

    @base
    def test_agent_events(hosts):
        host0, host1 = hosts

        # A successful D-Bus call surfaces as a :reply event via expect(),
        # asserted inside ensure_discovering when discovery is started here.
        ensure_discovering(host0)

        # An unknown method surfaces as an :error event.
        host0.agent.adapter_method("ThisMethodDoesNotExist")
        host0.agent.expect("org.bluez.Adapter1.ThisMethodDoesNotExist:error")

        # adapter_get goes through get_dbus()/mainloop on the VM side.
        assert str(host0.agent.adapter_get("Address")).lower() == host0.bdaddr

        # host.call marshals code and args to the VM and back.
        assert host0.call(operator.add, 20, 22) == 42
        assert host0.call(os.getpid) != os.getpid()
        future = host0.call(operator.mul, 6, 7, sync=False)
        assert future.wait() == 42

    @base
    def test_agent_inbound_callback(hosts):
        host0, host1 = hosts

        host1.agent.adapter_set("Pairable", True)
        host1.agent.adapter_set("Discoverable", True)

        ensure_discovering(host0)
        wait_until(host0.agent.has_device, host1.bdaddr)
        host0.agent.device_method(host1.bdaddr, "Pair")

        # The plugin delivers the inbound RequestConfirmation callback to each
        # host as an Event, with the same passkey marshalled to both.
        confirm_0 = host0.agent.expect("org.bluez.Agent1.RequestConfirmation")
        confirm_1 = host1.agent.expect("org.bluez.Agent1.RequestConfirmation")
        assert confirm_0.passkey == confirm_1.passkey

        host0.agent.reply()
        host1.agent.reply()

        # Pair()'s completion is surfaced over RPC; assert the event is
        # delivered, not that bonding succeeded.
        event = host0.agent.expect(
            ["org.bluez.Device1.Pair:reply", "org.bluez.Device1.Pair:error"]
        )
        assert event.kind.startswith("org.bluez.Device1.Pair:")

        # Test device set/get API
        host0.agent.device_set(host1.bdaddr, "Trusted", True)
        assert host0.agent.device_get(host1.bdaddr, "Trusted")

        # Unknown device raises ValueError on the VM host; the queried
        # address must surface in the RemoteError message.
        with pytest.raises(RemoteError, match="address='00:11:22:33:44:55'"):
            host0.agent.device_get("00:11:22:33:44:55", "Trusted")

    @base
    def test_bluetoothctl_reject(hosts):
        host0, _ = hosts

        # A reject pattern watched alongside the expected ones does
        # not disturb a normal match.
        host0.bluetoothctl.send("show\n")
        host0.bluetoothctl.expect("Powered:", reject=[r"(Never appears)"], timeout=60)

        # A reject pattern matching aborts the wait, and the matched
        # output surfaces in the RemoteError message.
        host0.bluetoothctl.send("show\n")
        with pytest.raises(RemoteError, match="Powered: yes"):
            host0.bluetoothctl.expect(
                "Never appears", reject=[r"(Powered: yes)"], timeout=60
            )

        # expect_all watches the reject patterns in every round.
        host0.bluetoothctl.send("show\n")
        with pytest.raises(RemoteError, match="Powered: yes"):
            host0.bluetoothctl.expect_all(
                ["Controller", "Never appears"],
                reject=[r"(Powered: yes)"],
                timeout=60,
            )
"""


def test_vm_controller_features(pytester, vm_args):
    result = run_vm(pytester, vm_args, CONTROLLER_FEATURES, "--btmon")
    result.assert_outcomes(passed=4)

    # --btmon / Btmon dump was captured and copied out of the shared dir.
    dumps = [Path(d) for d in glob.glob(str(pytester.path / "test-bluezenv-*.btsnoop"))]
    assert dumps, "btmon btsnoop dump was not copied out"
    assert any(d.stat().st_size > 0 for d in dumps)


# -- reuse configuration: tests sharing a setup must see the same hosts ------


REUSE = r"""
    import os

    from pytest_bluezenv import host_config, Call

    base = host_config([Call()], reuse=True)

    # The VM-side tester keeps running between tests that reuse a setup, so
    # both tests must observe the same guest process.  The check is
    # symmetric: whichever test runs second compares the two.
    guest_pids = {}

    def record(name, hosts):
        pid = hosts[0].call(os.getpid)
        guest_pids[name] = pid
        other = guest_pids.get("second" if name == "first" else "first")
        assert other is None or other == pid

    @base
    def test_first(hosts):
        record("first", hosts)

    @base
    def test_second(hosts):
        record("second", hosts)
"""


def test_reuse_keeps_vm_host_across_tests(pytester, vm_args):
    result = run_vm(pytester, vm_args, REUSE)
    result.assert_outcomes(passed=2)


# -- no-controller configuration: its own (cheap) boot ----------------------


NO_CONTROLLER = r"""
    import functools
    import operator
    import os
    import subprocess
    import pytest

    from pytest_bluezenv import host_config, run, Pexpect, RemoteError

    @host_config([Pexpect()], controller=False)
    def test_no_controller(hosts):
        (host,) = hosts

        # RPC round-trip with no Bluetooth controller at all.
        assert host.call(operator.add, 20, 22) == 42
        assert host.call(os.getpid) != os.getpid()

        #future = host.call(operator.mul, 6, 7, sync=False)
        #assert future.wait() == 42

        # An exception raised by an async call is raised by wait().
        future = host.call(functools.partial(operator.floordiv, 1, 0), sync=False)
        with pytest.raises(RemoteError):
            future.wait()

        # utils.run executes a command in the guest and returns the result.
        result = host.call(
            run, ["sh", "-c", "echo hello"], stdout=subprocess.PIPE, encoding="utf-8"
        )
        assert result.returncode == 0
        assert result.stdout == "hello\n"

        # Pexpect drives an interactive process in the guest.  The command
        # prints markers then blocks on input, so it stays alive until
        # close() sends EOF.
        shell = host.pexpect.spawn(
            ["/bin/sh", "-c", "echo pexpect-ready; echo one 1; echo two 2; read x"]
        )
        try:
            index, groups = shell.expect("pexpect-ready")
            assert index == 0

            # expect_all waits for all patterns in any order, and
            # returns the matched groups per pattern in the order
            # given.
            groups = shell.expect_all([r"two (\d)", r"one (\d)"], timeout=30)
            assert [g[0].decode() for g in groups] == ["2", "1"]
        finally:
            shell.close()

        # A reject pattern watched alongside the expected ones does
        # not disturb a normal match, and matching one aborts the
        # wait with the matched output in the RemoteError message.
        shell = host.pexpect.spawn(
            ["/bin/sh", "-c", "echo ready; echo bad news; read x"]
        )
        try:
            shell.expect("ready", reject=[r"(never)"], timeout=30)
            with pytest.raises(RemoteError, match="bad news"):
                shell.expect("never", reject=[r"(bad news)"], timeout=30)
        finally:
            shell.close()
"""


def test_vm_no_controller(pytester, vm_args):
    run_vm(pytester, vm_args, NO_CONTROLLER).assert_outcomes(passed=1)
