Writing tests
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
