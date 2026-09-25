# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from .. import utils


def test_run_capture_and_check():
    result = utils.run(
        [sys.executable, "-c", "print('hi')"], capture_output=True, encoding="utf-8"
    )
    assert result.returncode == 0
    assert result.stdout == "hi\n"

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        utils.run([sys.executable, "-c", "import sys; sys.exit(3)"], check=True)
    assert excinfo.value.returncode == 3


def test_find_exe(monkeypatch, tmp_path):
    # Found on PATH.
    assert Path(utils.find_exe("", "sh")).is_file()

    # A missing executable raises FileNotFoundError.
    with pytest.raises(FileNotFoundError):
        utils.find_exe("subdir", "pytest-bluezenv-no-such-exe")

    # BUILD_DIR takes precedence and resolves <build>/<subdir>/<name>.
    exe = tmp_path / "subdir" / "prog"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setattr(utils, "BUILD_DIR", tmp_path)
    assert utils.find_exe("subdir", "prog") == os.path.normpath(str(exe))


def test_bluez_src_dir(monkeypatch, tmp_path):
    # Returns the location configured with --bluez-src-dir.
    monkeypatch.setattr(utils, "SRC_DIR", tmp_path)
    assert utils.bluez_src_dir() == tmp_path

    # A string location is normalized to a Path.
    monkeypatch.setattr(utils, "SRC_DIR", str(tmp_path))
    assert utils.bluez_src_dir() == tmp_path

    # Returns None when the option was not given.
    monkeypatch.setattr(utils, "SRC_DIR", None)
    assert utils.bluez_src_dir() is None


def test_bluez_src_dir_missing_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "SRC_DIR", tmp_path / "does-not-exist")

    with pytest.raises(FileNotFoundError, match="does-not-exist"):
        utils.bluez_src_dir()


class FakeTime:
    """Monotonic clock where time only advances when slept."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def fake_time(monkeypatch):
    fake = FakeTime()
    monkeypatch.setattr(utils, "time", fake)
    return fake


@pytest.mark.parametrize("turn_true", [0.0, 0.05, 0.35, 1.95, 12.0])
def test_wait_until_notices_shortly_after_true(fake_time, turn_true):
    polls = []

    def predicate():
        polls.append(fake_time.now)
        return fake_time.now >= turn_true

    utils.wait_until(predicate, timeout=60)

    # The floor of one 50 ms wait covers the shortest waits, 25% the
    # rest.
    assert fake_time.now - turn_true <= max(0.25 * turn_true, 0.05) + 1e-9

    # Checks are never closer than the minimum poll interval.
    assert all(b - a >= 0.05 - 1e-9 for a, b in zip(polls, polls[1:]))


def test_wait_until_paces_expensive_predicates(fake_time):
    polls = []

    def predicate():
        polls.append(fake_time.now)
        fake_time.sleep(0.3)
        return fake_time.now >= 5.0

    utils.wait_until(predicate, timeout=60)

    gaps = [b - a for a, b in zip(polls, polls[1:])]

    # Spacing is at least twice the previous call duration ...
    assert all(gap >= 0.6 - 1e-9 for gap in gaps)

    # ... but the 1 s cap still limits it.
    assert all(gap <= 1.3 + 1e-9 for gap in gaps)


def test_wait_until_times_out_after_full_timeout(fake_time):
    with pytest.raises(TimeoutError):
        utils.wait_until(lambda: False, timeout=20)

    assert fake_time.now == pytest.approx(20)


def test_wait_until_passes_arguments():
    seen = []

    def predicate(*a, **kw):
        seen.append((a, kw))
        return True

    utils.wait_until(predicate, 1, b=2)
    assert seen == [((1,), {"b": 2})]


def test_get_bdaddr(monkeypatch):
    class Result:
        def __init__(self, stdout):
            self.stdout = stdout

    def make_run(btmgmt_out, hciconfig_out):
        def run(cmd, **kwargs):
            name = os.path.basename(cmd[0])
            out = btmgmt_out if name == "btmgmt" else hciconfig_out
            return Result(out)

        return run

    monkeypatch.setattr(utils, "find_exe", lambda subdir, name: f"/fake/{name}")

    monkeypatch.setattr(
        utils.subprocess, "run", make_run("addr 11:22:33:44:55:66 version 0x08 ", "")
    )
    assert utils.get_bdaddr() == "11:22:33:44:55:66"

    # Falls back to hciconfig when btmgmt output has no address.
    monkeypatch.setattr(
        utils.subprocess,
        "run",
        make_run("no address here", "BD Address: AA:BB:CC:DD:EE:FF  ACL MTU"),
    )
    assert utils.get_bdaddr() == "aa:bb:cc:dd:ee:ff"


def test_log_stream(caplog):
    with utils.LogStream(__name__) as log_stream:
        log_stream.stream.write(b"hello")

    (record,) = (r for r in caplog.records if r.name == __name__)
    assert "hello" in record.message


def test_oops_tracker():
    for max_lines, kernel, lines in _get_oops_cases():
        tracker = utils.OopsTracker(kernel=kernel, max_lines=max_lines)
        state = utils.OopsTracker.NONE
        end = False
        for j, line in enumerate(lines):
            if line[:2] == "+ ":
                state = utils.OopsTracker.START
            elif line[:2] == "- ":
                end = True
            elif line[:2] == "x ":
                state = utils.OopsTracker.OVER
                end = True
            elif end:
                state = utils.OopsTracker.NONE
                end = False
            elif state == utils.OopsTracker.START:
                state = utils.OopsTracker.CONT

            result = tracker.parse_line(line[2:])
            assert result == state, (j, result, state, line, "\n".join(lines))


def _get_oops_cases():
    max_lines = None
    in_oops = False
    kernel = True
    lines = []

    for line in OOPS_TESTS.splitlines():
        if in_oops:
            if line.strip() == "<END>":
                yield max_lines, kernel, lines
                in_oops = False
            else:
                lines.append(line)
        else:
            m = re.match(r"^<START\s+([0-9]+) (user)?>$", line.strip())
            if m:
                in_oops = True
                max_lines = int(m.group(1))
                kernel = not bool(m.group(2))
                lines = []


OOPS_TESTS = """
<START 9999>
  Not yet
  ==================================================================
+ BUG: KASAN: slab-use-after-free in iso_conn_hold_unless_zero+0x4d/0x180
  Read of size 4 at addr ffff888002425108 by task kworker/u5:0/35
  
  CPU: 0 UID: 0 PID: 35 Comm: kworker/u5:0 Not tainted 7.1.0-rc6-01805-g7f895d421292 #539 PREEMPT(lazy) 
  Hardware name: QEMU Standard PC (Q35 + ICH9, 2009), BIOS 1.17.0-10.fc44 06/10/2025
  Workqueue: hci0 hci_cmd_sync_work
  Call Trace:
   <TASK>
   print_address_description+0x73/0x1f0
   </TASK>
  
  Allocated by task 34:
   kasan_save_track+0x3e/0x80
  
  Freed by task 34:
   kasan_save_track+0x3e/0x80
  
  The buggy address belongs to the object at ffff888002425000
   which belongs to the cache kmalloc-512 of size 512
  The buggy address is located 264 bytes inside of
   freed 512-byte region [ffff888002425000, ffff888002425200)
  
  The buggy address belongs to the physical page:
  page dumped because: kasan: bad access detected
  
  Memory state around the buggy address:
  >ffff888002425100: fb fb fb fb fb fb fb fb fb fb fb fb fb fb fb fb
                          
   ffff888002425200: fc fc fc fc fc fc fc fc fc fc fc fc fc fc fc fc
- ==================================================================
  Some other message
<END>

<START 5>
  Not yet
  ==================================================================
+ BUG: KASAN: slab-use-after-free in iso_conn_hold_unless_zero+0x4d/0x180
  Read of size 4 at addr ffff888002425108 by task kworker/u5:0/35
  
  CPU: 0 UID: 0 PID: 35 Comm: kworker/u5:0 Not tainted 7.1.0-rc6-01805-g7f895d421292 #539 PREEMPT(lazy) 
  Hardware name: QEMU Standard PC (Q35 + ICH9, 2009), BIOS 1.17.0-10.fc44 06/10/2025
x Workqueue: hci0 hci_cmd_sync_work
  Call Trace:
   <TASK>
   print_address_description+0x73/0x1f0
   </TASK>
  
   ffff888002425200: fc fc fc fc fc fc fc fc fc fc fc fc fc fc fc fc
  ==================================================================
  Some other message
<END>

<START 9999 user>
  Not yet
  =================================================================
+ ==284378==ERROR: AddressSanitizer: heap-use-after-free on address
  READ of size 4 at 0x7be636de0510 thread T0
      #0 0x00000049ea3e in timeout_callback
      #1 0x00000049f0f0 in timeout_callba
  
  freed by thread T0 here:
      #0 0x7fa6388ee4cf in free.part.
  
  SUMMARY: AddressSanitizer: heap-use-after-free 
  Shadow byte legend (one shadow byte represents 8 application bytes):
    Right alloca redzone:    cb
- ==284378==ABORTING
  After
<END>

<START 9999>
  ------------[ cut here ]------------
  refcount_t: decrement hit 0; leaking memory.
+ WARNING: lib/refcount.c:31 at refcount_warn_saturate+0x51/0xd0, CPU#0: iso-tester/36
  CPU: 0 UID: 0 PID: 36 Comm: iso-tester Not tainted 7.1.0-rc6-01819-g038fbb2bf1d2-dirty #704 PREEMPT(lazy) 
  Hardware name: QEMU Standard PC (Q35 + ICH9, 2009), BIOS 1.17.0-10.fc44 06/10/2025
  RIP: 0010:refcount_warn_saturate+0x51/0xd0
  FS:  00007f7116e36280(0000) GS:0000000000000000(0000) knlGS:0000000000000000
  CS:  0010 DS: 0000 ES: 0000 CR0: 0000000080050033
  CR2: 00007f7117b2ac40 CR3: 00000000019f2004 CR4: 0000000000170ef0
  Call Trace:
   <TASK>
   bt_sock_unlink+0x106/0x110
   entry_SYSCALL_64_after_hwframe+0x74/0x7c
  RIP: 0033:0x7f711735054e
  R13: 0000000000000001 R14: 0000000000000000 R15: 00007c31160e1198
   </TASK>
  irq event stamp: 104899
  softirqs last  enabled at (104536): [<ffffffff8fc8ad75>] iso_sock_kill+0x25/0x220
  softirqs last disabled at (104534): [<ffffffff8f65cdf0>] lock_sock_nested+0x60/0xe0
- ---[ end trace 0000000000000000 ]---
  End
<END>

<START 9999>
  Start
+ KASAN: maybe wild-memory-access in range [0xdeacfffffffffca0-0xdeacfffffffffca7]
  CPU: 0 UID: 0 PID: 42 Comm: syzrepro2 Not tainted 7.2.0-rc6-01461-gb73748377ac3-dirty #985 PREEMPT(lazy) 
  Hardware name: QEMU Standard PC (Q35 + ICH9, 2009), BIOS 1.17.0-10.fc44 06/10/2025
  RIP: 0010:__l2cap_chan_add+0x1be/0x850
  CR2: 0000000000477f10 CR3: 0000000001a62000 CR4: 00000000000006f0
  Call Trace:
   <TASK>
   l2cap_chan_connect+0x6cd/0xb80
   l2cap_sock_connect+0x27b/0x4b0
   ? __pfx_l2cap_sock_connect+0x10/0x10
   __sys_connect+0x16d/0x1d0
   __x64_sys_connect+0x75/0x90
   do_syscall_64+0xe7/0x3f0
   ? entry_SYSCALL_64_after_hwframe+0x74/0x7c
  R10: 0000000000000000 R11: 0000000000000246 R12: 0000000000000021
  R13: 00007ffc13dfbc80 R14: 0000000000000072 R15: 00007ffc13dfbd77
   </TASK>
- ---[ end trace 0000000000000000 ]---
  RIP: 0010:__l2cap_chan_add+0x1be/0x850
  CR2: 0000000000477f10 CR3: 0000000001a62000 CR4: 00000000000006f0
<END>

<START 9999>
  ======================================================
+ WARNING: possible circular locking dependency detected
  7.2.0-rc6-01463-gfe3897b4ab57 #994 Not tainted
  ------------------------------------------------------
  rfcomm-tester/364 is trying to acquire lock:
  
  -> #2 (rfcomm_mutex){+.+.}-{4:4}:
         ret_from_fork_asm+0x19/0x30
  
  -> #1 (hci_cb_list_lock){+.+.}-{4:4}:
         ret_from_fork_asm+0x19/0x30
  
  -> #0 (&hdev->lock){+.+.}-{4:4}:
         entry_SYSCALL_64_after_hwframe+0x74/0x7c
  
  other info that might help us debug this:
  
  Chain exists of:
    &hdev->lock --> hci_cb_list_lock --> rfcomm_mutex
  
   Possible unsafe locking scenario:
    lock(&hdev->lock);
  
   *** DEADLOCK ***
  
  1 lock held by rfcomm-tester/364:
   #0: ffffffff99499f58 (rfcomm_mutex){+.+.}-{4:4}, at: rfcomm_dlc_open+0x44/0x1070
  
  stack backtrace:
  CPU: 0 UID: 0 PID: 364 Comm: rfcomm-tester Not tainted 7.2.0-rc6-01463-gfe3897b4ab57 #994 PREEMPT(lazy) 
  Call Trace:
   <TASK>
   print_circular_bug+0x2e7/0x300
  R10: 0000000000000000 R11: 0000000000000202 R12: 00007b2b99ad7e40
  R13: 00007b2b99ad7e60 R14: 000000000000000d R15: 00007b8b9ade0140
-  </TASK>
  Next message
<END>

<START 9999>
  Not part of message
  ==================================
+ WARNING: Nested lock was not taken
  7.2.0-rc6-01510-g755cf7adf8dd-dirty #1217 Not tainted
  ----------------------------------
  l2cap-tester/37 is trying to lock:
  
  stack backtrace:
  CPU: 0 UID: 0 PID: 37 Comm: l2cap-tester Not tainted 7.2.0-rc6-01510-g755cf7adf8dd-dirty #1217 PREEMPT(lazy) 
  Hardware name: QEMU Standard PC (Q35 + ICH9, 2009), BIOS 1.17.0-10.fc44 06/10/2025
  Call Trace:
   <TASK>
   dump_stack_lvl+0x54/0x70
  R13: 0000000000000022 R14: 00007ca175de7980 R15: 00007b9174c41fe0
   </TASK>
  
  other info that might help us debug this:
  1 lock held by l2cap-tester/37:
   #0: ffff8880029c0510 (&chan->lock/1){+.+.}-{4:4}, at: l2cap_chan_lock_conn+0x107/0x220
  
  stack backtrace:
  CPU: 0 UID: 0 PID: 37 Comm: l2cap-tester Not tainted 7.2.0-rc6-01510-g755cf7adf8dd-dirty #1217 PREEMPT(lazy) 
  Call Trace:
   <TASK>
   dump_stack_lvl+0x54/0x70
  R13: 0000000000000022 R14: 00007ca175de7980 R15: 00007b9174c41fe0
-  </TASK>
  Not part of message
<END>

<START 9999>
  Not part of message
+ WARNING: Nested lock was not taken
+ WARNING: Nested lock was not taken
+ WARNING: Nested lock was not taken
  Not part of message
<END>
"""
