from bumble import data_types
from bumble.core import AdvertisingData
from bumble.profiles.battery_service import BatteryService

from pytest_bluezenv import (
    Bluetoothctl,
    BumbleController,
    BumbleDevice,
    host_config,
)


def add_battery_service(device):
    device.add_service(BatteryService(lambda connection: 80))


@host_config(
    [Bluetoothctl()],
    controller=BumbleController(
        devices={
            "sensor": BumbleDevice(
                config={"name": "BumbleSensor"},
                setup=add_battery_service,
            )
        },
    ),
)
def test_declared_device(hosts, bumble_env):
    (host0,) = hosts
    sensor = bumble_env.devices["sensor"]
    address = sensor.static_address.to_string(False)

    host0.bluetoothctl.send("scan on\n")
    host0.bluetoothctl.expect(f"Device {address} BumbleSensor")

    advertising_data = bytes(
        AdvertisingData(
            [
                data_types.Flags(
                    AdvertisingData.Flags.LE_GENERAL_DISCOVERABLE_MODE
                    | AdvertisingData.Flags.BR_EDR_NOT_SUPPORTED
                ),
                data_types.CompleteLocalName("RenamedSensor"),
            ]
        )
    )
    bumble_env.run(sensor.start_advertising(advertising_data=advertising_data))
    host0.bluetoothctl.expect("RenamedSensor")

    host0.bluetoothctl.send(f"connect {address}\n")
    host0.bluetoothctl.expect("Connected: yes")
