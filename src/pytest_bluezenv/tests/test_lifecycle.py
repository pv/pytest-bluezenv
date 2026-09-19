# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
VM-side plugin manager.

``Implementation`` runs in the lower tester and is otherwise only reachable
through a booted VM, so it is exercised directly here.  Assertions are on
what the RPC client observes: loaded plugin values, call results, and load
errors.
"""

import pytest

from pytest_bluezenv import env


class FakePlugin:
    name = "fake"

    def __init__(self, value=None):
        self.value = value
        self.setup_calls = 0

    def setup(self, impl):
        self.setup_calls += 1


def test_load_exposes_value_and_calls_plugin():
    impl = env.Implementation()
    plugin = FakePlugin(value=123)

    impl.start_load(plugin)
    assert plugin.setup_calls == 1
    assert impl.wait_load() == {"fake": 123}

    assert impl.call_plugin("fake", "setup", None) is None
    assert plugin.setup_calls == 2


def test_failed_plugin_load_surfaces_on_wait():
    class Bad(FakePlugin):
        def setup(self, impl):
            raise RuntimeError("boom")

    impl = env.Implementation()
    with pytest.raises(RuntimeError, match="boom"):
        impl.start_load(Bad())

    with pytest.raises(RuntimeError, match="load failed"):
        impl.wait_load()
