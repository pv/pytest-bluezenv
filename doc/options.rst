Options
=======

Command line
------------

The pytest-bluezenv plugin adds the following options.

``--kernel=<image>``
    Kernel image or built Linux source-tree root. When omitted,
    ``FUNCTIONAL_TESTING_KERNEL`` supplies the value.

``--usb=hci0,hci1``
    USB controllers available for hardware tests. When omitted,
    ``FUNCTIONAL_TESTING_CONTROLLERS`` supplies the value. Otherwise, all
    accessible USB controllers are considered.

``--force-usb``
    Use USB controllers instead of ``btvirt``.

``--pcie=hci0,hci1``
    PCIe controllers available for hardware tests. When omitted,
    ``FUNCTIONAL_TESTING_CONTROLLERS`` supplies the value. Otherwise, all
    PCIe controllers are considered. PCIe pass-through binds a controller
    to ``vfio-pci`` while a VM host uses it and requires root.

``--force-pcie``
    Use PCIe controllers instead of ``btvirt``.

``--bluez-build-dir=<path>``
    BlueZ build directory searched for executables.

``--bluez-src-dir=<path>``
    BlueZ source directory. It is searched for executables when no build
    directory is set, and supplies ``doc/tester.config`` for kernel builds.

``--log-filter=[+-]<pattern>,[+-]<pattern>,...``
    Comma-separated allow and deny patterns for loggers. A pattern is a
    shell glob. Prefix a pattern with ``+`` or ``-`` to allow or deny it.

``--no-log-reorder``
    Preserve log arrival order instead of timestamp order.

``--vm-timeout=<seconds>``
    Timeout, in seconds, for communication with VM hosts.

``--vm-mem=<amount>``
    Default VM-host memory, for example ``512M``.

``--btmon``
    Run ``btmon`` on all VM hosts and save traffic in
    ``test-bluezenv-*.btsnoop``.

``--bluezenv-progress=auto/on/off``
    Report slow host RPC calls. ``auto`` (the default) reports only on an
    interactive terminal; ``on`` also emits periodic lines when there is
    none. Enabling it forces verbose test-case output.

``--kernel-build=no/use/auto/force``
    Build a suitable kernel image from source. ``no`` disables builds,
    ``use`` uses a cached image (default), ``auto`` builds when needed, and ``force``
    rebuilds it. A bare ``--kernel-build`` selects ``auto``.

``--kernel-upstream=<GIT_URL>``
    Kernel source Git URL used by ``--kernel-build``.

``--kernel-branch=<GIT_BRANCH>``
    Kernel branch or revision used by ``--kernel-build``.

``--no-core-backtraces``
    Do not generate backtraces for collected core files.

Tests requiring an unavailable kernel image or hardware controller are
skipped. Tests use ``btvirt`` otherwise.

Each VM host shares ``/run/shared`` with the upper tester. The upper-tester
directory is normally ``/tmp/pytest-bluezenv-*/shared-*``. Captures and core
dumps are copied out before the test instance stops.

INI options
-----------

``bluezenv_progress=auto/on/off``
    Default value for ``--bluezenv-progress``.

``vm_timeout``
    Default timeout, in seconds, for RPC calls and wait helpers. The
    command-line option ``--vm-timeout`` overrides it.

``vm_mem``
    Default memory assigned to each VM host. The command-line option
    ``--vm-mem`` overrides it.

``kernel_upstream``
    Default Git URL used when building a kernel.

``kernel_branch``
    Default kernel branch or revision used when building a kernel.

``host_plugins.rcvbuf.default``
    Default receive-buffer size set by :obj:`~pytest_bluezenv.Rcvbuf` on
    each VM host. An explicit ``Rcvbuf(rcvbuf=...)`` overrides it.
