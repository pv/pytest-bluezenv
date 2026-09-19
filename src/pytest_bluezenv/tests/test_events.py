# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Async-event plumbing shared by host plugins: Event and EventPluginMixin.
"""

import inspect
import pickle

import pytest

from pytest_bluezenv import Event, EventPluginMixin, dbus_service_event_method


class Mixin(EventPluginMixin):
    pass


@pytest.fixture
def mixin():
    m = Mixin()
    m.setup(impl=None)
    return m


def test_event_exposes_info_as_attributes():
    event = Event("org.bluez.Agent1.RequestConfirmation", passkey=1234)
    assert event.kind == "org.bluez.Agent1.RequestConfirmation"
    assert event.passkey == 1234
    with pytest.raises(AttributeError):
        event.missing


def test_event_is_picklable_without_callbacks():
    # Events cross the RPC boundary, so callback attributes are dropped.
    event = Event("k", data=1, reply_cb=lambda: None, error_cb=lambda e: None)
    reloaded = pickle.loads(pickle.dumps(event))
    assert reloaded.kind == "k"
    assert reloaded.data == 1
    assert reloaded.reply_cb is None
    assert reloaded.error_cb is None


def test_get_event_nonblocking_empty(mixin):
    assert mixin.get_event(block=False) is None


def test_expect_matches_kind(mixin):
    mixin.events.put(Event("a"))
    assert mixin.expect("a").kind == "a"


def test_expect_rejects_wrong_kind(mixin):
    mixin.events.put(Event("b"))
    with pytest.raises(AssertionError, match="Got event.kind="):
        mixin.expect("a")


def test_reply_invokes_reply_cb(mixin):
    replies = []
    mixin.events.put(Event("k", reply_cb=lambda *v: replies.append(v)))
    mixin.expect("k")
    mixin.reply("x", "y")
    assert replies == [("x", "y")]
    assert mixin.cur_event is None


def test_reply_error_invokes_error_cb(mixin):
    errors = {}
    mixin.events.put(
        Event(
            "k", reply_cb=lambda *v: None, error_cb=lambda e: errors.__setitem__("e", e)
        )
    )
    mixin.expect("k")
    mixin.reply_error()
    # Default error is org.bluez.Error.Rejected.
    assert type(errors["e"]).__name__ == "Rejected"


def test_reply_applies_reply_type(mixin):
    replies = []
    mixin.events.put(
        Event(
            "k",
            reply_cb=lambda *v: replies.append(v),
            reply_type=lambda a, b: (a, b * 10),
        )
    )
    mixin.expect("k")
    mixin.reply(1, 2)
    assert replies == [(1, 20)]


def test_dbus_service_event_method_builds_dbus_method():
    # The factory generates a D-Bus service method; inbound dispatch itself is
    # exercised by the VM agent test.  Asynchronous methods additionally take
    # reply and error callbacks; synchronous ones take only the declared args.
    method = dbus_service_event_method(
        "org.bluez.Agent1", "RequestPasskey", ("device",), "o", "u", sync=False
    )
    assert method.__name__ == "RequestPasskey"
    # self + 1 declared arg + 2 async callbacks.
    assert len(inspect.signature(method).parameters) == 4

    release = dbus_service_event_method("org.bluez.Agent1", "Release")
    # self only; no declared args, synchronous so no callbacks.
    assert len(inspect.signature(release).parameters) == 1
