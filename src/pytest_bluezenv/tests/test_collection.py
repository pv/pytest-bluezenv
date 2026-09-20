# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Collection ordering and xdist grouping of VM-using tests.

Tests sharing a setup run back-to-back so that VM and host instances are
reused.  With pytest-xdist active, reused host setups also get an
``xdist_group`` marker; without it they do not.  A stub plugin named
``xdist`` stands in for pytest-xdist, which need not be installed.
"""

from pytest_bluezenv import host_plugins

PLUGIN = ["-p", "pytest_bluezenv"]

XDIST_CONFTEST = """
    def pytest_configure(config):
        if not config.pluginmanager.has_plugin("xdist"):
            config.pluginmanager.register(object(), "xdist")
        config.addinivalue_line("markers", "xdist_group(name): xdist group")
"""

ORDER_SOURCE = """
    from pytest_bluezenv import host_config, Call

    @host_config([Call()], reuse=True)
    def test_one_host_first(host_setup, vm_setup):
        pass

    @host_config([Call()], [Call()], reuse=True)
    def test_two_hosts(host_setup, vm_setup):
        pass

    @host_config([Call()], reuse=True)
    def test_one_host_second(host_setup, vm_setup):
        pass

    def test_plain():
        pass
"""

REUSE_SOURCE = """
    from pytest_bluezenv import host_config, Call

    @host_config([Call()], reuse=True)
    def test_reuse(request, host_setup, vm_setup):
        marker = request.node.get_closest_marker("xdist_group")
        assert marker is not None
        assert marker.args == ("reuse-%s" % host_setup["name"],)
"""


def test_vm_tests_are_grouped_by_setup(pytester, monkeypatch):
    # The setup names are generated from a module-level counter shared
    # with other in-process runs, and tests are sorted by that name.
    # Reset it so the ids are small and in source order.
    monkeypatch.setattr(host_plugins, "HOST_SETUPS", 0)
    pytester.makepyfile(ORDER_SOURCE)
    result = pytester.runpytest(*PLUGIN, "-v")
    result.assert_outcomes(passed=4)

    executed = [
        line.split("::")[1].split()[0].split("[")[0]
        for line in result.outlines
        if "::" in line and "PASSED" in line
    ]

    # Non-VM tests first; tests with the same VM setup run adjacently.
    assert executed == [
        "test_plain",
        "test_one_host_first",
        "test_one_host_second",
        "test_two_hosts",
    ]


def test_xdist_group_added_for_reuse_setups(pytester):
    pytester.makeconftest(XDIST_CONFTEST)
    pytester.makepyfile(REUSE_SOURCE)
    pytester.runpytest(*PLUGIN).assert_outcomes(passed=1)


def test_xdist_group_not_overridden(pytester):
    pytester.makeconftest(XDIST_CONFTEST)
    pytester.makepyfile("""
        import pytest

        from pytest_bluezenv import host_config, Call

        @pytest.mark.xdist_group("custom")
        @host_config([Call()], reuse=True)
        def test_reuse(request, host_setup, vm_setup):
            marker = request.node.get_closest_marker("xdist_group")
            assert marker.args == ("custom",)
    """)
    pytester.runpytest(*PLUGIN).assert_outcomes(passed=1)


def test_no_xdist_group_without_xdist_plugin(pytester):
    pytester.makepyfile("""
        from pytest_bluezenv import host_config, Call

        @host_config([Call()], reuse=True)
        def test_reuse(request, host_setup, vm_setup):
            assert request.node.get_closest_marker("xdist_group") is None
    """)
    pytester.runpytest(*PLUGIN, "-p", "no:xdist").assert_outcomes(passed=1)
