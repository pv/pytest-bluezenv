# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
import os
import re
import pytest
import subprocess
import threading
import pytest

from .. import utils


def test_log_stream(caplog):
    with utils.LogStream(__name__) as log_stream:
        log_stream.stream.write(b"hello")

    (record,) = (r for r in caplog.records if r.name == __name__)
    assert "hello" in record.message


def test_oops_tracker():
    expect_table = {
        "+ ": utils.OopsTracker.START,
        ". ": utils.OopsTracker.CONT,
        "  ": utils.OopsTracker.NONE,
    }

    for max_lines, lines in _get_oops_cases():
        tracker = utils.OopsTracker(max_lines=max_lines)
        state = utils.OopsTracker.NONE
        end = False
        for j, line in enumerate(lines):
            if line[:2] == b"+ ":
                state = utils.OopsTracker.START
            elif line[:2] == b"- ":
                end = True
            elif end:
                state = utils.OopsTracker.NONE
                end = False
            elif state == utils.OopsTracker.START:
                state = utils.OopsTracker.CONT

            result = tracker.parse_line(line[2:])
            assert result == state, (j, result, state, line, b"\n".join(lines))


def _get_oops_cases():
    max_lines = None
    in_oops = False
    lines = []

    for line in OOPS_TESTS.splitlines():
        if in_oops:
            if line.strip() == b"<END>":
                yield max_lines, lines
                in_oops = False
            else:
                lines.append(line)
        else:
            m = re.match(rb"^<START\s+([0-9]+)>$", line.strip())
            if m:
                in_oops = True
                max_lines = int(m.group(1))
                lines = []


OOPS_TESTS = b"""
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
- Hardware name: QEMU Standard PC (Q35 + ICH9, 2009), BIOS 1.17.0-10.fc44 06/10/2025
  Workqueue: hci0 hci_cmd_sync_work
  Call Trace:
   <TASK>
   print_address_description+0x73/0x1f0
   </TASK>
  
   ffff888002425200: fc fc fc fc fc fc fc fc fc fc fc fc fc fc fc fc
  ==================================================================
  Some other message
<END>

<START 9999>
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
