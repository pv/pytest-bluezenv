# Design: bumble integration

Feature branch: `bumble-integration` (base `opencode/main`).

## Status

M1-M3 implemented: repo tests (`tests/test_bumble.py`) and
documentation done, VM-tested. The controller plumbing was
generalized into `controller.py` (see Controller backends below).

## Controller backends

`src/pytest_bluezenv/controller.py` hosts the shared interface.
`ControllerBase` subclasses are the decoration-time specs kept in
`vm_setup["controller"]`; they are shared and stateless. The
`backend` property names the `ControllerBackend` subclass that
`Environment.start()` constructs per environment; constructor
arguments are `(controller, path, num_hosts, timeout=None,
debug=False)` and the constructor starts the service.
`ControllerBackend` exposes `runner_args`, `stop()`,
`check_errors()`, `start_devices()`, `stop_devices()` and
`cleanup(path)`. Built-ins: `BtvirtController` (default, id "") and
`HwController` (passthrough). `BumbleController` lives in `_bumble.py`
and its runtime is the backend. `Environment` holds `self.controller`
and `self.controller_backend`; it no longer references btvirt, hw
probing or bumble directly. `host_config` still accepts `True`/`False`
for `controller`, mapped at decoration to `BtvirtController()`/`None`.

## M1 spike findings (verified)

- The guest kernel boots with the bumble-served controller and
  `bluetoothd` starts and runs normally; the assigned public address is
  reported by the guest (`Controller 00:AA:02:...`).
- HCI and mgmt paths are byte-correct (`btmon`: `LE Extended
  Advertising Report` -> `MGMT Device Found`).
- bluetoothd only creates a device object when the advertising data
  carries LE General Discoverable Flags
  (`adapter.c:device_is_discoverable()`); name-only advertising is
  silently dropped. Therefore a `BumbleDevice` with default
  `advertising=True` and no explicit `advertising_data` gets
  `Flags(LE General Discoverable | BR/EDR Not Supported)` prepended to
  its advertising data automatically.
- `Device.disconnect()` requires a reason argument.
- `DeviceConfiguration` `gatt_services` config parsing is rigid
  (uppercase properties, mandatory `permissions`, no values). Dynamic
  GATT content is done with the `setup` callback using bumble API
  (`device.add_service(...)`), which is what the docs show.

## Goal

Integrate with the `bumble` Python Bluetooth stack
(<https://pypi.org/project/bumble/>). Two capabilities:

1. `host_config(controller=BumbleController())` routes emulated HCI
   controllers provided by bumble to the VM host kernels, as an
   alternative to `btvirt`.
2. Tests declare emulated remote hosts (e.g. bumble GATT servers) on
   the same virtual air link, in the same `test_*.py` files as regular
   pytest-bluezenv tests. The topology is declared outside the test
   code. A custom bumble `Controller` subclass or factory is the Python
   alternative to BlueZ `btdev` emulation.

## Mechanism (verified)

- The guest kernel attaches its controller with line discipline `N_HCI`
  and protocol `HCI_UART_H4` (`subprojects/bluez/tools/test-runner.c:1221`)
  to the chardev created from the `test-runner` `-u <socket>` option.
  The stream is plain H4-framed HCI. bumble speaks exactly this between
  a host and `bumble.controller.Controller` (`bumble/controller.py:423`,
  `host_source`/`host_sink`). A bumble `Controller` served on a unix
  socket is therefore a drop-in replacement for the `btvirt`
  `bt-server-bredrle` socket (`env.py` `_start_btvirt`).
- Per-host unix sockets use `bumble.transport.unix.open_unix_server_transport`
  (`bumble/transport/unix.py:60`). It keeps listening across
  disconnects (sink re-attaches on reconnect; packets dropped while no
  client). The socket file exists as soon as the server is created, so
  `utils.wait_files()` readiness works as with `btvirt`.
- Virtual air: one `bumble.link.LocalLink` per `Environment`. VM-side
  `Controller` instances and emulated device `Controller` instances
  attach to it. Routing is by address; advertising is broadcast to all
  other controllers (`bumble/link.py`). `Controller` is a full link
  layer emulator (LE ext/periodic adv, classic LMP, connections).
  bumble documents the same controller-for-BlueZ-host pattern over
  `/dev/vhci`.
- Event loop: bumble is asyncio and objects are loop-affine
  (constructed under `get_running_loop()`). The upper tester is
  synchronous and its blocking RPC must overlap with bumble activity
  (e.g. the emulated controller must answer while
  `bluetoothctl.expect()` blocks). pytest-asyncio cannot drive a loop
  in background, so the plugin owns a session-wide daemon thread
  running one asyncio loop. All bumble objects for all environments
  live on that loop.

## Public API

```python
from pytest_bluezenv import host_config, Bluetoothd, Bluetoothctl
from pytest_bluezenv import BumbleController, BumbleDevice

@host_config(
    [Bluetoothd(), Bluetoothctl()],
    controller=BumbleController(
        controllers=None,   # None | callable | sequence[callable | None]
        devices={           # declarative emulated peers, host-plugin lifetime
            "sensor": {     # plain bumble device-config dict
                "name": "BumbleSensor",
                "address": "F1:23:00:00:00:01",
                "gatt_services": [ ... ],   # bumble's own declarative format
            },
            "led": BumbleDevice(
                config={ ... },
                power_on=True,        # default True
                advertising=True,     # default True: start_advertising(auto_restart)
                setup=attach_char,    # module-level callable, run on bumble loop
            ),
        },
    ),
)
def test_gatt(hosts, bumble_env):
    host0, = hosts
    sensor = bumble_env.devices["sensor"]   # bumble.device.Device, on the air
    host0.bluetoothctl.send("scan on\n")
    host0.bluetoothctl.expect("BumbleSensor")
```

### `BumbleController`

Declarative spec passed as `host_config(controller=)` /
`parametrized_host_config(controller=)`. One instance per
configuration; applies to the whole `Environment` (all hosts share one
air link), like `btvirt`. Picklable: plain data and module-level
callable references (lambdas unsupported, documented).

- `controllers=None`: per-VM-host controller factory.
  - `None`: stock `bumble.controller.Controller` for every host.
  - single callable: used for every host.
  - sequence: one entry per VM host, matched positionally with the
    `host_config` host declarations; `None` entry means stock
    `Controller` for that host. Length validated against `num_hosts`
    in `parametrized_host_config` at decoration time.
- Factory contract equals the bumble `Controller.__init__` signature,
  so any subclass is itself a valid factory:
  `factory(name=, host_source=, host_sink=, link=, public_address=)`.
- `devices`: mapping name -> `BumbleDevice` or plain bumble
  device-config dict (auto-wrapped). `BumbleDevice.config` is passed
  verbatim to `bumble.device.DeviceConfiguration`. pytest-bluezenv
  control keys live on `BumbleDevice`, not in the bumble config dict:
  `power_on`, `advertising`, `setup`.
- `hw=True` together with a controller spec raises `ValueError`.

### `bumble_env` fixture

Function scope. Bridges the synchronous upper tester onto the bumble
loop. Exposes bumble objects; there is no additional custom API.

- `run(awaitable, timeout=None)`: run a coroutine/future on the bumble
  loop, block until done, return the result or re-raise.
- `devices`: mapping name -> `bumble.device.Device` created from the
  spec (already powered on / advertising per spec).
- `controllers`: mapping host index -> `bumble.controller.Controller`
  serving that VM host (`.public_address` is the VM bdaddr).
- `link`: the `bumble.link.LocalLink` of the environment.
- `loop`: the asyncio loop object, for power users.

Device customization during tests is done with plain bumble API under
`run()` (attributes may be read directly). `bumble_env.controllers[i]`
supports test-driven injection (e.g. `send_hci_packet`) and per-opcode
handler overrides (`getattr(self, f"on_{command.name.lower()}")`,
`bumble/controller.py:543`).

### Lifecycle and isolation

- Bumble loop thread: session-wide daemon thread, started lazily on
  first use.
- `Environment` start: creates `LocalLink` and per-host
  unix-server `Controller` instances (`BumbleRuntime`), before the
  runners are launched; per-host sockets named `bumble-<idx>` under
  the environment tmpdir.
- Declared devices: created when the test hosts are set up
  (`_hosts_impl()`, idempotent: existing devices are kept) and
  destroyed by `Environment.close_hosts()` (disconnect + remove from
  `LocalLink`).  Their lifetime follows the test host plugins: torn
  down after every test with `reuse=False`, kept until the reuse
  group changes with `reuse=True`.  Controller instances live with
  the `Environment`.
- Missing `bumble` package: tests using the spec are skipped
  (`importlib.util.find_spec` check in `_vm_impl`, guarded for Python
  < 3.10 where bumble cannot even be imported).

### Addresses

VM-side controllers get deterministic distinct public addresses
derived from `ENV_INDEX` and host index, in a pattern clearly
separate from the `btvirt` convention (`00:AA:01:...`). Emulated peer
addresses come from their declared configs.

## Code changes

1. New `src/pytest_bluezenv/_bumble.py` (private module name, so it
   cannot shadow or collide with the `bumble` package; public classes
   are re-exported at the package top level) — no top-level `import
   bumble` (lazy imports inside functions; module import must not
   require bumble). Py3.8-compatible parent-side syntax.
   - loop thread management (`_Loop` singleton; exception handler
     recording failures),
   - `BumbleController` spec (with `name`, `factories()`, and
     `parametrize_id()`),
   - `BumbleDevice` (config / power_on / advertising / setup),
   - `_BumbleRuntime` (per `Environment`: link, unix servers, VM
     controllers, peer devices, logging, failure capture),
   - `BumbleEnv` facade (run/devices/controllers/link/loop).
2. `host_plugins.py`: `host_config`/`parametrized_host_config` accept
   `controller: bool | BumbleController`. The spec survives into the
   `vm_setup` dict (drop `bool()` coercion). Parametrize ids: `-noc`
   when False, `-bumble` (plus factory names when not default) so
   differing specs never share a VM. Decorate-time validation:
   `hw` conflict; `controllers` sequence length vs host count.
3. `env.py`: `Environment(controller=...)` accepts the spec;
   `start()` gains a bumble branch returning per-host
   `["-u<socket>"]` argv lists; `self.bumble` attribute; `stop()`
   destroys the runtime and unlinks `bumble-*` sockets before rmdir;
   `check_job_errors()` reports bumble runtime/loop failures.
4. `plugin.py`: `bumble_env` fixture resolving the active environment
   (`vm` or `vm_once` via `request.getfixturevalue`); skip in
   `_vm_impl` when bumble is not importable; `_hosts_impl()` starts
   the peer devices and `Environment.close_hosts()` stops them.
5. Packaging: `pyproject.toml` extra
   `bumble = ["bumble; python_version >= '3.10'"]`; source and test
   file lists in `meson.build`.

## Testing

`tests/test_bumble.py`:

- pytester unit tests (no QEMU): spec flows into `vm_setup` and ids;
  `hw` conflict error; `controllers` length validation; `bumble_env`
  requested without bumble configuration fails with a clear message.
- Kernel-free runtime test: `BumbleRuntime` on a tmpdir; a real bumble
  client transport + `Host`/`Device` connects to a per-host socket and
  performs a GATT exchange over the bridge. Validates the socket /
  `Controller` plumbing without a VM.
- Functional tests (auto-skip without kernel/QEMU, as in the existing
  suite):
  - declarative device advertising is found by the VM
    (`bluetoothctl scan`), and GATT-read from the VM;
  - bumble side connects to a discoverable VM host and reads GAP
    device name (bidirectionality);
  - custom `controllers=` factory/ subclass behavior observed from the
    guest (e.g. overridden `Read Local Version Information`);
  - device lifecycle: declared devices recreated for the next test on
    a shared VM with `reuse=False`.

## Documentation

- `doc/writing_tests.rst`: new section with runnable `.. testcode::`
  examples: declarative device + scan; custom controller factory.
  Explain the `bumble_env` loop/`run()` rules and fixture/module name
  shadowing.
- `doc/overview.rst`: controllers section mention.
- `doc/api.rst`: `BumbleController`, `BumbleDevice`, `BumbleEnv`,
  `bumble_env`.
- `doc/requirements.rst`: bumble extra; Python >= 3.10 note.
- `CHANGES.rst`; short README mention.

## Milestones

- M1 spike (throwaway script under ~/tmp): bumble unix-server +
  `Controller`, one VM via patched socket path; confirm `btmgmt` power
  on, scanning, addresses work against the guest kernel before
  building further.
- M2 plumbing: spec class, parametrize/vm_setup/env wiring, runtime,
  skip logic, addresses.
- M3 facade + fixture + declarative devices.
- M4 tests.
- M5 docs + packaging; full pytest suite, `black --check`, clean Sphinx
  build incl. doctest; push branch.

## Risks

- Guest kernel/BlueZ expectations vs bumble `Controller` feature set:
  de-risked by M1; adjust glue or controller options if needed.
- One loop thread serves all HCI traffic of an environment: acceptable
  for tests (`btvirt` is similarly single-threaded).
- `tests/test_host_config.py` asserts `vm_setup` verbatim: the bool
  path stays byte-identical; new spec path gets its own tests.
