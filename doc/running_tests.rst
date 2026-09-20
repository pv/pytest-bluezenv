Running tests
=============

Running a suite
---------------

.. code-block:: console

   $ python3 -mpytest --kernel=/path/to/bzImage

   $ export FUNCTIONAL_TESTING_KERNEL=/path/to/bzImage
   $ python3 -mpytest

Live logging
------------

.. code-block:: console

   $ python3 -mpytest --log-cli-level=0

Specific loggers can be selected or excluded with ``--log-filter``:

.. code-block:: console

   $ python3 -mpytest --log-cli-level=0 --log-filter=rpc,host
   $ python3 -mpytest --log-cli-level=0 --log-filter=*.bluetoothctl
   $ python3 -mpytest --log-cli-level=0 --log-filter=-host
   $ python3 -mpytest --log-cli-level=0 --log-filter=host,-host.*.1

Show slow RPC calls
-------------------

.. code-block:: console

   $ python3 -mpytest --bluezenv-progress=on

A slow host RPC call is shown on the line below the test:

.. code-block:: text

   test_bluetoothd.py::test_read_feature                WAITING
   host.0.0: bluetoothd.call("request", timeout=150) [55s, 95s left]

The line is truncated to the terminal width. The default ``auto`` reports
only on a terminal; ``on`` also emits whole lines when there is none.

Selecting tests
---------------

.. code-block:: console

   $ python3 -mpytest test/functional/test_cli_simple.py::test_bluetoothctl_script_show
   $ python3 -mpytest -k test_bluetoothctl_script_show
   $ python3 -mpytest -k 'test_btmgmt or test_bluetoothctl'

Markers can exclude tests:

.. code-block:: console

   $ python3 -mpytest -m "not pipewire"
   $ python3 -mpytest -m "not xfail"

Without the second expression, known failing tests run with their failures
suppressed. The following command reruns failed tests and stops on failure:

.. code-block:: console

   $ python3 -mpytest -x --ff

``--runxfail`` reports failures from known-failing tests:

.. code-block:: console

   $ python3 -mpytest --runxfail -k test_btmgmt_info

USB controllers
---------------

.. code-block:: console

   $ python3 -mpytest --usb=hci0,hci1

   $ export FUNCTIONAL_TESTING_CONTROLLERS=hci0,hci1
   $ python3 -mpytest -vv

USB pass-through does not require root. The process needs permission to
open each device. With ``-vv``, pytest-bluezenv reports missing permissions.
``--force-usb`` selects USB controllers for tests that would otherwise use
``btvirt``:

.. code-block:: console

   $ python3 -mpytest --usb=hci0,hci1 --force-usb

PCIe controllers
----------------

.. code-block:: console

   $ sudo python3 -mpytest --pcie=hci0,hci1

A PCIe controller is bound to ``vfio-pci`` while a VM host uses it and
returned to its original driver afterwards. This requires root, an enabled
IOMMU, and an IOMMU group containing no other device. ``--force-pcie``
selects PCIe controllers for tests that would otherwise use ``btvirt``:

.. code-block:: console

   $ sudo python3 -mpytest --pcie=hci0,hci1 --force-pcie

Parallel execution
------------------

pytest-xdist provides parallel execution:

.. code-block:: console

   $ python3 -mpytest -n auto

``--dist loadgroup`` keeps tests that reuse a VM host on the same worker:

.. code-block:: console

   $ python3 -mpytest -n auto --dist loadgroup

VM-host console
---------------

During a running test, the following command connects to a VM-host serial
console:

.. code-block:: console

   $ python3 -mpytest_bluezenv attach

The test normally needs to be paused, for example with ``--trace``. The
upper tester logs an equivalent command when it starts a VM host:

.. code-block:: console

   TTY: socat /tmp/pytest-bluezenv-q658swgi/pytest-bluezenv-tty-0 STDIO,rawer

The command contains the serial socket path.
