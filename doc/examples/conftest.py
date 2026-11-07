import importlib.machinery
import importlib.util
import sys
import types

import pytest

_bumble_missing = importlib.util.find_spec("bumble") is None

if _bumble_missing:
    bumble = types.ModuleType("bumble")
    bumble.__spec__ = importlib.machinery.ModuleSpec("bumble", loader=None)

    controller = types.ModuleType("bumble.controller")
    hci = types.ModuleType("bumble.hci")
    profiles = types.ModuleType("bumble.profiles")
    battery_service = types.ModuleType("bumble.profiles.battery_service")

    class Controller:
        pass

    class Address:
        def __init__(self, value):
            self.value = value

    class HCI_Read_BD_ADDR_ReturnParameters:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class BatteryService:
        def __init__(self, *args, **kwargs):
            pass

    controller.Controller = Controller
    hci.Address = Address
    hci.HCI_Read_BD_ADDR_ReturnParameters = HCI_Read_BD_ADDR_ReturnParameters
    hci.HCI_ErrorCode = types.SimpleNamespace(SUCCESS=0)
    battery_service.BatteryService = BatteryService
    profiles.battery_service = battery_service
    bumble.controller = controller
    bumble.hci = hci
    bumble.profiles = profiles

    sys.modules["bumble"] = bumble
    sys.modules["bumble.controller"] = controller
    sys.modules["bumble.hci"] = hci
    sys.modules["bumble.profiles"] = profiles
    sys.modules["bumble.profiles.battery_service"] = battery_service


def pytest_collection_modifyitems(items):
    if _bumble_missing:
        for item in items:
            item.add_marker(pytest.mark.skip(reason="bumble package not installed"))
