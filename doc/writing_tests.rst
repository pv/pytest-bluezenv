Writing tests
=============

Tests are ordinary Pytest functions. :obj:`~pytest_bluezenv.host_config`
declares the VM hosts and their plugins. The :obj:`~pytest_bluezenv.hosts`
fixture supplies one proxy per VM host. :doc:`overview` describes the
execution model.

Declaring a test
----------------

.. code-block:: python

   from pytest_bluezenv import host_config, Bluetoothd, Bluetoothctl

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

The decorator takes one argument per VM host. Each argument lists the
host plugins to load there. :obj:`~pytest_bluezenv.Bluetoothd` starts
``bluetoothd`` and :obj:`~pytest_bluezenv.Bluetoothctl` starts and drives
``bluetoothctl``.  By default the machines have ``btvirt`` controllers that
can see each other.

The test body runs on the upper tester. ``host0.bluetoothctl.*`` calls run
inside the first VM host over RPC. An exception from the lower tester is
reported as :obj:`~pytest_bluezenv.RemoteError`. The full configuration API
is documented at :obj:`~pytest_bluezenv.host_config`.

Fixtures
--------

The :obj:`~pytest_bluezenv.hosts` fixture gives the list of VM-host
proxies. It can reuse VM hosts from other tests. Host plugins are normally
torn down between tests.

.. code-block:: python

   def test_something(hosts):
       host0, host1 = hosts

:obj:`~pytest_bluezenv.hosts_once` reserves VM hosts for one test:

.. code-block:: python

   def test_something(hosts_once):
       host0, host1 = hosts_once

Running code on a host
----------------------

``host.call(func, *args, **kw)`` (from the
:obj:`~pytest_bluezenv.Call` plugin, loaded by default) runs a function
inside the VM and returns its result.

.. code-block:: python

   @host_config([Bluetoothd(conf="[General]\nExperimental = true")])
   def test_adv_monitor_crash(hosts):
       result = hosts[0].call(check_adv_monitor_crash)

   def check_adv_monitor_crash():
       # This runs on the VM side
       ...
       return 123

Pass ``sync=False`` to start the call without waiting; ``.wait()``
collects the result later.  The function and its arguments and return
value are pickled, so they must be importable on the VM.

.. code-block:: python

   def test_parallel(hosts):
       pending = hosts[0].call(slow_function, 1, 2, sync=False)
       ...                                # do something else meanwhile
       result = pending.wait()

Controlling a process
---------------------

:obj:`~pytest_bluezenv.Pexpect` drives a command-line program on a VM host
and reads its output with ``expect``.

.. code-block:: python

   def test_btmgmt(hosts):
       btmgmt = hosts[0].pexpect.spawn([find_exe("tools", "btmgmt")])
       btmgmt.send("info\n")
       btmgmt.expect("hci0")
       btmgmt.close()

The ``host.bluetoothctl`` handle used above is a ready-made
:obj:`~pytest_bluezenv.Bluetoothctl` plugin wrapping ``bluetoothctl``
with the same ``send`` / ``expect`` interface.

Asynchronous D-Bus events
-------------------------

Driving BlueZ over D-Bus is asynchronous. Method calls reply later and
the daemon can call back into the lower
tester. :obj:`~pytest_bluezenv.Agent` turns this into an ``expect`` /
``reply`` pattern.  ``expect`` returns an
:obj:`~pytest_bluezenv.Event` whose kind is the D-Bus method name, and
whose attributes are the method arguments.

.. code-block:: python

   from pytest_bluezenv import host_config, Agent, wait_until

   @host_config([Agent()], [Agent()])
   def test_pair(hosts):
       host0, host1 = hosts

       host0.agent.adapter_method("StartDiscovery")
       host0.agent.expect("org.bluez.Adapter1.StartDiscovery:reply")
       host1.agent.adapter_set("Discoverable", True)

       wait_until(host0.agent.has_device, host1.bdaddr)
       host0.agent.device_method(host1.bdaddr, "Pair")

       ev0 = host0.agent.expect("org.bluez.Agent1.RequestConfirmation")
       ev1 = host1.agent.expect("org.bluez.Agent1.RequestConfirmation")
       assert ev0.passkey == ev1.passkey

       host0.agent.reply()
       host1.agent.reply()
       host0.agent.expect("org.bluez.Device1.Pair:reply")

Outgoing method calls produce events named
``<interface>.<method>:reply`` and ``...:error``; incoming calls produce
events named after the method, and are answered with ``reply()`` or
``reply_error()``.

The same pattern is available for your own plugins through
:obj:`~pytest_bluezenv.EventPluginMixin` and
:obj:`~pytest_bluezenv.dbus_service_event_method`; see their API pages.

Writing a host plugin
---------------------

Host plugins run code on the VM side.  A plugin is a subclass of
:obj:`~pytest_bluezenv.HostPlugin`; its non-lifecycle methods are callable
over RPC.  ``bluetoothctl`` is implemented as:

.. code-block:: python

   import logging
   import signal
   import pexpect
   import pytest

   from pytest_bluezenv import HostPlugin, Bluetoothd, utils

   class Bluetoothctl(HostPlugin):
       name = "bluetoothctl"
       depends = [Bluetoothd()]          # load bluetoothd first

       def presetup(self, config):       # parent side, before VM starts
           try:
               self.exe = utils.find_exe("client", "bluetoothctl")
           except FileNotFoundError as exc:
               pytest.skip(reason=f"Bluetoothctl: {exc!r}")

       def setup(self, impl):            # VM side
           self.log = logging.getLogger(self.name)
           self.log_stream = utils.LogStream(self.name)
           self.ctl = pexpect.popen_spawn.PopenSpawn(
               self.exe, logfile=self.log_stream.stream,
               timeout=utils.DEFAULT_TIMEOUT,
           )

       def teardown(self):               # VM side
           self.ctl.sendeof()
           self.ctl.kill(signal.SIGTERM)

       def expect(self, *a, **kw):       # RPC-callable
           ret = self.ctl.expect(*a, **kw)
           return ret, self.ctl.match.groups()

       def send(self, *a, **kw):         # RPC-callable
           return self.ctl.send(*a, **kw)

The hooks run on the two sides as follows:

``__init__``
    Parent side, at collection time.  Store configuration on ``self``
    only; it must be picklable so it can be sent to the VM.

``presetup(config)``
    Parent side, during setup, before the VM starts.  Use
    ``pytest.skip()`` here to skip the test when a requirement is
    missing.

``setup(impl)`` / ``teardown()``
    VM side, at the start and end of the test.

Any other method is RPC-callable from the test; its return value is
pickled back.  The plugin appears as ``host.<name>``; set the
:obj:`~pytest_bluezenv.HostPlugin.value` attribute to control what the
parent sees instead of a plain RPC proxy
(see :obj:`~pytest_bluezenv.HostPlugin`).

Pass plugins to :obj:`~pytest_bluezenv.host_config` to load them.
Every host also gets a
few defaults automatically: :obj:`~pytest_bluezenv.Call` and
:obj:`~pytest_bluezenv.Rcvbuf`, plus :obj:`~pytest_bluezenv.Bdaddr`
(needed for a controller) unless ``controller=False``.

Reusing configuration and machines
----------------------------------

A configuration can be shared by several tests.  With ``reuse=True`` the
userspace (``bluetoothd`` and other plugins) is left running between
tests that use the same configuration --- useful when tests do not
perturb it much.

.. code-block:: python

   config = host_config([Bluetoothd()], reuse=True)

   @config
   def test_one(hosts):
       ...

   @config
   def test_two(hosts):
       ...              # same bluetoothd as test_one, not restarted

:obj:`~pytest_bluezenv.parametrized_host_config` runs one test over
several configurations, like ``pytest.mark.parametrize``:

.. code-block:: python

   @parametrized_host_config(
       [
           [[Bluetoothd()]],
           [[Bluetoothd(conf="[General]\nControllerMode = le")]],
       ],
       ids=["bredr", "le"],
   )
   def test_pairing_modes(hosts):
       ...

Choosing a controller
---------------------

Tests use the emulated ``btvirt`` controller, shared between the
machines, unless they ask otherwise.  Request a real controller with
``hw=True``; omit a controller entirely with ``controller=False``.

.. code-block:: python

   @host_config([Bluetoothd()], hw=True)          # needs --usb/--pcie
   def test_real_radio(hosts): ...

   @host_config([], controller=False)             # no controller at all
   def test_no_controller(hosts): ...

Real controllers come from ``--usb`` / ``--pcie`` and are selected
automatically otherwise; see :doc:`running_tests`.  Note that a machine
is reset with its controller **powered off**: ``bluetoothd`` turns it on,
but tests that run without it must power it on themselves, e.g. ``btmgmt
power on``.

The GLib main loop
------------------

Some host plugins use ``dbus-python``, which is not safe to call from
several threads at once.  On the VM side there is a single GLib main
loop for this: any method that touches D-Bus must run on it.  Decorate
such methods with :obj:`~pytest_bluezenv.mainloop_wrap` (or call them via
:obj:`~pytest_bluezenv.mainloop_invoke`) so they are dispatched onto the
main loop.

.. code-block:: python

   from pytest_bluezenv import HostPlugin, get_dbus, mainloop_wrap

   class MyPlugin(HostPlugin):
       name = "myplugin"

       @mainloop_wrap
       def is_powered(self):
           bus = get_dbus()
           ...
           return powered

:obj:`~pytest_bluezenv.Agent` and the D-Bus plugins already use the main
loop. A custom plugin that uses D-Bus directly needs the same arrangement.


LE advertising
--------------

In LE-only mode ``bluetoothd`` does not advertise the host by itself.
Add a :obj:`~pytest_bluezenv.LeAdvertiser` to make a host discoverable
and connectable by a peer:

.. code-block:: python

   from pytest_bluezenv import Bluetoothd, LeAdvertiser, host_config

   LE_CONF = "[General]\nControllerMode = le\n"

   @host_config(
       [Bluetoothd(conf=LE_CONF)],
       [Bluetoothd(conf=LE_CONF), LeAdvertiser(service_uuids=["180d"])],
   )
   def test_le_service(hosts):
       client, server = hosts

:obj:`~pytest_bluezenv.LeAdvertiser` registers a minimal connectable
``org.bluez.LEAdvertisement1`` object on ``/org/bluez/hci0``. Its
``service_uuids``, advertisement type, adapter path, object index, and
discoverability are configurable through its constructor.
