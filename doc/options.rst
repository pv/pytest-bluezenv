Command line
============

The `pytest-bluezenv` plugin adds the following command-line options:

``--kernel=<image>``
        Kernel image (or built Linux source tree root) to
	use.  See **test-runner(1)** and `tester.config` for required
	kernel config.

	If not provided, value from `FUNCTIONAL_TESTING_KERNEL`
	environment variable is used. If none, no image is used.

``--usb=hci0,hci1``
        USB controllers to use in tests that require use of
	real controllers.

	If not provided, value from `FUNCTIONAL_TESTING_CONTROLLERS`
	environment variable is used. If none, all USB controllers
	with suitable permissions are considered.

``--btmon``
        Launch btmon on all hosts to log events, and dump traffic to
	test-bluezenv-\*.btsnoop

``--force-usb``
        Force tests to use USB controllers instead of `btvirt`.

``--vm-timeout=<seconds>``
        Specify timeout for communication with VM hosts.

``--log-filter=[+-]<pattern>,[+-]<pattern>,...``
        Allow/deny lists
	for filtering logging output. The pattern is a shell glob matching
	to the logger names.

``--build-dir=<path>``
        Path to build directory where to search for BlueZ
        executables.

``--kernel-build=no/use/auto/force``
        Build a suitable kernel image from source.

``--kernel-upstream=<GIT_URL>``
        URL for Git clone of kernel sources.

``--kernel-branch=<GIT_BRANCH>``
        Git branch to build from.

Tests that require kernel image or USB controllers are skipped if none
are available. Normally, tests use `btvirt`.

VM instances share a directory ``/run/shared`` with host machine,
located on host usually in ``/tmp/pytest-bluezenv-*/shared-*``.  Core
dumps etc. are copied out from it before test instance is shut down.
