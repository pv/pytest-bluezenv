# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Pexpect host plugin matching behaviour.

The VM-side methods are exercised against a fake pexpect control object
that replays a scripted stream. No VM and no real process are needed.
"""

import re

import pytest

from pytest_bluezenv.host_plugins import Pexpect


class FakeMatch:
    def __init__(self, m):
        self._m = m

    def group(self, n):
        return self._m.group(n)

    def groups(self):
        return self._m.groups()


class FakeCtl:
    """Replays fixed chunks and matches patterns against the accumulated text."""

    def __init__(self, stream):
        self.stream = stream
        self.timeout = 20
        self.match = None
        self.expects = []
        self.eof = False
        self.killed = None

    def expect(self, pattern, timeout=-1, **kw):
        if not isinstance(pattern, (list, tuple)):
            pattern = [pattern]
        self.expects.append((list(pattern), timeout))
        for idx, pat in enumerate(pattern):
            m = re.search(pat, self.stream)
            if m:
                self.match = FakeMatch(m)
                return idx
        raise TimeoutError("no match")

    def sendeof(self):
        self.eof = True

    def kill(self, sig):
        self.killed = sig


def make_plugin(stream):
    plugin = Pexpect()
    plugin.log = __import__("logging").getLogger("test.pexpect")
    ctl = FakeCtl(stream)
    plugin.ctls = {1: ctl}
    return plugin, ctl


def test_expect_accepts_pattern_keyword_with_reject():
    plugin, _ = make_plugin("hello world")

    idx, groups = plugin.expect(1, pattern="(hello)", reject=[r"(nope)"])

    assert idx == 0
    assert groups[0] == "hello"


def test_expect_accepts_pattern_positional_with_reject():
    plugin, _ = make_plugin("hello world")

    idx, groups = plugin.expect(1, "(hello)", reject=[r"(nope)"])

    assert idx == 0
    assert groups[0] == "hello"


def test_expect_missing_pattern_is_a_type_error():
    plugin, _ = make_plugin("hello")

    with pytest.raises(TypeError):
        plugin.expect(1, reject=[r"(nope)"])


def test_expect_reject_aborts_with_matched_output():
    plugin, _ = make_plugin("bad news arrived")

    with pytest.raises(AssertionError, match="bad news"):
        plugin.expect(1, "never", reject=[r"(bad news)"])


def test_expect_index_is_relative_to_patterns_with_reject():
    plugin, _ = make_plugin("only second here")

    idx, _ = plugin.expect(1, [r"(first)", r"(second)"], reject=[r"(nope)"])

    assert idx == 1


def test_expect_all_returns_groups_in_pattern_order():
    plugin, _ = make_plugin("two 2 one 1")

    groups = plugin.expect_all(1, [r"one (\d)", r"two (\d)"])

    assert [g[0] for g in groups] == ["1", "2"]


def test_expect_all_reject_watched_every_round():
    plugin, _ = make_plugin("one 1 bad news")

    with pytest.raises(AssertionError, match="bad news"):
        plugin.expect_all(1, [r"one (\d)", r"(never)"], reject=[r"(bad news)"])


def test_expect_all_deadline_is_shared_across_rounds(monkeypatch):
    plugin, ctl = make_plugin("one 1")
    import pytest_bluezenv.host_plugins as hp

    clock = {"now": 0.0}

    def monotonic():
        return clock["now"]

    monkeypatch.setattr(hp.time, "monotonic", monotonic)

    seen = []
    rounds = iter([0.15, None])

    def expect(pattern, timeout=-1, **kw):
        seen.append(timeout)
        delay = next(rounds, None)
        if delay is not None:
            # The first pattern arrives after 0.15 s.
            clock["now"] += delay
            return FakeCtl.expect(ctl, pattern, timeout=timeout, **kw)
        # The second pattern never arrives: block until the round times
        # out, then report it.
        clock["now"] += timeout
        raise TimeoutError("no match")

    ctl.expect = expect

    # Pattern two never arrives. A shared deadline bounds the whole wait
    # by one timeout, while a per-round timeout would allow two.
    with pytest.raises(TimeoutError):
        plugin.expect_all(1, [r"one (\d)", r"(never)"], timeout=0.2)

    assert clock["now"] == pytest.approx(0.2)
    assert len(seen) == 2
    # The second round only gets what is left of the budget.
    assert seen[1] == pytest.approx(0.05)


def test_expect_all_matches_reject_via_helper():
    plugin, ctl = make_plugin("x")

    ctl.expect = lambda pattern, timeout=-1, **kw: 0
    ctl.match = FakeMatch(re.match(r"(x)", "x"))

    with pytest.raises(AssertionError):
        plugin.expect_all(1, ["(a)"], reject=[r"(x)"])


def test_pexpect_close_kills_and_forgets_process():
    import signal

    plugin, ctl = make_plugin("x")

    plugin.close(1)

    assert ctl.eof is True
    assert ctl.killed == signal.SIGTERM
    assert 1 not in plugin.ctls


def test_bluetoothctl_teardown_closes_the_one_process():
    import signal

    from pytest_bluezenv.host_plugins import Bluetoothctl

    plugin = Bluetoothctl(args=("-a", "auto"))
    pexpect_plugin, ctl = make_plugin("x")
    ctl_id = 1
    plugin._pexpect = pexpect_plugin
    plugin._ctl_id = ctl_id

    plugin.teardown()

    assert ctl.eof is True
    assert ctl.killed == signal.SIGTERM
    assert ctl_id not in pexpect_plugin.ctls
