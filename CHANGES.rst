Development:
   - *(Backward incompatible)* Power controller off before tests.
     Tests not using bluetoothd must now power it on explicitly.
   - *(Backward incompatible)* Rename ``usb_indices`` fixture to
     ``hw_indices``.
   - *(Backward incompatible)* For Call ``sync=False`` its `.wait()`
     now raises possible exceptions, instead of returning them.
   - Add PCIe controller passthrough with --pcie and --force-pcie.
   - Add ``LeAdvertiser`` host plugin for connectable LE advertisements.
   - Add ``Agent.device_get`` and ``Agent.device_set`` helpers for
     ``org.bluez.Device1`` properties.
   - Add progress reporting for slow host RPC calls with
     ``--bluezenv-progress``.
   - Expose ``bluez_src_dir`` for locating files in the BlueZ source
     tree given by ``--bluez-src-dir``.

v0.1.9:
   - Add configurable default VM memory with --vm-mem.
   - Collect kernel oops and sanitizer logs from all test logs.

v0.1.8:
   - Support Python 3.8 and newer.
   - Improve kernel oops parsing and btvirt sanitizer diagnostics.

v0.1.7:
   - Generate gdb backtraces for core dumps by default.
   - Add safe handling for warnings that are configured as errors.

v0.1.6:
   - Add helpers for system and session D-Bus connections.
   - Detect crashed QEMU, btvirt, and test-runner processes.

v0.1.5:
   - Support test environments without a Bluetooth controller.
   - Bundle required BlueZ sources in source distributions.

v0.1.4:
   - Wait for host core dumps to finish before collecting them.

v0.1.3:
   - Cleanly close hosts when environment setup fails.

v0.1.2:
   - Add the attach subcommand.
   - Use a non-debug kernel configuration if no --bluez-src-dir given.

v0.1.1:
   - Add PyPI packaging and distribution support.

v0.1:
   - Initial release of the pytest BlueZ environment plugin.
