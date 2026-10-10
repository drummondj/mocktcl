# mocktcl

A testing framework for Tcl, written in Python: test runner, assertions, mocking,
and line + branch coverage (text, lcov, HTML). The spec is in `plans/SPECIFICATION.md`
and the design and status are in `plans/PLAN.md`. Read both before making large changes.

## Environment

- Tcl 8.6 (`tclsh`). Python 3.12. The dev venv is `.venv/` (`python3 -m venv .venv && .venv/bin/pip install -e . pytest`).
- Run the Python suite: `.venv/bin/pytest -q`
- Run the tool against the example project: `cd examples/calculator && ../../.venv/bin/mocktcl`

## Layout

- `src/mocktcl/tclparse.py`: Tcl tokenizer (commands/words with offsets and line numbers).
- `src/mocktcl/instrument.py`: inserts coverage probes; `SCRIPT_ARGS` lists which arguments of which commands are script bodies.
- `src/mocktcl/tcl/harness.tcl`: Tcl runtime. It runs inside `tclsh`, one process per test file. The parent interp holds assertions, mocks and coverage counters; test code runs in a child interp and reaches the parent through `interp alias`.
- `src/mocktcl/runner.py`: spawns `tclsh` and reads the JSON-lines results file.
- `src/mocktcl/coverage/`: coverage model plus the text, lcov and HTML writers.
- `src/mocktcl/cli.py`: argparse entry point (`mocktcl`).
- `tests/`: pytest suite for mocktcl itself. Tcl fixture projects are written into `tmp_path` by the tests.
- `examples/`: sample Tcl projects that use mocktcl.

## Invariants (don't break these)

- Instrumentation must never change line numbers. Probes go on the same line, followed by `; `.
- Probe commands (`::mocktcl::_l`, `::mocktcl::_b`) must return the empty string. An injected `else`/`default` arm must not change what a command returns.
- When the parser can't handle a file, sourcing it must still work (fall back to the original text, with no coverage).
- Framework logic stays in the parent interp, so user mocks of built-ins (`string`, `clock`, …) can't break assertions.
- Harness results go to the results file, never to stdout, which belongs to the user's code.

## Conventions

- Python: standard library only at runtime (no third-party deps). Type hints, dataclasses.
- Tcl: must run on 8.6. Avoid 9.0-only commands. Fully qualify the framework's own command names (`::mocktcl::…`).
- Every behaviour change gets a pytest test. Harness behaviour is tested end-to-end by running `tclsh` on small fixture projects.
