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
``bluetoothctl``. By default the VM hosts have ``btvirt`` controllers that
can see each other.

The test body runs on the upper tester. ``host0.bluetoothctl.*`` calls run
inside the first VM host over RPC. An exception raised in the VM host is
reported as :obj:`~pytest_bluezenv.RemoteError`. The full configuration API
is documented at :obj:`~pytest_bluezenv.host_config`.

Fixtures
--------

The :obj:`~pytest_bluezenv.hosts` fixture yields the list of VM-host
proxies. The VM hosts can be reused by tests with matching VM
configuration.

The :obj:`~pytest_bluezenv.hosts_once` fixture instead reserves a
separate VM host for the test.

.. code-block:: python

   from pytest_bluezenv import host_config

   @host_config([], [])
   def test_something(hosts):
       host0, host1 = hosts

   @host_config([], [])
   def test_isolated_hosts(hosts_once):
       host0, host1 = hosts_once

Host plugins are normally torn down between tests, even when a VM host is
reused. Pass ``reuse=True`` to :obj:`~pytest_bluezenv.host_config` when
consecutive tests use the same plugin instances and should not restart
the userspace programs.

Built-in host plugins
---------------------

The built-in plugins cover common BlueZ test setups:

* :obj:`~pytest_bluezenv.Agent` registers a test implementation of
  ``org.bluez.Agent1`` and exposes asynchronous D-Bus events.
* :obj:`~pytest_bluezenv.LeAdvertiser` registers a connectable LE
  advertisement. Add it to a host using LE-only mode, as shown below.
* :obj:`~pytest_bluezenv.Obexd` starts ``obexd``.
* :obj:`~pytest_bluezenv.Bluetoothd` starts ``bluetoothd``.
* :obj:`~pytest_bluezenv.Bluetoothctl` starts ``bluetoothctl``.
* :obj:`~pytest_bluezenv.Pexpect` allows controlling other command-line programs.
* :obj:`~pytest_bluezenv.Btmon` captures controller traffic. The
  ``--btmon`` option can be used to load it.
* :obj:`~pytest_bluezenv.DbusSystem` and
  :obj:`~pytest_bluezenv.DbusSession` start D-Bus system and session buses.

.. code-block:: python

   from pytest_bluezenv import Obexd, host_config

   @host_config([Obexd()])
   def test_obex(hosts):
       host = hosts[0]
       # Exercise OBEX through a D-Bus client or a test-specific plugin.

Every host also loads :obj:`~pytest_bluezenv.Call` and
:obj:`~pytest_bluezenv.Rcvbuf`. Hosts with a controller also load
:obj:`~pytest_bluezenv.Bdaddr`, which provides ``host.bdaddr``.

Running code on a host
----------------------

``host.call(func, *args, **kw)`` (from the
:obj:`~pytest_bluezenv.Call` plugin, loaded by default) runs a function
inside the VM and returns its result.

.. code-block:: python

   from pytest_bluezenv import Bluetoothd, host_config

   @host_config([Bluetoothd(conf="[General]\nExperimental = true")])
   def test_adv_monitor_crash(hosts):
       result = hosts[0].call(check_adv_monitor_crash)

   def check_adv_monitor_crash():
       # This runs on the VM side
       ...
       return 123

Pass ``sync=False`` to start the call without waiting. ``.wait()``
collects the result later. The function must be importable on the VM.
Arguments and return values must be picklable.

.. code-block:: python

   from pytest_bluezenv import Call, host_config

   @host_config([])
   def test_parallel(hosts):
       pending = hosts[0].call(slow_function, 1, 2, sync=False)
       ...                                # do something else meanwhile
       result = pending.wait()

Controlling a process
---------------------

:obj:`~pytest_bluezenv.Pexpect` drives a command-line program on a VM host
and reads its output with ``expect``.  ``spawn()`` returns a
:obj:`~pytest_bluezenv.Pexpect.CtlProxy` for the process. The handle can
also be used as a context manager.

.. code-block:: python

   from pytest_bluezenv import Pexpect, find_exe, host_config

   @host_config([Pexpect()])
   def test_btmgmt(hosts):
       btmgmt = hosts[0].pexpect.spawn([find_exe("tools", "btmgmt")])
       btmgmt.send("info\n")
       btmgmt.expect("hci0")
       btmgmt.close()

.. code-block:: python

   from pytest_bluezenv import Pexpect, find_exe, host_config

   @host_config([Pexpect()])
   def test_btmgmt_with(hosts):
       with hosts[0].pexpect.spawn([find_exe("tools", "btmgmt")]) as btmgmt:
           btmgmt.send("info\n")
           btmgmt.expect("hci0")

``expect_all()`` waits for several patterns in any order. It returns
the matched groups of each pattern in the order the patterns were
given. When ``timeout`` is set, it is one deadline shared by all the
patterns, so awaiting many patterns does not multiply the timeout.

.. code-block:: python

   @host_config([Pexpect()])
   def test_btmgmt_all(hosts):
       btmgmt = hosts[0].pexpect.spawn([find_exe("tools", "btmgmt")])
       btmgmt.send("info\n")
       groups = btmgmt.expect_all([r"(\w+): (yes|no)", "hci0"], timeout=30)

.. code-block:: python

   @host_config([Pexpect()])
   def test_btmgmt_reject(hosts):
       btmgmt = hosts[0].pexpect.spawn([find_exe("tools", "btmgmt")])
       btmgmt.send("info\n")
       btmgmt.expect("hci0", reject=[r"(Failed to [^\n]*)"])

:obj:`~pytest_bluezenv.Bluetoothctl` plugin wraps ``bluetoothctl`` with
the same ``send`` / ``expect`` interface.

Host proxies and RPC
--------------------

``host.<name>`` is a :obj:`~pytest_bluezenv.PluginProxy` for a plugin,
if the plugin :obj:`~pytest_bluezenv.HostPlugin.value`. Any public
non-lifecycle method on that proxy becomes an RPC call to the VM-host
plugin. Arguments, results, and exceptions cross the RPC connection by
pickling.

.. code-block:: python

   from pytest_bluezenv import Bluetoothctl, host_config

   @host_config([Bluetoothctl()])
   def test_rpc(hosts):
       host0, = hosts
       # host.bluetoothctl is a PluginProxy: send is an RPC call
       host0.bluetoothctl.send("show\n")

A plugin that sets :obj:`~pytest_bluezenv.HostPlugin.value`
appears as that value instead.  Two built-in
plugins do this with their own proxies.
:obj:`~pytest_bluezenv.Call` exposes a :obj:`~pytest_bluezenv.Call.Proxy`
as ``host.call``.
:obj:`~pytest_bluezenv.Pexpect` exposes a
:obj:`~pytest_bluezenv.Pexpect.Proxy` as ``host.pexpect``.

.. code-block:: python

   from pytest_bluezenv import Call, Pexpect, find_exe, host_config

   @host_config([Pexpect()])
   def test_proxies(hosts):
       pending = hosts[0].call(slow_function, 1, 2, sync=False)
       ...                                # do something else meanwhile
       result = pending.wait()

       with hosts[0].pexpect.spawn([find_exe("tools", "btmgmt")]) as btmgmt:
           btmgmt.send("info\n")
           btmgmt.expect("hci0")

Reusing configuration and machines
----------------------------------

A configuration can be shared by several tests. With ``reuse=True``,
userspace programs such as ``bluetoothd`` remain running between tests
using the same configuration. This is useful when tests do not perturb
the host state.

.. code-block:: python

   config = host_config([Bluetoothd()], reuse=True)

   @config
   def test_one(hosts):
       ...

   @config
   def test_two(hosts):
       ...              # same bluetoothd as test_one

:obj:`~pytest_bluezenv.parametrized_host_config` runs one test over
several configurations, like ``pytest.mark.parametrize``:

.. code-block:: python

   from pytest_bluezenv import Bluetoothd, parametrized_host_config

   @parametrized_host_config(
       [
           [[Bluetoothd()]],
           [[Bluetoothd(conf="[General]\nControllerMode = le")]],
       ],
       ids=["bredr", "le"],
   )
   def test_pairing_modes(hosts):
       ...

Tests and their fixtures can request the resolved configuration through
the :obj:`~pytest_bluezenv.host_setup` and
:obj:`~pytest_bluezenv.vm_setup` fixtures. Their keys are documented
with the fixtures.

.. code-block:: python

   def test_broadcast(hosts, vm_setup):
       if vm_setup["num_hosts"] < 3:
           pytest.skip("needs three VM hosts")

Choosing a controller
---------------------

Tests use the emulated ``btvirt`` controller, shared between the
VM hosts, unless they ask otherwise. Request a real controller with
``hw=True``. Omit a controller entirely with ``controller=False``.

.. code-block:: python

   from pytest_bluezenv import Bluetoothd, host_config

   @host_config([Bluetoothd()], hw=True)          # needs --usb/--pcie
   def test_real_radio(hosts): ...

   @host_config([], controller=False)             # no controller at all
   def test_no_controller(hosts): ...

Real controllers come from ``--usb`` / ``--pcie`` and are selected
automatically otherwise. See :doc:`running_tests`. Tests start with
the controller **powered off**. ``Bluetoothd`` turns it on,
but tests that run without it must power it on themselves, e.g. ``btmgmt
power on``.

Writing a host plugin
---------------------

Host plugins run code on the VM side.  A plugin is a subclass of
:obj:`~pytest_bluezenv.HostPlugin`. Its non-lifecycle methods are callable
over RPC.  ``bluetoothctl`` is implemented as:

.. code-block:: python

   import logging
   import signal
   import pexpect
   import pytest

   from pytest_bluezenv import HostPlugin, Bluetoothd, find_exe, LogStream, default_timeout

   class Bluetoothctl(HostPlugin):
       name = "bluetoothctl"
       depends = [Bluetoothd()]          # load bluetoothd first

       def presetup(self, config):       # upper tester, before VM starts
           try:
               self.exe = find_exe("client", "bluetoothctl")
           except FileNotFoundError as exc:
               pytest.skip(reason=f"Bluetoothctl: {exc!r}")

       def setup(self, impl):            # VM side
           self.log = logging.getLogger(self.name)
           self.log_stream = LogStream(self.name)
           self.ctl = pexpect.popen_spawn.PopenSpawn(
               self.exe, logfile=self.log_stream.stream,
               timeout=default_timeout(),
           )

       def teardown(self):               # VM side
           self.ctl.sendeof()
           self.ctl.kill(signal.SIGTERM)

       def expect(self, *a, **kw):       # RPC-callable
           ret = self.ctl.expect(*a, **kw)
           return ret, self.ctl.match.groups()

       def send(self, *a, **kw):         # RPC-callable
           return self.ctl.send(*a, **kw)

The hooks run on the upper-tester and VM-host sides as follows:

``__init__``
    Upper-tester side, at collection time. Store configuration on ``self``
    only. The object must be picklable so it can be sent to the VM.

``presetup(config)``
    Upper-tester side, during setup, before the VM starts. Use
    ``pytest.skip()`` here to skip the test when a requirement is
    missing.

``setup(impl)`` / ``teardown()``
    VM-host lower tester side, at the start and end of the test.

Any other method is RPC-callable from the test. Its return value is
pickled back. The plugin appears as ``host.<name>``. Set the
:obj:`~pytest_bluezenv.HostPlugin.value` attribute to control what the
upper tester sees instead of a plain RPC proxy
(see :obj:`~pytest_bluezenv.HostPlugin`).

Pass plugins to :obj:`~pytest_bluezenv.host_config` to load them.
Every host also gets a
few defaults automatically: :obj:`~pytest_bluezenv.Call` and
:obj:`~pytest_bluezenv.Rcvbuf`, plus :obj:`~pytest_bluezenv.Bdaddr`
(needed for a controller) unless ``controller=False``.

Asynchronous D-Bus events
-------------------------

Driving BlueZ over D-Bus is asynchronous. Method calls reply later and
the daemon can call back into the lower
tester. :obj:`~pytest_bluezenv.Agent` turns this into an ``expect`` /
``reply`` pattern.  ``expect`` returns an
:obj:`~pytest_bluezenv.Event` whose kind is the D-Bus method name, and
whose attributes are the method arguments.

.. code-block:: python

   from pytest_bluezenv import Agent, host_config, wait_until

   @host_config([Agent()], [Agent()])
   def test_pair(hosts):
       host0, host1 = hosts

       host0.agent.adapter_method("StartDiscovery")
       host0.agent.expect("org.bluez.Adapter1.StartDiscovery:reply")
       host1.agent.adapter_set("Discoverable", True)
       host1.agent.adapter_set("Pairable", True)

       wait_until(host0.agent.has_device, host1.bdaddr)
       host0.agent.device_method(host1.bdaddr, "Pair")

       ev0 = host0.agent.expect("org.bluez.Agent1.RequestConfirmation")
       ev1 = host1.agent.expect("org.bluez.Agent1.RequestConfirmation")
       assert ev0.passkey == ev1.passkey

       host0.agent.reply()
       host1.agent.reply()
       host0.agent.expect("org.bluez.Device1.Pair:reply")

Outgoing method calls produce events named
``<interface>.<method>:reply`` and ``...:error``. A ``:reply`` event
exposes the method return values as ``event.values``, and an ``:error``
event exposes the exception as ``event.error``. Incoming calls produce
events named after the method, with the arguments as attributes, and are
answered with ``reply()`` or ``reply_error()``.

The same pattern is available for your own plugins through
:obj:`~pytest_bluezenv.EventPluginMixin` and
:obj:`~pytest_bluezenv.dbus_service_event_method`. Subclass using the mixin,
call its ``setup`` from the plugin's ``setup``, and declare service
methods that push :obj:`~pytest_bluezenv.Event` instances:

.. code-block:: python

   import dbus.service

   from pytest_bluezenv import (
       DbusSystem,
       EventPluginMixin,
       HostPlugin,
       host_config,
       dbus_service_event_method,
       mainloop_assert,
       get_dbus,
   )

   class MyService(dbus.service.Object):
       @mainloop_assert
       def __init__(self, bus, path, events):
           self.events = events
           super().__init__(bus, path)

       DoWork = dbus_service_event_method(
           "org.example.Service1",
           "DoWork",
           ("arg",),
           in_signature="s",
           out_signature="s",
           sync=False,
       )

   class MyPlugin(HostPlugin, EventPluginMixin):
       name = "myplugin"
       depends = [DbusSystem()]

       @mainloop_wrap
       def setup(self, impl):
           EventPluginMixin.setup(self, impl)
           bus = get_dbus()
           self.service = MyService(bus, "/service", self.events)

For an asynchronous D-Bus service method, another client can invoke
``DoWork`` on the private bus. Answer the pending call from the upper
tester:

.. code-block:: python

   @host_config([MyPlugin()])
   def test_reply(hosts):
       event = hosts[0].myplugin.expect("org.example.Service1.DoWork")
       hosts[0].myplugin.reply("return value")

The GLib main loop
------------------

Some host plugins use ``dbus-python``, which is not safe to call from
several threads at once. On the VM side there is a single GLib main
loop for this. Any method that touches D-Bus must run on it. Decorate
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

:obj:`~pytest_bluezenv.Agent` and the built-in D-Bus plugins already use
the main loop. A custom plugin that uses D-Bus directly needs the same
arrangement.


LE advertising
--------------

In LE-only mode ``bluetoothd`` does not advertise the host by itself.
Add a :obj:`~pytest_bluezenv.LeAdvertiser` on the advertising VM host to
make it discoverable and connectable by a peer:

.. code-block:: python

   from pytest_bluezenv import Bluetoothd, LeAdvertiser, host_config

   LE_CONF = "[General]\nControllerMode = le\n"

   @host_config(
       [Bluetoothd(conf=LE_CONF)],
       [Bluetoothd(conf=LE_CONF), LeAdvertiser(service_uuids=["180d"])],
   )
   def test_le_service(hosts):
       client, server = hosts


Agent device properties
-----------------------

The :obj:`~pytest_bluezenv.Agent` plugin provides synchronous property
access for both the local adapter and a discovered remote device. Device
operations take the remote device address, which is resolved to its
current BlueZ object path:

.. code-block:: python

   from pytest_bluezenv import Agent, host_config

   @host_config([Agent()], [Agent()])
   def test_device_trust(hosts):
       host = hosts[0]
       peer = hosts[1]
       host.agent.device_set(peer.bdaddr, "Trusted", True)
       assert host.agent.device_get(peer.bdaddr, "Trusted")

Use :obj:`~pytest_bluezenv.Agent.adapter_get` and
:obj:`~pytest_bluezenv.Agent.adapter_set` for ``org.bluez.Adapter1``
properties, and :obj:`~pytest_bluezenv.Agent.device_get` and
:obj:`~pytest_bluezenv.Agent.device_set` for ``org.bluez.Device1``
properties. Use :obj:`~pytest_bluezenv.Agent.adapter_method` or
:obj:`~pytest_bluezenv.Agent.device_method` when the D-Bus operation has
an async reply event that should be handled with ``host.agent.expect()``.
