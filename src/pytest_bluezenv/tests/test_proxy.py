# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Parent-side proxies against a lower tester.

The lower tester runs in a guest, so a real QEMU host is the only way to
reach it otherwise.  Run the production VM-side ``Implementation`` behind a
plain Unix socket instead: the RPC transport is real, only QEMU is left out.
"""

import threading

import pytest

from pytest_bluezenv import (
    HostPlugin,
    HostProxy,
    PluginProxy,
    RemoteError,
    env,
    rpc,
    utils,
)


class ValuePlugin(HostPlugin):
    name = "value"

    def setup(self, impl):
        self.value = 123


class FakeConn:
    def __init__(self):
        self.calls = []
        self.log = type("Log", (), {"debug": lambda *args, **kwargs: None})()

    def call(self, *a, **kw):
        self.calls.append((a, kw))
        return "result"


class EchoPlugin(HostPlugin):
    name = "echo"

    def __call__(self, text):
        return f"echo {text}"

    def shout(self, text):
        return text.upper()


class BadPlugin(HostPlugin):
    name = "bad"

    def setup(self, impl):
        raise RuntimeError("plugin-boom")


@pytest.fixture
def host(tmp_path):
    socket_path = tmp_path / "rpc.socket"
    server = threading.Thread(
        target=rpc.server_unix_socket,
        args=(socket_path, env.Implementation()),
        daemon=True,
    )
    server.start()
    utils.wait_until(socket_path.exists, timeout=10)

    host = HostProxy(str(socket_path), timeout=10, name="host.test")
    try:
        yield host
    finally:
        host.close()
        server.join(timeout=10)
        assert not server.is_alive(), "lower tester did not exit on close"


def test_host_plugin_attribute_requires_loaded_plugin():
    host = HostProxy("/path", timeout=1, name="host.0.0")
    with pytest.raises(AttributeError):
        host.no_such_plugin


def test_plugin_proxy_rejects_private_names():
    proxy = PluginProxy()
    proxy.set_connection("p", None)
    with pytest.raises(AttributeError):
        proxy._secret


def test_load_exposes_plugin_value(host):
    host.load(ValuePlugin())
    assert host.value == 123


def test_loaded_plugin_without_value_gives_rpc_proxy(host):
    host.load(EchoPlugin())
    assert isinstance(host.echo, PluginProxy)
    assert host.echo.shout("hi") == "HI"
    assert host.echo("yo") == "echo yo"


def test_plugin_load_error_surfaces_as_remote_error(host):
    with pytest.raises(RemoteError, match="load failed"):
        host.load(BadPlugin())


class ProgressReporter:
    def __init__(self):
        self.events = []

    def call_started(self, connection, label, timeout, args=(), kwargs=None):
        self.events.append(("started", label, timeout, args, kwargs))
        return label

    def call_finished(self, token):
        self.events.append(("finished", token))


def test_plugin_proxy_reports_labeled_calls():
    conn = FakeConn()
    reporter = ProgressReporter()
    proxy = PluginProxy()
    proxy.set_connection("agent", conn, reporter)

    assert proxy.expect("event", timeout=3) == "result"
    assert reporter.events == [
        ("started", "agent.expect", 3, ("event",), {}),
        ("finished", "agent.expect"),
    ]


def test_plugin_proxy_reports_failed_call():
    conn = FakeConn()

    def boom(*a, **kw):
        raise RuntimeError("boom")

    conn.call = boom
    reporter = ProgressReporter()
    proxy = PluginProxy()
    proxy.set_connection("agent", conn, reporter)

    with pytest.raises(RuntimeError, match="boom"):
        proxy.expect("event")

    assert reporter.events == [
        ("started", "agent.expect", None, ("event",), {}),
        ("finished", "agent.expect"),
    ]


def test_plugin_proxy_call_survives_reporter_error():
    conn = FakeConn()

    class BrokenReporter:
        def call_started(self, *args, **kwargs):
            raise RuntimeError("reporter bug")

        def call_finished(self, token):
            raise RuntimeError("reporter bug")

    proxy = PluginProxy()
    proxy.set_connection("agent", conn, BrokenReporter())

    assert proxy.expect("event") == "result"
