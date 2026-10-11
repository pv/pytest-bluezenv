# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Bumble-emulated controllers.

Kernel-free tests cover the `host_config` wiring and the runtime bridge
between the synchronous upper tester and bumble objects.  VM tests
assert the end-to-end mechanism: guest kernel driven by a bumble
controller, declared emulated devices discovered and connected from
the VM, and per-host custom controller behavior.

The VM tests are skipped unless --kernel and a built BlueZ tree are
given (see the vm_args fixture), and whenever the bumble package is
not installed.
"""

import asyncio

import pytest

from pytest_bluezenv import BumbleController, BumbleDevice, host_config
from pytest_bluezenv import _bumble as bumble_mod

PLUGIN = ["-p", "pytest_bluezenv"]

requires_bumble = pytest.mark.skipif(
    not bumble_mod.bumble_available(), reason="bumble package not installed"
)


# -- host_config wiring (no VM, no bumble needed) ----------------------------


def test_controller_type_validated():
    with pytest.raises(TypeError, match="controller must be"):
        host_config([], controller="bumble")


def test_hw_conflict_rejected():
    with pytest.raises(ValueError, match="hw=True"):
        host_config([], hw=True, controller=BumbleController())


def test_controllers_type_validated():
    with pytest.raises(TypeError):
        BumbleController(controllers=42)
    with pytest.raises(TypeError):
        BumbleController(controllers=[3])


def test_controllers_length_checked_at_setup():
    spec = BumbleController(controllers=[None, None])
    host_config([], controller=spec)
    spec.factories(2)


def test_devices_are_wrapped():
    plain = {"name": "Sensor"}
    spec = BumbleController(
        devices={"a": plain, "b": BumbleDevice(config=plain, power_on=False)}
    )
    assert isinstance(spec.devices["a"], BumbleDevice)
    assert spec.devices["a"].power_on
    assert spec.devices["a"].advertising
    assert not spec.devices["b"].power_on
    # config dict is copied, not captured live
    plain["name"] = "Changed"
    assert spec.devices["a"].config["name"] == "Sensor"


def test_spec_flows_to_vm_setup(pytester):
    pytester.makepyfile("""
        from pytest_bluezenv import host_config, BumbleController

        @host_config([], controller=BumbleController(
            devices={"sensor": {"name": "S"}}))
        def test_spec(host_setup, vm_setup):
            spec = vm_setup["controller"]
            assert isinstance(spec, BumbleController)
            assert spec.devices["sensor"].config["name"] == "S"
    """)
    pytester.runpytest(*PLUGIN).assert_outcomes(passed=1)


def test_parametrize_ids(pytester):
    pytester.makepyfile("""
        from pytest_bluezenv import host_config, BumbleController

        class FakeAddr:
            pass

        @host_config([], [], controller=BumbleController(
            controllers=[None, FakeAddr]))
        def test_ids(host_setup, vm_setup):
            pass

        @host_config([], controller=BumbleController())
        def test_plain(host_setup, vm_setup):
            pass
    """)
    result = pytester.runpytest(*PLUGIN, "--collect-only", "-q")
    result.stdout.fnmatch_lines(["*vm2-bumble-Controller+FakeAddr*"])
    result.stdout.fnmatch_lines(["*vm1-bumble*"])


# -- runtime bridge (bumble needed, no VM) -----------------------------------


@requires_bumble
def test_controllers_length_error_at_setup(tmp_path):
    spec = BumbleController(controllers=[None, None])
    with pytest.raises(ValueError, match="controllers for 1 hosts"):
        bumble_mod._BumbleRuntime(spec, tmp_path, 1, timeout=60)


@requires_bumble
def test_runtime_device_lifecycle(tmp_path):
    spec = BumbleController(devices={"sensor": {"name": "S"}})
    runtime = bumble_mod._BumbleRuntime(spec, tmp_path, 1, timeout=60)
    try:
        runtime.start_devices()
        sensor = runtime.env.devices["sensor"]
        assert sensor.is_advertising

        # starting for a new test keeps a device that is already there
        runtime.start_devices()
        assert runtime.env.devices["sensor"] is sensor

        # closing the hosts takes the devices down
        runtime.stop_devices()
        assert runtime.env.devices == {}

        # and the next host setup gets a fresh device
        runtime.start_devices()
        fresh = runtime.env.devices["sensor"]
        assert fresh is not sensor
        assert fresh.is_advertising
    finally:
        runtime.stop()
    assert runtime.link.controllers == set()


@requires_bumble
def test_runtime_gatt_roundtrip(tmp_path):
    from bumble import hci
    from bumble.device import Device, Peer
    from bumble.gatt import GATT_BATTERY_LEVEL_CHARACTERISTIC
    from bumble.hci import Address
    from bumble.host import Host
    from bumble.profiles.battery_service import BatteryService
    from bumble.transport.unix import open_unix_client_transport

    def add_battery(device):
        device.add_service(BatteryService(lambda connection: 80))

    spec = BumbleController(
        devices={
            "sensor": BumbleDevice(
                config={"name": "BumbleTest"},
                setup=add_battery,
            )
        }
    )
    runtime = bumble_mod._BumbleRuntime(spec, tmp_path, 1, timeout=60)
    try:
        runtime.start_devices()
        sensor = runtime.env.devices["sensor"]
        assert sensor.static_address.to_string(False).startswith("F1:")
        # the VM-host controller stays registered on the link
        assert len(runtime.link.controllers) == 2

        async def client():
            source_sink = await open_unix_client_transport(str(runtime.socket_paths[0]))
            async with source_sink as transport:
                device = Device(
                    address=Address("F0:00:00:00:00:FE"),
                    host=Host(transport.source, transport.sink),
                )
                await device.power_on()
                await device.start_scanning()

                found = asyncio.get_running_loop().create_future()

                def on_advertisement(advertisement):
                    if not found.done() and advertisement.address.to_string(
                        False
                    ) == sensor.static_address.to_string(False):
                        found.set_result(advertisement.address)

                device.on("advertisement", on_advertisement)
                connection = await device.connect(await asyncio.wait_for(found, 30))
                try:
                    peer = Peer(connection)
                    await peer.discover_services()
                    values = await peer.read_characteristics_by_uuid(
                        GATT_BATTERY_LEVEL_CHARACTERISTIC
                    )
                    assert values[0] == bytes([80])
                finally:
                    await device.disconnect(
                        connection,
                        hci.HCI_ErrorCode.REMOTE_USER_TERMINATED_CONNECTION_ERROR,
                    )

        bumble_mod._Loop.submit(client(), timeout=60)

        runtime.stop_devices()
        assert runtime.env.devices == {}
        assert len(runtime.link.controllers) == 1
    finally:
        runtime.stop()
    assert runtime.link.controllers == set()


# -- VM tests ----------------------------------------------------------------


def run_vm(pytester, vm_args, source, *extra):
    pytester.makepyfile(source)
    return pytester.runpytest(
        "-p", "pytest_bluezenv", "--vm-timeout", "180", *vm_args, *extra
    )


BUMBLE_VM_FEATURES = r"""
    import pytest

    pytest.importorskip("bumble")

    from pytest_bluezenv import (
        Bluetoothctl,
        BumbleController,
        host_config,
    )

    # One VM, shared by the three tests below.  With reuse=False (the
    # default) the host plugins, and with them the emulated devices,
    # are torn down and set up again around each test.
    base = host_config(
        [Bluetoothctl()],
        controller=BumbleController(devices={"sensor": {"name": "BumbleSensor"}}),
    )

    @base
    def test_host_identity(hosts, bumble_env):
        (host0,) = hosts
        controller, = bumble_env.controllers
        assert host0.bdaddr.upper().startswith("00:AA:02")
        assert host0.bdaddr.upper() == controller.public_address.to_string(False).upper()

    @base
    def test_vm_connects_emulated_device(hosts, bumble_env):
        (host0,) = hosts
        sensor = bumble_env.devices["sensor"]

        address = sensor.static_address.to_string(False)
        host0.bluetoothctl.send("scan on\n")
        host0.bluetoothctl.expect(f"Device {address} BumbleSensor")
        host0.bluetoothctl.send(f"connect {address}\n")
        host0.bluetoothctl.expect("Connection successful")

    # Same VM, but the test above and its device are gone.  The device
    # teardown must have dropped the open connection and taken the
    # device down cleanly, so that a fresh device is discovered and
    # connected here.
    @base
    def test_device_recreated(hosts, bumble_env):
        (host0,) = hosts
        sensor = bumble_env.devices["sensor"]

        address = sensor.static_address.to_string(False)
        host0.bluetoothctl.send("scan on\n")
        host0.bluetoothctl.expect(f"Device {address} BumbleSensor")
        host0.bluetoothctl.send(f"connect {address}\n")
        host0.bluetoothctl.expect("Connection successful")
"""


@requires_bumble
def test_bumble_vm_features(pytester, vm_args):
    run_vm(pytester, vm_args, BUMBLE_VM_FEATURES).assert_outcomes(passed=3)


CUSTOM_CONTROLLER = r"""
    import pytest

    pytest.importorskip("bumble")

    from bumble import hci
    from bumble.controller import Controller

    from pytest_bluezenv import Bluetoothctl, BumbleController, host_config

    FAKE_BDADDR = "02:AA:BB:CC:DD:EE"

    # Python alternative to btdev-style quirks: per-opcode HCI command
    # handlers are plain methods, override or add them freely.
    class FakeBdaddrController(Controller):
        def on_hci_read_bd_addr_command(self, command):
            return hci.HCI_Read_BD_ADDR_ReturnParameters(
                status=hci.HCI_ErrorCode.SUCCESS,
                bd_addr=hci.Address(FAKE_BDADDR),
            )

    @host_config(
        [Bluetoothctl()],
        [Bluetoothctl()],
        controller=BumbleController(controllers=[FakeBdaddrController, None]),
    )
    def test_custom_controller(hosts):
        host0, host1 = hosts

        # The guest kernel reads its address through the overridden handler.
        assert host0.bdaddr.upper() == FAKE_BDADDR
        # The stock controller factory still serves the other host.
        assert host1.bdaddr.upper().startswith("00:AA:02")
"""


@requires_bumble
def test_bumble_custom_controller(pytester, vm_args):
    run_vm(pytester, vm_args, CUSTOM_CONTROLLER).assert_outcomes(passed=1)
