Requirements
============

General
-------

The following are needed:

- QEmu (x86_64)
- ``dbus-daemon`` available

Recommended:

- KVM-enabled x86_64 host system
- Preferably built BlueZ source tree
- ``chronyd`` available
- ``util-linux`` tools available
- ``agetty`` available

Kernel
------

Running VM-based tests requires a kernel image with similar
config as BlueZ **test-runner(1)**.  If given `--kernel-build` option, a
suitable image is built from sources downloaded under
`.pytest_cache`.

Simplest setup is

.. code-block::

	cp ../bluez/doc/tester.config .config
	make olddefconfig
	make -j8

To get log timestamps right, the kernel should have the following
configuration enabled:

.. code-block::

	CONFIG_HYPERVISOR_GUEST=y
	CONFIG_PARAVIRT=y
	CONFIG_KVM_GUEST=y

	CONFIG_PTP_1588_CLOCK=y
	CONFIG_PTP_1588_CLOCK_KVM=y
	CONFIG_PTP_1588_CLOCK_VMCLOCK=y

USB
---

Some tests may require a hardware controller instead of the virtual `btvirt` one.
