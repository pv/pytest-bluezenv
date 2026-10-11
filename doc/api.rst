API
===

VM configuration
----------------

.. autosummary::
   :toctree: api

   ~pytest_bluezenv.host_config
   ~pytest_bluezenv.parametrized_host_config

Fixtures
--------

.. autosummary::
   :toctree: api

   ~pytest_bluezenv.hosts
   ~pytest_bluezenv.hosts_once
   ~pytest_bluezenv.bumble_env

Host plugins
------------

.. autosummary::
   :toctree: api

   ~pytest_bluezenv.HostPlugin
   ~pytest_bluezenv.Agent
   ~pytest_bluezenv.Bdaddr
   ~pytest_bluezenv.Bluetoothctl
   ~pytest_bluezenv.Bluetoothd
   ~pytest_bluezenv.Btmon
   ~pytest_bluezenv.Call
   ~pytest_bluezenv.DbusSession
   ~pytest_bluezenv.DbusSystem
   ~pytest_bluezenv.LeAdvertiser
   ~pytest_bluezenv.Obexd
   ~pytest_bluezenv.Pexpect
   ~pytest_bluezenv.Rcvbuf

Controllers
-----------

Sources of Bluetooth controllers for the VM hosts.  A controller
specification is selected with the ``controller`` argument of
:obj:`~pytest_bluezenv.host_config`.

.. autosummary::
   :toctree: api

   ~pytest_bluezenv.ControllerBase
   ~pytest_bluezenv.ControllerBackend
   ~pytest_bluezenv.BtvirtController
   ~pytest_bluezenv.HwController

Bumble emulated controllers
---------------------------

Controller specifications for
:obj:`~pytest_bluezenv.host_config` and the test-side access to the
bumble objects.

.. autosummary::
   :toctree: api

   ~pytest_bluezenv.BumbleController
   ~pytest_bluezenv.BumbleDevice
   ~pytest_bluezenv.BumbleEnv

Exceptions
----------

.. autosummary::
   :toctree: api

   ~pytest_bluezenv.RemoteError
   ~pytest_bluezenv.RemoteTimeoutError

Utilities
---------

.. autosummary::
   :toctree: api

   ~pytest_bluezenv.LogStream
   ~pytest_bluezenv.bluez_src_dir
   ~pytest_bluezenv.default_timeout
   ~pytest_bluezenv.get_bdaddr
   ~pytest_bluezenv.get_dbus
   ~pytest_bluezenv.find_exe
   ~pytest_bluezenv.mainloop_assert
   ~pytest_bluezenv.mainloop_invoke
   ~pytest_bluezenv.mainloop_wrap
   ~pytest_bluezenv.quoted
   ~pytest_bluezenv.run
   ~pytest_bluezenv.wait_until
   ~pytest_bluezenv.CoredumpWarning
   ~pytest_bluezenv.KernelBugWarning
   ~pytest_bluezenv.SanitizerWarning

.. autosummary::
   :toctree: api

   ~pytest_bluezenv.Event
   ~pytest_bluezenv.EventPluginMixin
   ~pytest_bluezenv.dbus_service_event_method


Host proxies
------------

The upper-tester objects used to access VM-host plugins. ``host.<name>``
is a :obj:`~pytest_bluezenv.PluginProxy` unless a plugin exposes a value
through :obj:`~pytest_bluezenv.HostPlugin.value`.

.. autosummary::
   :toctree: api

   ~pytest_bluezenv.HostProxy
   ~pytest_bluezenv.PluginProxy

Internals
---------

Internal fixtures, used by :obj:`~pytest_bluezenv.host_config`.

.. autosummary::
   :toctree: api

   ~pytest_bluezenv.kernel
   ~pytest_bluezenv.vm
   ~pytest_bluezenv.vm_once
   ~pytest_bluezenv.host_setup
   ~pytest_bluezenv.vm_setup

.. toctree::
   :hidden:

   api-internal
