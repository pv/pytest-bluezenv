===============
pytest-bluezenv
===============

**pytest-bluezenv** is a `pytest <https://pytest.org>`_ plugin for
functional testing of the Linux Bluetooth stack and applications.

- Source code: https://github.com/bluez/pytest-bluezenv/
- Documentation: https://bluez.github.io/pytest-bluezenv/
- PyPi: https://pypi.org/project/pytest-bluezenv/

Example
-------

A test declares the VM host topology and host plugins. pytest-bluezenv starts the
VM hosts and exposes them through RPC. By default, their emulated
``btvirt`` controllers provide a virtual air link. USB or PCIe controllers
can be passed through for tests using real radios.

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

The above test declares a VM setup with two Qemu instances, where both hosts
run bluetoothd and start a bluetoothctl process.  The Qemu instances
have `btvirt` virtual BT controllers and can see each other.
