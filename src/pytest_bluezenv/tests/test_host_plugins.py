# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Host plugin contract and parent-side configuration.

Plugins are declared at collection time; ``__init__`` and ``presetup`` run on
the parent side, so they are exercised here without a VM.
"""

import pytest

from pytest_bluezenv import (
    Agent,
    Bdaddr,
    Bluetoothctl,
    Bluetoothd,
    Btmon,
    Call,
    DbusSession,
    DbusSystem,
    Obexd,
    Pexpect,
    Rcvbuf,
)
from pytest_bluezenv import utils

# name and declared dependencies per documented plugin.
CONTRACT = {
    Agent: ("agent", {"bluetoothd"}),
    Bdaddr: ("bdaddr", set()),
    Bluetoothctl: ("bluetoothctl", {"bluetoothd"}),
    Bluetoothd: ("bluetoothd", {"dbus-system"}),
    Btmon: ("btmon", set()),
    Call: ("call", set()),
    DbusSession: ("dbus-session", set()),
    DbusSystem: ("dbus-system", set()),
    Obexd: ("obexd", {"bluetoothd", "dbus-session"}),
    Pexpect: ("pexpect", set()),
    Rcvbuf: ("rcvbuf", set()),
}


@pytest.mark.parametrize("cls", list(CONTRACT))
def test_plugin_contract(cls):
    name, depends = CONTRACT[cls]
    assert cls.name == name
    assert {type(d).name for d in cls.depends} == depends


def test_bluetoothd_arg_handling():
    assert Bluetoothd().args == ("-d",)
    assert Bluetoothd(debug=False).args == ()
    # explicit -d is not duplicated
    assert Bluetoothd(args=("-d", "-P", "avrcp")).args == ("-d", "-P", "avrcp")
    assert Bluetoothd(debug=False, args=("-d",)).args == ("-d",)
    assert Bluetoothd(conf="[General]").conf == "[General]"


@pytest.mark.parametrize(
    "plugin_cls, exe",
    [
        (DbusSystem, "dbus-daemon"),
        (Bluetoothd, "bluetoothd"),
        (Bluetoothctl, "bluetoothctl"),
        (Obexd, "obexd"),
    ],
)
def test_presetup_skips_when_executable_missing(pytester, monkeypatch, plugin_cls, exe):
    # find_exe probes the host filesystem: stub it to fail only for `exe`.
    def fake_find_exe(subdir, name):
        if name == exe:
            raise FileNotFoundError(name)
        return "/fake/" + name

    monkeypatch.setattr(utils, "find_exe", fake_find_exe)
    pytester.makepyfile(f"""
        from pytest_bluezenv import host_config, {plugin_cls.__name__}

        @host_config([{plugin_cls.__name__}()])
        def test_skip(host_setup, vm_setup):
            pass
    """)
    pytester.runpytest("-p", "pytest_bluezenv").assert_outcomes(skipped=1)


def test_presetup_called_with_config(pytester):
    pytester.makepyfile("""
        from pytest_bluezenv import HostPlugin, host_config

        calls = []

        class Watcher(HostPlugin):
            name = "watcher"

            def presetup(self, config):
                calls.append(config)

        @host_config([Watcher()])
        def test_presetup(host_setup, vm_setup):
            assert len(calls) == 1
            assert calls[0].getini("vm_timeout") == "30"
    """)
    pytester.runpytest("-p", "pytest_bluezenv").assert_outcomes(passed=1)


def test_rcvbuf_default_from_ini(pytester):
    pytester.makeini("[pytest]\nhost_plugins.rcvbuf.default = 2048\n")
    pytester.makepyfile("""
        from pytest_bluezenv import Rcvbuf

        def test_rcvbuf(request):
            plugin = Rcvbuf()
            plugin.presetup(request.config)
            assert plugin.rcvbuf == 2048
    """)
    pytester.runpytest("-p", "pytest_bluezenv").assert_outcomes(passed=1)


def test_rcvbuf_explicit_value_kept(pytester):
    pytester.makeini("[pytest]\nhost_plugins.rcvbuf.default = 2048\n")
    pytester.makepyfile("""
        from pytest_bluezenv import Rcvbuf

        def test_rcvbuf(request):
            plugin = Rcvbuf(4096)
            plugin.presetup(request.config)
            assert plugin.rcvbuf == 4096
    """)
    pytester.runpytest("-p", "pytest_bluezenv").assert_outcomes(passed=1)
