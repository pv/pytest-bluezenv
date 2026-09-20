# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
from pytest_bluezenv.le import LeAdvertiser, _LeAdvertisement


def test_le_advertisement_properties():
    props = _LeAdvertisement.properties("peripheral", ["1234"], True)
    assert props["Type"] == "peripheral"
    assert list(props["ServiceUUIDs"]) == ["1234"]
    assert bool(props["Discoverable"]) is True

    props = _LeAdvertisement.properties("peripheral", (), False)
    assert "Discoverable" not in props


def test_le_advertiser_registration_timeout_names_advertisement(monkeypatch):
    plugin = LeAdvertiser(index=3, timeout=0.01)

    class FakeAdv:
        adv_path = "/org/bluez/test/advertisement3"

    def fake_register():
        plugin.adv = FakeAdv()
        # The registration never completes: no reply handler runs.

    monkeypatch.setattr(plugin, "_register", fake_register)

    try:
        plugin.setup(None)
    except TimeoutError as exc:
        assert "advertisement3" in str(exc)
    else:
        raise AssertionError("expected TimeoutError")


def test_le_advertiser_setup_reraises_registration_error(monkeypatch):
    plugin = LeAdvertiser(timeout=0.01)

    class FakeAdv:
        adv_path = "/org/bluez/test/advertisement0"

    def fake_register():
        plugin.adv = FakeAdv()
        plugin.register_error = ValueError("rejected")
        plugin.registered = True

    monkeypatch.setattr(plugin, "_register", fake_register)

    try:
        plugin.setup(None)
    except ValueError as exc:
        assert "rejected" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_le_advertiser_teardown_without_registration_is_safe():
    plugin = LeAdvertiser()
    plugin.log = __import__("logging").getLogger("test.le")

    # No advertisement was ever registered.
    LeAdvertiser.teardown.__wrapped__(plugin)


def test_le_advertisement_teardown_unregisters_and_removes():
    plugin = LeAdvertiser()
    plugin.log = __import__("logging").getLogger("test.le")

    released = []

    class FakeAdv:
        adv_path = "/org/bluez/test/advertisement0"

        def remove_from_connection(self):
            released.append(True)

    class FakeManager:
        def UnregisterAdvertisement(self, path, **kw):
            reply = kw.get("reply_handler")
            if reply:
                reply()

    plugin.adv = FakeAdv()
    plugin.manager = FakeManager()
    LeAdvertiser.teardown.__wrapped__(plugin)

    assert released == [True]
