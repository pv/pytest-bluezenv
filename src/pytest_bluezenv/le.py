# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""LE advertising host plugin."""

import logging

import dbus
import dbus.exceptions
import dbus.service

from .host_plugins import Bluetoothd
from .env import HostPlugin
from .utils import get_dbus, mainloop_assert, mainloop_wrap, wait_until

__all__ = ["LeAdvertiser"]


BLUEZ_BUS_NAME = "org.bluez"
PROPS_INTERFACE = "org.freedesktop.DBus.Properties"
LE_ADV_INTERFACE = "org.bluez.LEAdvertisement1"
LE_ADV_MANAGER_INTERFACE = "org.bluez.LEAdvertisingManager1"


class _LeAdvertisement(dbus.service.Object):
    """Minimal fixed-property ``org.bluez.LEAdvertisement1`` object."""

    class UnknownProperty(dbus.exceptions.DBusException):
        _dbus_error_name = "org.freedesktop.DBus.Error.UnknownProperty"

    @staticmethod
    def properties(adv_type, service_uuids, discoverable):
        props = dbus.Dictionary(
            {
                "Type": dbus.String(adv_type),
                "ServiceUUIDs": dbus.Array(
                    [dbus.String(uuid) for uuid in service_uuids], signature="s"
                ),
            },
            signature="sv",
        )
        if discoverable:
            props["Discoverable"] = dbus.Boolean(True)
        return props

    @mainloop_assert
    def __init__(self, bus, path, adv_type, service_uuids, discoverable):
        self.adv_path = path
        self.released = False
        self._props = self.properties(adv_type, service_uuids, discoverable)
        super().__init__(bus, path)

    @dbus.service.method(PROPS_INTERFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface == LE_ADV_INTERFACE:
            return self._props
        return dbus.Dictionary({}, signature="sv")

    @dbus.service.method(PROPS_INTERFACE, in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        props = self.GetAll(interface)
        if prop not in props:
            raise self.UnknownProperty(f"No such property {prop} on {interface}")
        return props[prop]

    @dbus.service.signal(PROPS_INTERFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    @dbus.service.method(LE_ADV_INTERFACE, in_signature="", out_signature="")
    def Release(self):
        self.released = True


class LeAdvertiser(HostPlugin):
    """
    Host plugin registering a minimal connectable
    ``org.bluez.LEAdvertisement1`` object on a Bluetooth adapter.

    In LE-only mode ``bluetoothd`` does not advertise the host by
    itself. Load this plugin to make the host discoverable and
    connectable by a peer. Registration completes before the test
    starts. On teardown the advertisement is unregistered and removed
    from the bus.

    Args:
        service_uuids (sequence): service UUIDs to advertise.
        adv_type (str): advertisement type, ``"peripheral"`` or
            ``"broadcast"``.
        index (int): index appended to the advertisement object path
            to keep advertisements of several instances distinct.
        adapter_path (str): D-Bus object path of the adapter to
            advertise on.
        discoverable (bool): whether to set the ``Discoverable``
            advertisement property.
        timeout (float): seconds to wait for the advertisement to be
            registered, or None to use the default timeout.

    Attributes:
        PATH_BASE (str): base D-Bus object path of the advertisements.
            The instance ``index`` is appended to it.

    Example:

        .. code-block:: python

           LE_CONF = "[General]\\nControllerMode = le\\n"

           @host_config(
               [Bluetoothd(conf=LE_CONF)],
               [Bluetoothd(conf=LE_CONF), LeAdvertiser(service_uuids=["180d"])],
           )
           def test_le_connect(hosts):
               client, server = hosts

    """

    name = "le_advertiser"
    depends = [Bluetoothd()]
    PATH_BASE = "/org/bluez/test/advertisement"

    def __init__(
        self,
        service_uuids=(),
        adv_type="peripheral",
        index=0,
        adapter_path="/org/bluez/hci0",
        discoverable=True,
        timeout=None,
    ):
        self.service_uuids = tuple(service_uuids)
        self.adv_type = adv_type
        self.index = index
        self.adapter_path = adapter_path
        self.discoverable = discoverable
        self.timeout = timeout

    def setup(self, impl):
        """
        Register the advertisement with ``bluetoothd`` and wait for it
        to be accepted (VM side).

        Args:
            impl: lower-tester plugin manager.

        Raises:
            TimeoutError: the registration did not complete in time.
        """
        self.log = logging.getLogger(self.name)
        self.registered = False
        self.register_error = None
        self._register()
        try:
            wait_until(lambda: self.registered, timeout=self.timeout)
        except TimeoutError:
            raise TimeoutError(
                f"LE advertisement {self.adv.adv_path} registration timed out"
            ) from None
        if self.register_error is not None:
            raise self.register_error

    @mainloop_wrap
    def _register(self):
        self.bus = get_dbus(private=True)
        self.adv = _LeAdvertisement(
            self.bus,
            f"{self.PATH_BASE}{self.index}",
            self.adv_type,
            self.service_uuids,
            self.discoverable,
        )
        self.manager = dbus.Interface(
            self.bus.get_object(BLUEZ_BUS_NAME, self.adapter_path),
            LE_ADV_MANAGER_INTERFACE,
        )
        self.log.info(f"Register LE advertisement {self.adv.adv_path}")
        self.manager.RegisterAdvertisement(
            self.adv.adv_path,
            dbus.Dictionary({}, signature="sv"),
            reply_handler=self._registered,
            error_handler=self._register_error,
        )

    def _registered(self):
        self.log.info(f"LE advertisement {self.adv.adv_path} registered")
        self.registered = True

    def _register_error(self, err):
        self.log.error(f"LE advertisement {self.adv.adv_path} failed: {err}")
        self.register_error = err
        self.registered = True

    @mainloop_wrap
    def teardown(self):
        """
        Unregister the advertisement and remove it from the bus
        (VM side).
        """
        if not getattr(self, "adv", None):
            return

        self.log.info(f"Unregister LE advertisement {self.adv.adv_path}")
        self.manager.UnregisterAdvertisement(
            self.adv.adv_path,
            reply_handler=lambda: self.log.debug("Unregistered"),
            error_handler=lambda err: self.log.debug(f"Unregister: {err}"),
        )
        self.adv.remove_from_connection()
