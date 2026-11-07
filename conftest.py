# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Test harness for pytest-bluezenv's own tests.

Functional tests drive the plugin through the `pytester` fixture, running an
inner pytest that loads the plugin with `-p pytest_bluezenv` in an isolated
directory.  VM tests additionally boot real QEMU hosts; they only run when
`--kernel` and a built BlueZ tree are given on the outer command line, and
forward those options inward.
"""

import sys
import shutil
import importlib.resources
import subprocess
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]


def pytest_addoption(parser):
    def abs_path(value):
        return Path(value).absolute()

    group = parser.getgroup("bluezenv-selftest")
    group.addoption(
        "--kernel",
        default=None,
        help="Kernel image or build tree for VM tests",
        type=abs_path,
    )
    group.addoption(
        "--bluez-build-dir",
        default=None,
        help="BlueZ build directory for VM tests",
        type=abs_path,
    )


@pytest.fixture
def vm_args(request, monkeypatch):
    """
    CLI arguments to forward into a pytester run that boots VM hosts.

    Skips unless a kernel and the VM-host binaries are available, so
    VM tests are strict (assert passed) when they do run.
    """
    from pytest_bluezenv import utils

    config = request.config

    kernel = config.getoption("kernel")
    if not kernel:
        pytest.skip("no --kernel given")
    if not kernel.exists():
        pytest.skip("no kernel image")

    monkeypatch.setattr(utils, "BUILD_DIR", config.getoption("bluez_build_dir"))
    monkeypatch.setattr(utils, "pkg_bin_dir", pkg_bin_dir)

    for subdir, exe in (
        ("client", "bluetoothctl"),
        ("emulator", "btvirt"),
        ("src", "bluetoothd"),
        ("tools", "btmgmt"),
        ("tools", "test-runner"),
    ):
        try:
            utils.find_exe(subdir, exe)
        except FileNotFoundError:
            pytest.skip(f"{subdir}/{exe} not found")

    args = ["--kernel", str(kernel), "-vvv", "-ra"]
    if utils.BUILD_DIR:
        args += ["--bluez-build-dir", str(utils.BUILD_DIR)]

    return args


def pytest_collection_modifyitems(items):
    """
    Mark VM-using tests: they request the vm_args fixture. Run them
    with -m vm, e.g. to select the tests a kernel image is needed for.
    """
    for item in items:
        if "vm_args" in item.fixturenames:
            item.add_marker(pytest.mark.vm)


def pkg_bin_dir():
    return (
        Path(__file__).parent
        / "build"
        / f"cp{sys.version_info.major}{sys.version_info.minor}"
    )


@pytest.fixture(autouse=True)
def restore_plugin_state():
    """
    Keep plugin globals from leaking between tests: an in-process
    pytester session runs the plugin's pytest_configure, overwriting
    utils.DEFAULT_TIMEOUT, Environment.DEFAULT_MEM and the BlueZ tree
    locations for the outer session.
    """
    from pytest_bluezenv import env, utils

    original = (
        utils.DEFAULT_TIMEOUT,
        env.Environment.DEFAULT_MEM,
        utils.BUILD_DIR,
        utils.SRC_DIR,
    )
    yield
    (
        utils.DEFAULT_TIMEOUT,
        env.Environment.DEFAULT_MEM,
        utils.BUILD_DIR,
        utils.SRC_DIR,
    ) = original
