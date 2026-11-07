from bumble import hci
from bumble.controller import Controller

from pytest_bluezenv import Bluetoothctl, BumbleController, host_config

FAKE_BDADDR = "02:AA:BB:CC:DD:EE"


class FakeBdaddrController(Controller):
    def on_hci_read_bd_addr_command(self, command):
        return hci.HCI_Read_BD_ADDR_ReturnParameters(
            status=hci.HCI_ErrorCode.SUCCESS,
            bd_addr=hci.Address(FAKE_BDADDR),
        )


@host_config(
    [Bluetoothctl()],
    controller=BumbleController(controllers=FakeBdaddrController),
)
def test_custom_controller(hosts):
    (host0,) = hosts
    assert host0.bdaddr.upper() == FAKE_BDADDR
