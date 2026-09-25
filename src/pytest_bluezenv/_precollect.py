# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""Collection-only plugin for estimating xdist workers' VM memory."""

import json
import os
from pathlib import Path

import pytest

from .plugin import DEFAULT_VM_MEM, QEMU_OVERHEAD, _parse_mem


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_collection_modifyitems(config, items):
    yield

    default_mem = config.option.vm_mem or config.getini("vm_mem")
    shared = private = 0

    for item in items:
        callspec = getattr(item, "callspec", None)
        setup = callspec.params.get("vm_setup") if callspec is not None else None
        if setup is None:
            continue

        value = setup["mem"] or default_mem
        try:
            guest_mem = _parse_mem(value) if value else DEFAULT_VM_MEM
        except ValueError as exc:
            raise pytest.UsageError(f"Invalid VM memory {value!r}") from exc

        footprint = setup["num_hosts"] * (guest_mem + QEMU_OVERHEAD)
        if "vm" in item.fixturenames:
            shared = max(shared, footprint)
        if "vm_once" in item.fixturenames:
            private = max(private, footprint)

    Path(os.environ["PYTEST_BLUEZENV_PRECOLLECT"]).write_text(
        json.dumps([shared, private])
    )
