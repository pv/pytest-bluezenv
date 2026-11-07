Requirements
============

General
-------

pytest-bluezenv requires:

- QEMU for x86_64, unless using a User Mode Linux kernel
- ``dbus-daemon``
- The Python dependencies declared by the package

Install the package and its Python dependencies in the environment that
runs Pytest:

.. code-block:: console

   $ python3 -m pip install pytest-bluezenv

The following are recommended:

- An x86_64 host with KVM enabled
- A built BlueZ source tree
- ``chronyd``, ``util-linux``, and ``agetty``

Kernel
------

VM-host tests require a kernel image. ``--kernel-build`` builds a suitable
image from sources in ``.pytest_cache`` when needed.

The BlueZ source tree provides a suitable configuration in
``doc/tester.config``. To build an image manually:

.. code-block::

	cp ../bluez/doc/tester.config .config
	make olddefconfig
	make -j8

pytest-bluezenv bundles a suitable base configuration, used for
``--kernel-build`` if not BlueZ source tree is provided.

For accurate VM-host log timestamps, the kernel needs these options:

.. code-block::

	CONFIG_HYPERVISOR_GUEST=y
	CONFIG_PARAVIRT=y
	CONFIG_KVM_GUEST=y

	CONFIG_PTP_1588_CLOCK=y
	CONFIG_PTP_1588_CLOCK_KVM=y
	CONFIG_PTP_1588_CLOCK_VMCLOCK=y

User Mode Linux
---------------

A User Mode Linux (UML) kernel can be used instead of QEMU, e.g. on
machines without KVM support. The VM hosts are then run as UML processes
by ``test-runner``, with a single ``btvirt`` serving their controllers and
control and log channels as vhost-user devices. Controller pass-through
and bumble-emulated controllers are not available; tests using them are
skipped. The kernel is built with ``ARCH=um`` from the same
configuration, with in addition:

.. code-block::

	CONFIG_HOSTFS=y
	CONFIG_VIRTIO_UML=y

.. code-block::

	make ARCH=um defconfig
	scripts/kconfig/merge_config.sh -m .config ../bluez/doc/tester.config
	scripts/config -e HOSTFS -e VIRTIO_UML
	make ARCH=um olddefconfig linux

and passed with ``--kernel=<linux>``, or the tree root. The hosts run on
real time: UML time travel runs the guests in lock-step, which makes
tests exchanging traffic between hosts slower.

USB
---

Some tests require a hardware controller rather than ``btvirt``. USB
pass-through requires permission to open the controller. PCIe pass-through
requires root, an enabled IOMMU, and an isolated IOMMU group. The relevant
commands are documented in :doc:`running_tests`.
