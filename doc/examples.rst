Examples
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
