===============
pytest-bluezenv
===============

**pytest-bluezenv** Pytest plugin is used for functional testing of
BlueZ and kernel using multiple virtual machine environments,
connected by real or virtual controllers.

OPTIONS
=======

The `pytest-bluezenv` plugin has command-line options:

:--kernel=<image>: Kernel image (or built Linux source tree root) to
	use.  See **test-runner(1)** and `tester.config` for required
	kernel config.

	If not provided, value from `FUNCTIONAL_TESTING_KERNEL`
	environment variable is used. If none, no image is used.

:--usb=hci0,hci1: USB controllers to use in tests that require use of
	real controllers.

	If not provided, value from `FUNCTIONAL_TESTING_CONTROLLERS`
	environment variable is used. If none, all USB controllers
	with suitable permissions are considered.

:--btmon: Launch btmon on all hosts to log events, and dump traffic to
	test-bluezenv-\*.btsnoop

:--force-usb: Force tests to use USB controllers instead of `btvirt`.

:--vm-timeout=<seconds>: Specify timeout for communication with VM hosts.

:--log-filter=[+-]<pattern>,[+-]<pattern>,...: Allow/deny lists
	for filtering logging output. The pattern is a shell glob matching
	to the logger names.

:--build-dir=<path>: Path to build directory where to search for BlueZ
        executables.

:--kernel-build=no/use/auto/force: Build a suitable kernel image from source.

:--kernel-upstream=<GIT_URL>: URL for Git clone of kernel sources.

:--kernel-branch=<GIT_BRANCH>: Git branch to build from.

Tests that require kernel image or USB controllers are skipped if none
are available. Normally, tests use `btvirt`.

VM instances share a directory ``/run/shared`` with host machine,
located on host usually in ``/tmp/pytest-bluezenv-*/shared-*``.  Core
dumps etc. are copied out from it before test instance is shut down.


REQUIREMENTS
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


EXAMPLES
========

Run all tests
-------------

.. code-block::

	$ python3 -mpytest --kernel=/pathto/bzImage

	$ export FUNCTIONAL_TESTING_KERNEL=/pathto/bzImage
	$ python3 -mpytest

Show output during run
----------------------

.. code-block::

	$ python3 -mpytest --log-cli-level=0

Show only specific loggers:

.. code-block::

	$ python3 -mpytest --log-cli-level=0 --log-filter=rpc,host

	$ python3 -mpytest --log-cli-level=0 --log-filter=*.bluetoothctl

Filter out loggers:

.. code-block::

	$ python3 -mpytest --log-cli-level=0 --log-filter=-host

	$ python3 -mpytest --log-cli-level=0 --log-filter=host,-host.*.1

Run selected tests
------------------

.. code-block::

	$ python3 -mpytest test/functional/test_cli_simple.py::test_bluetoothctl_script_show

	$ python3 -mpytest -k test_bluetoothctl_script_show

	$ python3 -mpytest -k 'test_btmgmt or test_bluetoothctl'

Don't run tests with a given marker:

.. code-block::

	$ python3 -mpytest -m "not pipewire"

Don't run known-failing tests:

.. code-block::

	$ python3 -mpytest -m "not xfail"

Note that otherwise known-failing tests would be run, but with
failures suppressed.

Run previously failed and stop on failure
-----------------------------------------

.. code-block::

	$ python3 -mpytest -x --ff

Show errors from know-failing test
----------------------------------

.. code-block::

	$ python3 -mpytest --runxfail -k test_btmgmt_info

Redirect USB devices
--------------------

.. code-block::

	$ python3 -mpytest --usb=hci0,hci1

	$ export FUNCTIONAL_TESTING_CONTROLLERS=hci0,hci1
	$ python3 -mpytest -vv

This does not require running as root. Changing device permissions is
sufficient. In verbose mode (``-vv``) some instructions are printed.

Run all tests using the USB controllers:

.. code-block::

	$ python3 -mpytest --usb=hci0,hci1 --force-usb

Run tests in parallel
---------------------

pytest-xdist is required for parallel execution. To run:

.. code-block::

	$ python3 -mpytest -n auto

To reduce VM setup/teardowns:

.. code-block::

	$ python3 -mpytest -n auto --dist loadgroup

Logging in to a test VM instance
--------------------------------

While test is running:

.. code-block::

	$ python3 -mpytest_bluezenv attach

For this to be useful, usually, you need to pause the test
e.g. by running with ``--trace`` option.

To do it manually, when starting the tester will log a line like::

	TTY: socat /tmp/pytest-bluezenv-q658swgi/pytest-bluezenv-tty-0 STDIO,rawer

with the location of the socket where the serial is connected to.

WRITING TESTS
=============

The functional tests are written in files (test modules) names
`test/functional/test_*.py`.  They are written using standard Pytest
style.  See https://docs.pytest.org/en/stable/getting-started.html

Use `Black <https://black.readthedocs.io/en/stable/>`__ to autoformat
Python test code.

Example: Virtual machines
-------------------------

.. code-block:: python

   from pytest_bluez import host_config, Bluetoothd, Bluetoothctl

   @host_config(
       [Bluetoothd(), Bluetoothctl()],
       [Bluetoothd(), Bluetoothctl()],
   )
   def test_bluetoothctl_pair(hosts):
       host0, host1 = hosts

       host0.bluetoothctl.send("scan on\n")
       host0.bluetoothctl.expect(f"Controller {host0.bdaddr.upper()} Discovering: yes")

       host1.bluetoothctl.send("pairable on\n")
       host1.bluetoothctl.expect("Changing pairable on succeeded")
       host1.bluetoothctl.send("discoverable on\n")
       host1.bluetoothctl.expect(f"Controller {host1.bdaddr.upper()} Discoverable: yes")

       host0.bluetoothctl.expect(f"Device {host1.bdaddr.upper()}")
       host0.bluetoothctl.send(f"pair {host1.bdaddr}\n")

       idx, m = host0.bluetoothctl.expect(r"Confirm passkey (\d+).*:")
       key = m[0].decode("utf-8")

       host1.bluetoothctl.expect(f"Confirm passkey {key}")

       host0.bluetoothctl.send("yes\n")
       host1.bluetoothctl.send("yes\n")

       host0.bluetoothctl.expect("Pairing successful")

The test declares a VM setup with two Qemu instances, where both hosts
run bluetoothd and start a bluetoothctl process.  The Qemu instances
have `btvirt` virtual BT controllers and can see each other.

The test itself runs on the parent host.

The `host0/1.bluetoothctl.*` commands invoke RPC calls to one of the
the two VM instances. In this case, they are controlling the
`bluetoothctl` process using `pexpect` library to deal with its
command line.

When the test body finishes executing, the test passes. Or, it fails
if any ``assert`` statement fails or an error is raised. For example,
above ``RemoteError`` due to bluetoothctl not proceeding as expected
in pairing is possible.

The host configuration (bluetoothd + bluetoothctl above) is torn down
between test (SIGTERM/SIGKILL sent etc.).

By default the VM instance itself continues running, and may be used
for other tests that share the same VM setup.

Generally, the framework automatically orders the tests so that the VM
setup does not need to be restarted unless needed.


Example host plugin
-------------------

The `host.bluetoothctl` implementation used above is as follows:

.. code-block:: python

   from pytest_bluez import HostPlugin, Bluetoothd

   class Bluetoothctl(Pexpect):
       # Declare unique plugin name
       name = "bluetoothctl"

       # Declare plugin dependencies to be loaded first
       depends = [Bluetoothd()]

       # These run on parent host side:

       def __init__(self, subdir, name):
           self.exe = utils.find_exe(subdir, name)

       def presetup(self):
           pass

       # These run on VM side at setup/teardown:

       def setup(self, impl):
           self.log = logging.getLogger(self.name)
           self.log_stream = utils.LogStream(self.name)
           self.ctl = pexpect.spawn(self.exe, logfile=self.log_stream.stream)

       def teardown(self):
           self.ctl.terminate()

       # These define custom RPC methods that can be called

       def expect(self, *a, **kw):
           ret = self.ctl.expect(*a, **kw)
           self.log.debug("match found")
           return ret, self.ctl.match.groups()

       def send(self, *a, **kw):
           return self.ctl.send(*a, **kw)

Host plugins are for injecting code to run on the VM side test hosts.
The host plugins have scope of one test.  The VM side test framework
sends SIGTERM and SIGKILL to all processes in the test process group
to reset the state between each test.

The plugins are declared by inheriting from `HostPlugin`. Their
`__init__()` is supposed to only store declarative configuration on
`self` and runs on parent side early in the test discovery phase.  The
`presetup` runs on parent side in test setup phase, before VM
environment is started. The plugin can for example do
`pytest.skip(reason="something")` to skip the test.

The `setup()` and `teardown()` methods run on VM-side at host
environment start and end.  All other methods can be invoked via RPC
by the parent tester, and any values returned by them are passed via
RPC back to the parent.

To load a plugin to a VM host, pass it to `host_config()` in the
declaration of a given test.
