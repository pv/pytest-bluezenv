# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Progress reporting end to end.

``--bluezenv-progress`` must survive pytest's own stream capture: the
reporter writes from a background thread while a test phase runs, when
pytest has redirected the standard streams to a capture file. A write
that lands there is discarded, so these tests drive a real inner pytest
session and assert that the report reaches the terminal. A pty is used
for the interactive status line, and a pipe plus ``-u`` for periodic
lines. Only a real subprocess under a real terminal exercises capture,
so pytester cannot stand in here; no VM is needed because the lower
tester runs on a plain Unix socket, as in test_proxy.py.
"""

import fcntl
import os
import pty
import re
import struct
import subprocess
import sys
import termios
import textwrap
import threading

import pytest

CONFTEST = """
    import threading
    import time

    import pytest

    from pytest_bluezenv import (
        HostPlugin,
        HostProxy,
        env,
        plugin,
        progress,
        rpc,
        utils,
    )


    class Slow(HostPlugin):
        name = "slow"

        def wait(self, *args, **kwargs):
            time.sleep(1.2)
            return "done"


    @pytest.fixture(scope="session", autouse=True)
    def fast_progress():
        progress.PROGRESS_DELAY = 0.2
        progress.PROGRESS_INTERVAL = 0.05
        progress.PROGRESS_LINE_DELAY = 0.3
        progress.PROGRESS_LINE_INTERVAL = 0.25


    @pytest.fixture
    def host(tmp_path):
        socket_path = tmp_path / "rpc.socket"
        server = threading.Thread(
            target=rpc.server_unix_socket,
            args=(socket_path, env.Implementation()),
            daemon=True,
        )
        server.start()
        utils.wait_until(lambda: socket_path.exists(), timeout=10)
        host = HostProxy(
            str(socket_path),
            timeout=10,
            name="host.0.0",
            progress_reporter=plugin.PROGRESS_REPORTER,
        )
        host.load(Slow())
        try:
            yield host
        finally:
            host.close()
"""

TEST = """
    import threading

    def test_slow_call(host):
        print("captured-marker")
        assert host.slow.wait(1.2) == "done"


    def test_long_call_arguments(host):
        print("captured-marker")
        assert host.slow.wait("a" * 200, 1, 2, 3, 4, extra="b" * 200) == "done"


    def test_slow_call_from_other_thread(host):
        print("captured-marker")
        result = []

        def wait():
            result.append(host.slow.wait(1.2))

        thread = threading.Thread(target=wait)
        thread.start()
        thread.join()
        assert result == ["done"]
"""


def _make_ctty():
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def _run_case(tmp_path, args, pty_terminal, test_name="test_slow_call"):
    (tmp_path / "conftest.py").write_text(textwrap.dedent(CONFTEST))
    (tmp_path / "test_slow_call.py").write_text(textwrap.dedent(TEST))
    cmd = [
        sys.executable,
        "-u",
        "-mpytest",
        "-p",
        "pytest_bluezenv",
        f"test_slow_call.py::{test_name}",
        *args,
    ]
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    env["TERM"] = "xterm"

    if pty_terminal:
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        proc = subprocess.Popen(
            cmd,
            cwd=tmp_path,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            close_fds=True,
            preexec_fn=_make_ctty,
        )
        os.close(slave)
        chunks = []

        def pump():
            while True:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        try:
            returncode = proc.wait(timeout=120)
        finally:
            reader.join(timeout=10)
            os.close(master)
        return returncode, b"".join(chunks)

    proc = subprocess.run(
        cmd,
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        timeout=120,
    )
    return proc.returncode, proc.stdout


def _assert_run(returncode, output):
    assert returncode == 0, output.decode(errors="replace")
    assert b"1 passed" in output, output.decode(errors="replace")
    # A print in the test body is captured, not shown. Reporting must not
    # disturb pytest capture or the marker would leak to the terminal.
    assert b"captured-marker" not in output, output.decode(errors="replace")


def _visible_lines(output):
    ansi = re.compile(rb"\x1b\[[0-9;]*[A-Za-z]")
    chunks = re.split(rb"[\r\n]+", output)
    return [ansi.sub(b"", chunk) for chunk in chunks]


def test_progress_line_mode_reports_slow_call(tmp_path):
    # Without a terminal, ``on`` reports whole lines. The inner session
    # runs with default fd capture, so a report that does not escape the
    # capture never reaches stdout. The WAITING status word is only
    # written when the line can be rewritten in place.
    returncode, output = _run_case(tmp_path, ["--bluezenv-progress=on"], False)
    _assert_run(returncode, output)
    assert b"WAITING" not in output
    assert b"host.0.0: slow.wait(1.2) [" in output
    assert b"s left]" in output


def test_progress_status_line_visible_on_terminal(tmp_path):
    returncode, output = _run_case(tmp_path, ["--bluezenv-progress=on"], True)
    _assert_run(returncode, output)
    assert b"test_slow_call.py::test_slow_call WAITING" in output
    assert b"host.0.0: slow.wait(1.2) [" in output
    assert b"s left]" in output


def test_progress_truncates_long_call_arguments(tmp_path):
    returncode, output = _run_case(
        tmp_path, ["--bluezenv-progress=on"], True, test_name="test_long_call_arguments"
    )
    _assert_run(returncode, output)
    status_lines = [line for line in _visible_lines(output) if b"host.0.0" in line]
    assert status_lines
    assert all(b"..." in line for line in status_lines)
    assert all(line.endswith(b"s left]") for line in status_lines)
    assert all(len(line) < 80 for line in status_lines)


def test_progress_reports_from_xdist_worker(tmp_path):
    pytest.importorskip("xdist")
    returncode, output = _run_case(
        tmp_path, ["--bluezenv-progress=on", "-n", "1"], True
    )
    _assert_run(returncode, output)
    assert b"WAITING" in output
    assert b"\n[gw0] host.0.0: slow.wait(1.2) [" in output
    assert b"s left]" in output


@pytest.mark.parametrize("mode", ["off", "auto"])
def test_progress_disabled_emits_nothing(tmp_path, mode):
    # ``off`` disables reporting; ``auto`` on a non-terminal pipe must
    # stay silent.
    returncode, output = _run_case(tmp_path, [f"--bluezenv-progress={mode}"], False)
    _assert_run(returncode, output)
    assert b"WAITING" not in output
    assert b"host.0.0:" not in output


def test_progress_reports_non_main_thread_call(tmp_path):
    # Reporting writes through a descriptor duplicated from the original
    # standard output at import, and never redirects the streams itself.
    # It is therefore safe for calls issued by threads other than the
    # pytest one.
    returncode, output = _run_case(
        tmp_path,
        ["--bluezenv-progress=on"],
        False,
        test_name="test_slow_call_from_other_thread",
    )
    _assert_run(returncode, output)
    assert b"WAITING" not in output
    assert b"host.0.0: slow.wait(1.2) [" in output
    assert b"s left]" in output
