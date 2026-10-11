# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
HW controller selection in ``HwController.select``.

``HwController.controller_bus`` and ``HwController.check_controller``
probe host hardware under ``/sys``.  The tests replace them with a
fixed synthetic controller set.
"""

import pytest

from pytest_bluezenv import controller

BUSES = {"hci0": "usb", "hci1": "usb", "hci2": "pci"}


class FakeConfig:
    def __init__(self, **options):
        self.option = type(
            "Options",
            (),
            {"usb": None, "pcie": None, "force_usb": False, "force_pcie": False},
        )()
        for name, value in options.items():
            setattr(self.option, name, value)

    def getoption(self, name):
        return getattr(self.option, name)


@pytest.fixture
def fake_controllers(monkeypatch, broken):
    def check_controller(cls, name):
        if name in broken:
            raise ValueError(f"{name} cannot be used")
        return ["-U", name]

    monkeypatch.setattr(
        controller.HwController,
        "controller_bus",
        classmethod(lambda cls, name: BUSES.get(name)),
    )
    monkeypatch.setattr(
        controller.HwController, "check_controller", classmethod(check_controller)
    )
    monkeypatch.delenv("FUNCTIONAL_TESTING_CONTROLLERS", raising=False)


@pytest.mark.parametrize(
    "options, controllers, broken, indices, messages",
    [
        # Only controllers on the requested bus are kept.
        ({"usb": "hci0,hci1,hci2"}, None, [], ["hci0", "hci1"], ["", ""]),
        ({"pcie": "hci0,hci1,hci2"}, None, [], ["hci2"], [""]),
        # Without bus options, both kinds are collected.
        ({}, "hci0,hci1,hci2", [], ["hci0", "hci1", "hci2"], ["", "", ""]),
        # Force options restrict to one kind even with an unset bus option.
        ({"force_usb": True}, "hci0,hci2", [], ["hci0"], [""]),
        ({"force_pcie": True}, "hci0,hci2", [], ["hci2"], [""]),
        # An unusable controller is dropped and reported.
        ({"usb": "hci0"}, None, ["hci0"], [], ["hci0 cannot be used"]),
        # Usable controllers come first even when the unusable one is named
        # first, so the skip reason shows one message per missing controller.
        ({"usb": "hci1,hci0"}, None, ["hci1"], ["hci0"], ["", "hci1 cannot be used"]),
    ],
)
def test_select(
    monkeypatch, fake_controllers, options, controllers, broken, indices, messages
):
    if controllers is not None:
        monkeypatch.setenv("FUNCTIONAL_TESTING_CONTROLLERS", controllers)

    config = FakeConfig(**options)

    assert controller.HwController.select(config) == (indices, messages)
