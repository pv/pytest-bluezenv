# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""Automatic worker counts use the selected VM configurations."""

import os
from pathlib import Path

import pytest

from pytest_bluezenv import plugin

PLUGIN = ["-p", "pytest_bluezenv"]
MiB = 1024**2
GiB = 1024**3


def setup_probes(monkeypatch, mem):
    monkeypatch.setattr(os, "sched_getaffinity", lambda *a: list(range(64)))
    monkeypatch.setattr(plugin, "_mem_available", lambda: mem)


def test_auto_workers_use_selected_host_count(pytester, monkeypatch):
    pytester.makepyfile("""
        from pytest_bluezenv import host_config

        @host_config([], [], [])
        def test_three(hosts): pass

        @host_config([])
        def test_one(hosts): pass
    """)
    setup_probes(monkeypatch, 12 * GiB)

    config = pytester.parseconfig(*PLUGIN, "-k", "one")

    assert plugin.pytest_xdist_auto_num_workers(config) == 30


def test_auto_workers_respect_mark_selection(pytester, monkeypatch):
    pytester.makepyfile("""
        import pytest
        from pytest_bluezenv import host_config

        @pytest.mark.slow
        @host_config([], [], [])
        def test_three(hosts): pass

        @host_config([])
        def test_one(hosts): pass
    """)
    setup_probes(monkeypatch, 12 * GiB)

    config = pytester.parseconfig(*PLUGIN, "-m", "not slow")

    assert plugin.pytest_xdist_auto_num_workers(config) == 30


def test_auto_workers_use_per_test_memory_and_default_precedence(pytester, monkeypatch):
    pytester.makeini("[pytest]\nvm_mem = 1G\n")
    pytester.makepyfile("""
        from pytest_bluezenv import host_config

        @host_config([])
        def test_default(hosts): pass

        @host_config([], mem="2G")
        def test_large(hosts): pass
    """)
    setup_probes(monkeypatch, 12 * GiB)

    config = pytester.parseconfig(*PLUGIN, "--vm-mem", "512M")

    assert plugin.pytest_xdist_auto_num_workers(config) == 5


def test_auto_workers_allow_overlapping_vm_and_vm_once(pytester, monkeypatch):
    pytester.makepyfile("""
        from pytest_bluezenv import host_config

        @host_config([], [])
        def test_shared(hosts): pass

        @host_config([], [])
        def test_private(hosts_once): pass
    """)
    setup_probes(monkeypatch, 4 * GiB)

    config = pytester.parseconfig(*PLUGIN)

    assert plugin.pytest_xdist_auto_num_workers(config) == 2


def test_auto_workers_count_both_fixtures_in_one_test(pytester, monkeypatch):
    pytester.makepyfile("""
        from pytest_bluezenv import host_config

        @host_config([], [])
        def test_both(hosts, hosts_once): pass
    """)
    setup_probes(monkeypatch, 4 * GiB)

    config = pytester.parseconfig(*PLUGIN)

    assert plugin.pytest_xdist_auto_num_workers(config) == 2


def test_auto_workers_plain_number_is_mib(pytester, monkeypatch):
    pytester.makepyfile("""
        from pytest_bluezenv import host_config

        @host_config([])
        def test_vm(hosts): pass
    """)
    setup_probes(monkeypatch, 1000 * MiB)

    config = pytester.parseconfig(*PLUGIN, "--vm-mem", "512")

    assert plugin.pytest_xdist_auto_num_workers(config) == 1


def test_auto_workers_without_vm_tests_use_cpus(pytester, monkeypatch):
    pytester.makepyfile("def test_plain(): pass")
    setup_probes(monkeypatch, MiB)

    config = pytester.parseconfig(*PLUGIN)

    assert plugin.pytest_xdist_auto_num_workers(config) == 64


def test_auto_workers_report_precollection_errors(pytester, monkeypatch):
    pytester.makepyfile("raise RuntimeError('broken collection')")
    setup_probes(monkeypatch, 4 * GiB)
    config = pytester.parseconfig(*PLUGIN)

    with pytest.raises(pytest.UsageError, match="broken collection"):
        plugin.pytest_xdist_auto_num_workers(config)


def test_auto_workers_at_least_one(pytester, monkeypatch):
    pytester.makepyfile("""
        from pytest_bluezenv import host_config

        @host_config([])
        def test_vm(hosts): pass
    """)
    setup_probes(monkeypatch, MiB)

    config = pytester.parseconfig(*PLUGIN)

    assert plugin.pytest_xdist_auto_num_workers(config) == 1


def test_auto_workers_fallback_when_memory_unknown(pytester, monkeypatch):
    config = pytester.parseconfig(*PLUGIN)
    setup_probes(monkeypatch, None)

    assert plugin.pytest_xdist_auto_num_workers(config) == 64


def test_auto_workers_run_with_xdist(pytester, monkeypatch):
    pytest.importorskip("xdist")
    root = str(Path(plugin.__file__).resolve().parent.parent)
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join([root, os.environ.get("PYTHONPATH", "")])
    )
    pytester.makepyfile("""
        from pytest_bluezenv import host_config

        @host_config([])
        def test_vm_without_kernel(hosts): pass
    """)

    result = pytester.runpytest_subprocess(
        *PLUGIN, "-n", "auto", "--maxprocesses=2", "--kernel-build=no"
    )

    result.assert_outcomes(skipped=1)


def test_hook_registered_without_xdist(pytester):
    pytester.makepyfile("def test_ok(): pass")
    pytester.runpytest(*PLUGIN, "-p", "no:xdist").assert_outcomes(passed=1)
