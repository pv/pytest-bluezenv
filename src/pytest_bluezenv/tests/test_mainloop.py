# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
GLib main-loop helpers.

The main loop is only fully available for VM host plugins, but the invoke /
wrap / assert helpers are exercisable from the tester process.
"""

import pytest
from gi.repository import GLib

from pytest_bluezenv import utils


def test_mainloop_invoke_returns_value():
    assert utils.mainloop_invoke(lambda x: x * 2, 21) == 42


def test_mainloop_invoke_propagates_exception():
    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        utils.mainloop_invoke(boom)


def test_mainloop_wrap_runs_function():
    @utils.mainloop_wrap
    def add(a, b):
        return a + b

    assert add(2, 3) == 5


@pytest.mark.skipif(
    GLib.MainContext.default().is_owner(),
    reason="main thread owns the GLib main context here",
)
def test_mainloop_assert_requires_mainloop():
    @utils.mainloop_assert
    def func():
        return 5

    with pytest.raises(AssertionError, match="not called from GLib mainloop"):
        func()


def test_get_dbus_is_mainloop_guarded():
    # get_dbus is decorated with mainloop_assert, so it must not reach D-Bus
    # outside the main loop.
    if GLib.MainContext.default().is_owner():
        pytest.skip("main thread owns the GLib main context here")
    with pytest.raises(AssertionError):
        utils.get_dbus()
