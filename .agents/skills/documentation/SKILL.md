---
name: documentation
description: Guidance for working on documentation
---

# Documentation

Agents working on documentation must follow this guidance.

## Scope of documentation

Documentation includes docstrings where they reach the built
documentation, i.e. those picked up by the Sphinx API autodoc. Do not
change runtime behaviour if asked to work only on the
documentation. Rebuild from `doc/` with `make clean html`.

Documentation of pytest-bluezenv discusses only pytest-bluezenv and
its features. Background information should not be added unless
necessary for understanding what pytest-bluezenv features do.

## Audience and length

The reader is an expert. Write so it is fast to read.

## Prose style

- Use simple sentence structures. Avoid long explanations. No semicolons.
- Keep paragraphs short. If sentence becomes too long, split it.
- Verify what you add. Check against the code before writing.
- Write in an impersonal, neutral register. Keep the tone formal.
- Write pytest-bluezenv's own explanation. Do not mirror the wording of
  documents such as BlueZ testing manual.
- Verify section titles reflect what is discussed in the section.

## Terminology

- Use the Bluetooth and BlueZ nomenclatures.
- The Pytest side is the **upper tester**. The guest is the **VM
  host**; its in-guest runtime is the **lower tester**.
- Distinguish a documented API object (capitalised, e.g. `Bluetoothd`)
  from the program it wraps (lowercase, e.g. ``bluetoothd``,
  ``bluetoothctl``, ``btvirt``, ``chronyd``), from BlueZ's own `tester`
  program, and from keyword arguments and their values (``hw=True``,
  ``reuse=True``).

## Internal implementation details

Some things an external tool does are internal to pytest-bluezenv. The
`test-runner` QEMU launcher is one example. Do not build the reader's
understanding around it. It may be named, but only with enough context for
the reader to know what it is, and framed as an implementation detail.

## Cross-references

- Reference every documented API object with a real Sphinx
  cross-reference, never preformatted text. Write
  ``:obj:`~pytest_bluezenv.host_config` ``, not ``` ``host_config``` ```.
  Use the tilde short form so it renders as `host_config`. Nested proxies
  take the full dotted path, e.g. `pytest_bluezenv.Call.Proxy`.
- Keep ``` ``double backticks`` ``` for things that are not API objects:
  command-line options (``` ``--vm-timeout``` ``), program and file names,
  keyword arguments and their values, logger names, and generic interface
  verbs (`send` / `expect` / `reply` used as a pattern).
- Never invent a target. Check Sphinx output for warnings about missing targets.

## Examples for main features

Every main feature needs a short example. Keep it minimal: illustrate
the one point being made. The example does not have to be runnable
code.  If the feature is complex, include multiple examples
illustrating different points.

## "Writing tests" documentation

The file ``doc/writing_tests.rst`` must cover all main features of
``pytest-bluezenv`` related to writing tests. If something is missing,
add a new section, or modify a suitable existing section with new example
and explanation.

## Docstrings

- Give every public object a docstring that explains its parameters
  and succinctly what it does.
- If a function or class ``__init__`` takes parameters, an ``Args:`` section
  is mandatory.
- Docstring ``Args:`` should list type annotation for the argument.
  If the type is part of private API, it should not be listed.
- If a value is returned, ``Returns:`` is mandatory.
- If values are yielded, ``Yields:`` is mandatory.
- Raised exceptions usually do not need to be documented, unless they are
  a central part of the API, such as ``RemoteError``.
- Per-plugin lifecycle overrides (`presetup` / `setup` / `teardown`) and
  RPC methods should also be documented.
- After a build, read `doc/api/*` and confirm every listed object is
  documented.
- At least one example is required in docstrings of main features.

## Figures

Diagrams are plain SVG in `doc/_static/`.

- Depict the concept faithfully.
- Connect arrows so they actually meet the boxes they attach to; size the
  boxes so this holds.
- Keep labels and caption text clear of arrows and of each other.

## Downstream context

pytest-bluezenv is used by BlueZ. When deciding what needs explaining,
consult the downstream BlueZ tree to look for examples.  The relevant
parts in the BlueZ tree are `doc/*functional*` and
`test/functional/*`.  If you cannot find it, ask user to provide it.

## Workflow

If you are asked to make commits:

- Do not commit text back and forth. Get each logical change right in one
  commit.

## Verifying

- Rebuild after changes and require a clean build (no `WARNING:` or
  `ERROR:`).
- Run a nitpick pass, `sphinx-build -b html . _build -n`, to catch dangling
  `:obj:` and `:doc:` targets. Ignore the pre-existing bare-type-name and
  ambiguous-target warnings.
- Run `black --check` on changed source files; docstring edits must stay
  formatted.
