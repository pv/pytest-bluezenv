# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Public host-configuration decorators: host_config / parametrized_host_config.

The decorators resolve through the ``host_setup`` and ``vm_setup`` fixtures;
the tests below assert the fixture values a user gets.  Plugin ``presetup``
calls look up executables, so ``find_exe`` is stubbed to always succeed.
"""

import pytest

from pytest_bluezenv import (
    Agent,
    Bluetoothctl,
    Bluetoothd,
    Call,
    Obexd,
    parametrized_host_config,
)
from pytest_bluezenv import utils

PLUGIN = ["-p", "pytest_bluezenv"]

PLUGINS = [Agent, Bluetoothctl, Bluetoothd, Obexd]

# Expansion pulls in default plugins (rcvbuf, call, bdaddr) and resolves
# `depends` to a linear load order.
EXPAND = {
    "bluetoothd": ["rcvbuf", "call", "bdaddr", "dbus-system", "bluetoothd"],
    "bluetoothctl": [
        "rcvbuf",
        "call",
        "bdaddr",
        "dbus-system",
        "bluetoothd",
        "bluetoothctl",
    ],
    "obexd": [
        "rcvbuf",
        "call",
        "bdaddr",
        "dbus-system",
        "bluetoothd",
        "dbus-session",
        "obexd",
    ],
    "agent": [
        "rcvbuf",
        "call",
        "bdaddr",
        "dbus-system",
        "bluetoothd",
        "agent",
    ],
}


@pytest.mark.parametrize("plugin_cls", PLUGINS)
def test_dependency_expansion(pytester, monkeypatch, plugin_cls):
    plugin = plugin_cls.__name__
    monkeypatch.setattr(utils, "find_exe", lambda subdir, name: "/fake/" + name)
    pytester.makepyfile(f"""
        from pytest_bluezenv import host_config, {plugin}

        @host_config([{plugin}()])
        def test_expansion(host_setup, vm_setup):
            names = [type(p).name for p in host_setup["setup"][0]]
            assert names == {EXPAND[plugin.lower()]!r}
    """)
    pytester.runpytest(*PLUGIN).assert_outcomes(passed=1)


def test_host_config_vm_setup_flags(pytester):
    pytester.makepyfile("""
        from pytest_bluezenv import host_config

        @host_config([], [], hw=True, mem="512M", controller=False)
        def test_vm(vm_setup, host_setup):
            assert vm_setup == {
                "num_hosts": 2,
                "hw": True,
                "mem": "512M",
                "controller": False,
            }
    """)
    pytester.runpytest(*PLUGIN).assert_outcomes(passed=1)


def test_host_config_generates_setup_ids(pytester):
    pytester.makepyfile("""
        from pytest_bluezenv import host_config

        @host_config([], [], hw=True, mem="512M", controller=False)
        def test_vm(host_setup, vm_setup):
            pass
    """)
    result = pytester.runpytest(*PLUGIN, "--collect-only", "-q")
    result.stdout.fnmatch_lines(["*vm2-512M-hw-noc*"])


def test_controller_false_drops_bdaddr(pytester):
    pytester.makepyfile("""
        from pytest_bluezenv import host_config

        @host_config([], controller=False)
        def test_setup(host_setup, vm_setup):
            names = [type(p).name for p in host_setup["setup"][0]]
            assert names == ["rcvbuf", "call"]
    """)
    pytester.runpytest(*PLUGIN).assert_outcomes(passed=1)


def test_reuse_flag_propagates(pytester):
    pytester.makepyfile("""
        from pytest_bluezenv import host_config, Call

        @host_config([Call()], reuse=True)
        def test_reuse(host_setup, vm_setup):
            assert host_setup["reuse"] is True
    """)
    pytester.runpytest(*PLUGIN).assert_outcomes(passed=1)


def test_parametrized_multiple_scenarios_custom_ids(pytester):
    pytester.makepyfile("""
        from pytest_bluezenv import parametrized_host_config, Call

        @parametrized_host_config(
            [([Call()], [Call()]), ([], [])],
            ids=["two", "empty"],
        )
        def test_parametrized(host_setup, vm_setup):
            pass
    """)
    result = pytester.runpytest(*PLUGIN, "--collect-only", "-q")
    result.stdout.fnmatch_lines(["2 tests collected*"])
    result.stdout.fnmatch_lines(["*two*"])
    result.stdout.fnmatch_lines(["*empty*"])


def test_parametrized_requires_same_host_count():
    with pytest.raises(ValueError, match="same host count"):
        parametrized_host_config([([Call()],), ([Call()], [Call()])])


def test_parametrized_requires_matching_ids():
    with pytest.raises(ValueError, match="Wrong number of ids"):
        parametrized_host_config([([Call()],)], ids=["a", "b"])


@pytest.mark.parametrize(
    "fixture, reason",
    [
        ("host_setup", "host setup not specified"),
        ("vm_setup", "env setup not specified"),
    ],
)
def test_setup_fixture_requires_parametrization(pytester, fixture, reason):
    pytester.makepyfile(f"""
        def test_needs_setup({fixture}):
            pass
    """)
    result = pytester.runpytest(*PLUGIN)
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines([f"*{reason}*"])
