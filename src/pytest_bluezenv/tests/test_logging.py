# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Log filtering, timestamp reordering and oops detection.
"""

import logging

import pytest

from pytest_bluezenv import CoredumpWarning, utils


def record(name, msg="m", level=utils.OUT, nsec=None):
    rec = logging.LogRecord(name, level, __file__, 0, msg, None, None)
    rec.name = name
    if nsec is not None:
        rec.nsec = nsec
    return rec


@pytest.mark.parametrize(
    "allow, deny, expected",
    [
        # a plain logger name matches itself and its descendants
        (
            ("host",),
            (),
            {
                "host": True,
                "host.0": True,
                "host.0.1": True,
                "rpc": False,
                "hostx": False,
            },
        ),
        # a glob matches its own set, e.g. descendants but not the bare name
        (("host.*",), (), {"host": False, "host.0": True, "host.0.1": True}),
        # deny wins over allow
        (("host.*",), ("host.0",), {"host.0": False, "host.1": True}),
        # deny alone filters a name and its descendants
        (
            (),
            ("host",),
            {"host": False, "host.0": False, "host.0.1": False, "rpc": True},
        ),
    ],
)
def test_log_name_filter(allow, deny, expected):
    f = utils.LogNameFilter(allow, deny)
    for name, want in expected.items():
        assert bool(f.filter(record(name))) is want, name


def test_log_reorder_filter():
    class Collect(logging.Handler):
        def __init__(self):
            super().__init__()
            self.messages = []

        def emit(self, rec):
            self.messages.append(rec.msg)

    handler = Collect()
    utils.LogReorderFilter.enable([handler])
    try:
        # Arrive out of order; the filter buffers until flushed.
        handler.handle(record("x", msg="B", nsec=2_000_000_000))
        handler.handle(record("x", msg="A", nsec=1_000_000_000))
        utils.LogReorderFilter.flush_all()
    finally:
        utils.LogReorderFilter.disable([handler])

    assert handler.messages == ["A", "B"]


def test_oops_log_handler_kernel():
    warnings = []
    handler = utils.OopsLogHandler(warnings)
    for msg in ["WARNING: something bad", " CPU: 0 UID: 0"]:
        handler.emit(record("host.0.0", msg=msg))

    assert len(warnings) == 1
    cls, text = warnings[0]
    assert cls is utils.KernelBugWarning
    assert text.startswith("[host.0.0] WARNING: something bad")
    assert "CPU: 0 UID: 0" in text


def test_oops_log_handler_sanitizer():
    warnings = []
    handler = utils.OopsLogHandler(warnings)
    handler.emit(record("someapp", msg="==123==ERROR: AddressSanitizer: boom address"))
    assert [cls for cls, _ in warnings] == [utils.SanitizerWarning]


def test_oops_log_handler_ignores_low_levels():
    warnings = []
    handler = utils.OopsLogHandler(warnings)
    handler.emit(record("host.0.0", msg="WARNING: x", level=logging.INFO))
    assert warnings == []


def test_warning_types_are_user_warnings():
    for cls in (CoredumpWarning, utils.KernelBugWarning, utils.SanitizerWarning):
        assert issubclass(cls, UserWarning)
