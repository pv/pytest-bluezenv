# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
import threading

import pytest

from .. import rpc


def test_call_round_trip_over_unix_sockets(tmp_path):

    def impl_1(text):
        return f"1: got {text}"

    class Impl2:
        def method(self, text):
            return f"2: got {text}"

        def error(self):
            raise FloatingPointError("test")

    def serve(socket_path, implementation, results, errors):
        try:
            results.append(rpc.server_unix_socket(socket_path, implementation))
        except BaseException as exc:
            errors.append(exc)

    socket_1 = tmp_path / "socket.1"
    socket_2 = tmp_path / "socket.2"
    results, errors = [], []

    threads = [
        threading.Thread(target=serve, args=(socket_1, impl_1, results, errors)),
        threading.Thread(target=serve, args=(socket_2, Impl2(), results, errors)),
    ]
    for t in threads:
        t.start()

    try:
        with rpc.client_unix_socket(socket_1) as c_1:
            with rpc.client_unix_socket(socket_2) as c_2:
                assert c_1.call("__call__", "hello 1") == "1: got hello 1"
                assert c_2.call("method", "hello 2") == "2: got hello 2"
                with pytest.raises(rpc.RemoteError, match="Remote traceback"):
                    c_2.call("error")
    finally:
        for t in threads:
            t.join(timeout=10)
            assert not t.is_alive()

    assert errors == []
    assert all(handled >= 1 for handled in results)


def test_remote_error_shows_original_exception_and_traceback():
    exc = ValueError("boom")
    err = rpc.RemoteError(exc, "Traceback (most recent call last):\n  line")

    assert str(exc) in str(err)
    assert "Remote traceback:" in str(err)
    assert err.exc is exc
    assert err.traceback.startswith("Traceback")
