pytest-bluezenv
===============

**pytest-bluezenv** is a `pytest <https://pytest.org>`_ plugin for
functional testing of the Linux Bluetooth stack and applications.

- Source code: https://github.com/bluez/pytest-bluezenv/
- Documentation: https://bluez.github.io/pytest-bluezenv/
- PyPi: https://pypi.org/project/pytest-bluezenv/

.. image:: _static/overview.svg
   :alt: A pytest process drives several QEMU VM hosts over RPC; the VMs see each other through a btvirt or real Bluetooth controller.

A test declares the VM host topology and host plugins. pytest-bluezenv starts the
VM hosts and exposes them through RPC. By default, their emulated
``btvirt`` controllers provide a virtual air link. USB or PCIe controllers
can be passed through for tests using real radios.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   overview
   writing_tests
   running_tests
   api
   options
   requirements
   releases
