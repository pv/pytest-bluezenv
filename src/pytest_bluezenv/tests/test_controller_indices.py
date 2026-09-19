# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
HW controller selection through the hw_indices fixture.

``Environment.controller_bus`` and ``Environment.check_controller`` probe
host hardware under ``/sys``.  The tests replace them with a fixed
synthetic controller set.
"""

import pytest

from pytest_bluezenv import env

BUSES = {"hci0": "usb", "hci1": "usb", "hci2": "pci"}

HW_TEST = """
    def test_hw_indices(hw_indices):
        indices, messages = hw_indices
        assert indices == {indices!r}
        # Usable controllers come first, so the skip reason can show at most
        # one message per missing controller.
        assert messages == {messages!r}
"""


@pytest.fixture
def fake_controllers(monkeypatch, broken):
    def check_controller(cls, name):
        if name in broken:
            raise ValueError(f"{name} cannot be used")
        return ["-U", name]

    monkeypatch.setattr(
        env.Environment,
        "controller_bus",
        classmethod(lambda cls, name: BUSES.get(name)),
    )
    monkeypatch.setattr(
        env.Environment, "check_controller", classmethod(check_controller)
    )


@pytest.mark.parametrize(
    "options, controllers, broken, indices, messages",
    [
        # Only controllers on the requested bus are kept.
        (["--usb", "hci0,hci1,hci2"], None, [], ["hci0", "hci1"], ["", ""]),
        (["--pcie", "hci0,hci1,hci2"], None, [], ["hci2"], [""]),
        # Without bus options, both kinds are collected.
        ([], "hci0,hci1,hci2", [], ["hci0", "hci1", "hci2"], ["", "", ""]),
        # Force options restrict to one kind even with an unset bus option.
        (["--force-usb"], "hci0,hci2", [], ["hci0"], [""]),
        (["--force-pcie"], "hci0,hci2", [], ["hci2"], [""]),
        # An unusable controller is dropped and reported.
        (["--usb", "hci0"], None, ["hci0"], [], ["hci0 cannot be used"]),
        # Usable controllers come first even when the unusable one is named
        # first, so the skip reason shows one message per missing controller.
        (["--usb", "hci1,hci0"], None, ["hci1"], ["hci0"], ["", "hci1 cannot be used"]),
    ],
)
def test_hw_indices(
    pytester, monkeypatch, fake_controllers, options, controllers, indices, messages
):
    monkeypatch.delenv("FUNCTIONAL_TESTING_CONTROLLERS", raising=False)
    if controllers is not None:
        monkeypatch.setenv("FUNCTIONAL_TESTING_CONTROLLERS", controllers)

    pytester.makepyfile(HW_TEST.format(indices=indices, messages=messages))
    result = pytester.runpytest("-p", "pytest_bluezenv", "--kernel-build=no", *options)
    result.assert_outcomes(passed=1)
