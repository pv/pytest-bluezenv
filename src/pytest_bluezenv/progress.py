# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""Progress reporting for slow host RPC calls."""

import os
import threading
import time

PROGRESS_DELAY = 3.0
PROGRESS_INTERVAL = 1.0
PROGRESS_LINE_DELAY = 5.0
PROGRESS_LINE_INTERVAL = 10.0
PROGRESS_ARG_LIMIT = 60


def _arg_repr(value):
    try:
        text = " ".join(repr(value).split())
    except BaseException:
        return "..."
    if len(text) > PROGRESS_ARG_LIMIT:
        text = text[: PROGRESS_ARG_LIMIT - 3] + "..."
    return text


class ProgressReporter:
    """
    Report RPC calls that take longer than expected.

    On a terminal the running test line gets a ``WAITING`` status and the
    awaited call, its arguments and its elapsed and remaining time are
    updated in place on the line below. When pytest reports the test, the
    status line is replaced by the normal pytest status line. Without a
    terminal, and in a pytest-xdist worker that cannot rewrite the
    controller's lines, whole lines are emitted periodically instead.

    Output goes through a stream on a duplicate of the standard output
    opened at session start, which bypasses pytest's per-phase stream
    capture during test phases.
    """

    def __init__(self, stream, rewrite, worker=None):
        """
        Create a progress reporter.

        Args:
            stream: writable text stream, closed in ``close``.
            rewrite (bool): update a line in place, or emit periodic lines.
            worker (str): pytest-xdist worker id, or None.
        """
        self.stream = stream
        self.rewrite = rewrite
        self.worker = worker
        self._closed = False
        self._lock = threading.Lock()
        self._tokens = set()
        self._shown = None
        self._test_line = None
        self._waiting_shown = False

    @classmethod
    def from_config(cls, config, option):
        """Create a reporter for the session, or None when disabled."""
        if option == "off":
            return None

        worker = getattr(config, "workerinput", None)
        if worker is not None:
            # The worker cannot rewrite the controller's lines, so report
            # whole lines on the controlling terminal.
            try:
                stream = open("/dev/tty", "w", buffering=1, errors="replace")
            except OSError:
                return None
            return cls(stream, rewrite=False, worker=worker["workerid"])

        # The global capture is suspended at session start, so fd 1 is
        # the real standard output even under capture.
        try:
            stream = os.fdopen(os.dup(1), "w", buffering=1, errors="replace")
        except OSError:
            return None

        rewrite = stream.isatty()
        if option == "auto" and not rewrite:
            stream.close()
            return None

        return cls(stream, rewrite=rewrite)

    def call_started(self, connection, label, timeout, args=(), kwargs=None):
        """
        Start reporting a call. Returns a token for ``call_finished``, or
        None when reporting is already closed.

        Args:
            connection: RPC connection; supplies the default timeout.
            label (str): operation label, e.g. "bluetoothd.read".
            timeout (float): call timeout in seconds, or None.
            args, kwargs: arguments of the call.
        """
        if timeout is None:
            timeout = connection.timeout

        name = connection.log.name
        name = name[len("rpc.") :] if name.startswith("rpc.") else name
        base = f"{name}: {label}" if name else label

        parts = [_arg_repr(arg) for arg in list(args)[:3]]
        kwargs = kwargs or {}
        parts += [
            f"{key}={_arg_repr(value)}" for key, value in sorted(kwargs.items())[:3]
        ]
        if len(args) > 3 or len(kwargs) > 3:
            parts.append("...")
        if parts:
            base = f"{base}({', '.join(parts)})"

        token = _Call(self, base, timeout)
        with self._lock:
            if self._closed:
                return None
            self._tokens.add(token)
        token.thread.start()
        return token

    def call_finished(self, token):
        """Stop reporting a call.

        Args:
            token: token returned by ``call_started``.
        """
        token.done.set()
        token.thread.join()
        with self._lock:
            self._tokens.discard(token)

    def close(self):
        """Stop reporting and release the stream."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            tokens = list(self._tokens)
        for token in tokens:
            token.done.set()
            token.thread.join()
        with self._lock:
            if self._shown is not None:
                self._erase()
        self.stream.close()

    def set_test(self, line):
        """
        Set the pytest test line currently running, with the trailing
        space before the status word.
        """
        with self._lock:
            if self._closed:
                return
            if self._test_line != line:
                if self._shown is not None:
                    self._erase()
                self._test_line = line
                self._waiting_shown = False

    def finish_test(self):
        with self._lock:
            if self._shown is not None:
                self._erase()
            self._test_line = None
            self._waiting_shown = False

    def prepare_report(self):
        """
        Give the status line back to pytest before it reports the test,
        so the status word lands on the test line.
        """
        with self._lock:
            if self._closed or not self._waiting_shown:
                return
            if self._shown is not None:
                self._erase()
            if self.rewrite:
                self._write(self._test_line)
            self._test_line = None
            self._waiting_shown = False

    def show(self, token):
        """
        Format and emit the status line of a ticking call: the awaited
        call with its arguments, and its elapsed and remaining time.
        Rewrites the line in place when ``rewrite``, otherwise emits a
        whole line.
        """
        with self._lock:
            if self._closed:
                return

            if not self._waiting_shown and self._test_line is not None:
                if self.rewrite:
                    # The cursor sits just past the test line written on
                    # this stream.
                    self._write("WAITING\n")
                self._waiting_shown = True

            prefix = f"[{self.worker}] " if self.worker else "    "
            elapsed = time.monotonic() - token.start
            if token.timeout:
                status = (
                    f"{elapsed:.0f}s, {max(0.0, token.timeout - elapsed):.0f}s left"
                )
            else:
                status = f"{elapsed:.0f}s"
            suffix = f" [{status}]"

            try:
                width = os.get_terminal_size(self.stream.fileno()).columns
            except (AttributeError, ValueError, OSError):
                width = 80
            # Leave a margin so the rewrite cannot race the wrap.
            max_width = max(16, width - 17)

            line = f"{prefix}{token.base}{suffix}"
            if len(line) > max_width:
                # Fit within width, keeping the prefix and the
                # elapsed/remaining time.
                keep = max_width - len(prefix) - len(suffix) - 3
                line = (
                    prefix + token.base[:keep] + "..." + suffix if keep > 0 else suffix
                )

            if self.rewrite:
                self._write(f"\r{line}\x1b[K")
                self._shown = token
            else:
                self._write(f"\n{line}")

    def clear(self, token):
        with self._lock:
            if self._shown is token:
                self._write("\n")

        self._shown = None

    def _write(self, text):
        try:
            self.stream.write(text)
            self.stream.flush()
        except OSError:
            pass


class _Call:
    """Ticker for one reported call: wakes the reporter periodically."""

    def __init__(self, reporter, base, timeout):
        self.reporter = reporter
        self.base = base
        self.timeout = timeout
        self.start = None
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        self.start = time.monotonic()
        if self.done.wait(PROGRESS_DELAY):
            return

        rewrite = self.reporter.rewrite
        next_line = PROGRESS_LINE_DELAY
        shown = False

        while True:
            if rewrite:
                delay = PROGRESS_INTERVAL
            else:
                delay = max(0.0, next_line - (time.monotonic() - self.start))
            if self.done.wait(delay):
                break

            self.reporter.show(self)
            if rewrite:
                shown = True
            else:
                next_line += PROGRESS_LINE_INTERVAL

        if shown:
            self.reporter.clear(self)
