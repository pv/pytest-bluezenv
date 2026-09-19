---
name: testing
description: Guidance for working on tests
---

# Testing

Agents writing or changing tests must follow this guidance.

The purpose of a test is to catch a regression in behaviour that the
project promises to its users. A failing test must mean something real
is broken.

## Running tests

- `python3 -mpytest src/pytest_bluezenv -vv` to run basic tests
- `python3 -mpytest src/pytest_bluezenv --kernel /pathto/bzImage --bluez-build-dir /pathto/bluez-build -vv` to run VM tests.
  `--kernel` takes a suitable Linux kernel bzImage or kernel source
  tree. `--bluez-build-dir` points to a built BlueZ tree that provides
  the binaries the guests run.
  If you cannot find these, ask user to provide it.
- Pytest makes sure that the code in `src/pytest_bluezenv` is used in the testing.
  Usually you do not need to know how this works.

## Pytest usage

You need to read pytest API documentation to understand:

- https://docs.pytest.org/en/stable/reference/index.html
- https://docs.pytest.org/en/stable/reference/reference.html

## Pytester pitfalls

- Load the plugin in the inner session with
  `-p pytest_bluezenv`.
- `pytester.runpytest` runs the inner session in the same interpreter
  by default. A monkeypatch of a pytest-bluezenv module leaks to the
  outer session. Restore such state from the outer test (an outer
  `monkeypatch` or a `yield` fixture), not from the inner conftest:
  inner `pytest_unconfigure` does not run in a successful inner run.
- A test decorated by `host_config` or `parametrized_host_config` must
  request both the `host_setup` and `vm_setup` fixtures. Indirect
  parametrization of a fixture the test does not use fails collection.
- Inner run output is in dot format. Pass `-v` when a test asserts on
  the order or identity of executed tests.
- pytest-xdist and pytest-randomly may or may not be installed. Tests
  must pass either way. Use `pytester.makeconftest` to register a stub
  plugin to simulate presence and `-p no:<name>` in the inner session to
  simulate absence; never assume either way.
- `assert` statements executed in a separate thread do not fail the
  test. Collect thread results and assert on them in the test body.
- Module state survives an in-process pytester session. Some plugin
  objects, such as the default host plugins, are created at import
  time and configured by later `presetup` calls. Do not write tests
  whose result depends on, or mutates, such shared instances.

## Test the public API

- Test primarily through the public, documented interface: the API
  objects, the pytest fixtures, the command-line options, and the ini
  configuration.
- Drive the plugin as a user does. Register it and resolve fixtures
  through `pytester` instead of calling into private functions.
- Test an internal helper only if it carries substantial logic that no
  public path exercises. Never test an internal helper just to gain
  coverage.

## Test behaviour, not implementation

- Assert on outcomes that must hold regardless of how things are
  implemented: return values, raised exceptions, observable side
  effects, fixture resolution.
- Do not assert on private attributes, internal call sequences, wire
  message shapes, or how often an internal function was called. Such
  tests break under refactors that change no behaviour.
- Stub only at true external boundaries such as QEMU, D-Bus, and the
  network. Do not stub pytest-bluezenv internals to verify how it works
  internally.
- A test that must be edited whenever behaviour-preserving code is
  restructured is coupled to the implementation. Rewrite it against
  behaviour.

## Potential bugs

- Do not believe current implementation is necessarily correct.
  Especially so if code, documentation, code comments, or common sense
  conflict.
- Raise any pre-existing issues you find with the user.

## Test what matters

- Do not test trivial things. Skip constructors that only store their
  arguments, trivial pass-throughs, and anything a type checker already
  guarantees.
- Cover scenarios where a plausible bug could hide: defaults versus
  explicit values, option interactions, error paths, edge cases.
- Every test must be able to fail on a plausible defect. If no sensible
  bug can ever make it fail, delete it.

## Test case design

- Assert one behaviour per test. Name the test after the behaviour, not
  after the function under test.
- Keep a test minimal and readable: arrange, act, assert.
- Use pytest facilities: fixtures, `parametrize`, `tmp_path`,
  `monkeypatch`, `pytest.raises`.
- Use `pytester` for plugin-level behaviour. It runs the plugin in an
  isolated session and needs neither QEMU nor a kernel image.
- Tests must be deterministic, isolated, and order-independent. Do not
  sleep for a fixed duration.
- In a VM test, each host runs its own kernel: values such as process
  IDs are not comparable across hosts.  Compare such values only
  within one host, across its test instances.

## VM-using test

- Do not add VM-using tests if there is a good alternative way.
  VM-using tests are for cases that are difficult to test otherwise.
- Avoid increasing the number of VM boots required.
- It is allowed that a single VM-using test tests different aspects of
  the behaviour of the lower tester, if this avoids spawning a new VM
  instance.
- Assert that a pytest-bluezenv mechanism works. Do not assert that
  the Bluetooth protocol is correct. BlueZ and the kernel are only the
  substrate.
- Skip when prerequisites such as the kernel image are missing, and
  assert exact outcomes when the VM does run.
- On failure, VM-using tests must produce readable output that can
  be used to debug the issue.

## Regression tests

- For every bug fix, first add a test that reproduces the bug. It must
  fail before the fix and pass after it. Keep it as a guard.

## Verifying

- Run `python3 -mpytest src/pytest_bluezenv` and require it to pass.
- Run the VM-dependent tests with `--kernel` and `--bluez-build-dir`
  when a kernel and a BlueZ build tree are available.
- Test failures and warnings must be fixed.
- VM-dependent tests skip when no kernel image is available. A missing
  image must lead to a skip, never to a failure.
