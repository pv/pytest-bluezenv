API
===

VM configuration
----------------

.. autosummary::
   :toctree: api

   pytest_bluezenv.host_config
   pytest_bluezenv.parametrized_host_config

Fixtures
--------

.. autosummary::
   :toctree: api

   pytest_bluezenv.hosts
   pytest_bluezenv.hosts_once

Host plugins
------------

.. autosummary::
   :toctree: api

   pytest_bluezenv.HostPlugin
   pytest_bluezenv.Agent
   pytest_bluezenv.Bdaddr
   pytest_bluezenv.Bluetoothctl
   pytest_bluezenv.Bluetoothd
   pytest_bluezenv.Btmon
   pytest_bluezenv.Call
   pytest_bluezenv.DbusSession
   pytest_bluezenv.DbusSystem
   pytest_bluezenv.Obexd
   pytest_bluezenv.Pexpect
   pytest_bluezenv.Rcvbuf
   pytest_bluezenv.RemoteError

Utilities
---------

.. autosummary::
   :toctree: api

   pytest_bluezenv.LogStream
   pytest_bluezenv.get_bdaddr
   pytest_bluezenv.find_exe
   pytest_bluezenv.mainloop_assert
   pytest_bluezenv.mainloop_invoke
   pytest_bluezenv.mainloop_wrap
   pytest_bluezenv.quoted
   pytest_bluezenv.run
   pytest_bluezenv.wait_until

.. autosummary::
   :toctree: api

   pytest_bluezenv.Event
   pytest_bluezenv.EventPluginMixin
   pytest_bluezenv.dbus_service_event_method


Internals
---------

.. autosummary::
   :toctree: api

   pytest_bluezenv.HostProxy
   pytest_bluezenv.PluginProxy

Internal fixtures:

.. autosummary::
   :toctree: api

   pytest_bluezenv.host_setup
   pytest_bluezenv.kernel
   pytest_bluezenv.usb_indices
   pytest_bluezenv.vm
   pytest_bluezenv.vm_once
   pytest_bluezenv.vm_setup
