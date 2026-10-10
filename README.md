# mocktcl

A testing framework for Tcl: test runner, assertions, mocking of procs and built-in
commands, and line + branch coverage (text, lcov, HTML). Written in Python and
needs `tclsh` 8.6+.

## Install

```sh
pip install -e .          # provides the `mocktcl` command
```

## Writing tests

Put test files in `tests/`, named `test_*.tcl`. Subdirectories are suites.
Other files (helpers, fixtures, mocks) only run when a test file sources them.

```
tests/
   test_my_app.tcl
   a_test_suite/
      test_something.tcl
   fixtures/
      a_model.tcl
   helpers.tcl
```

Each `proc test_*` is a test:

```tcl
source [file join [file dirname [info script]] .. src calc.tcl]

proc test_add {} {
    expect [calc::add 1 2] 3
    expect_not [calc::add 1 2] 4 "custom failure message"
}

proc test_logging {} {
    mock calc::log {msg} { return "" }
    calc::add 1 2
    expect_called calc::log 1
}
```

### Assertions

Each assertion takes an optional trailing failure message.

| Command | Passes when |
|---|---|
| `expect v1 v2` | `v1` equals `v2` (string equality, or numeric equality when both are numbers) |
| `expect_not v1 v2` | `v1` does not equal `v2` |
| `expect_contains v1 v2` | `v1` contains the substring `v2` |
| `expect_list l1 l2` | same elements, in any order (duplicates count) |
| `expect_list_contains l1 l2` | every element of `l2` is in `l1` |
| `expect_called mock n` | `mock` was called exactly `n` times in this test |
| `expect_error script ?pattern?` | `script` raises an error whose message matches the glob `pattern` |

### Mocking

```tcl
mock name {args} { body }
```

- Works on procs, namespaced procs (`::app::db::query`), built-ins (`clock`, `open`, `exec`, …),
  and commands that don't exist yet.
- A mock created inside a test or in `before_each` is removed after that test, and the
  original command is restored.
- A mock created at the top of a file or in `before_all` stays in place for the whole file.
- `mock_calls name` returns the list of argument lists the mock received.
- Not supported: mocking `proc`, `rename`, `namespace`, `uplevel`, `info`, `source` or `catch`.

### Hooks and other helpers

- `before_all`, `before_each`, `after_each`, `after_all`: optional procs in a test file.
  `after_each` always runs.
- `skip ?reason?`: marks the current test as skipped.
- If code under test calls `exit`, the test fails instead of the run ending.
- Each test file runs in its own `tclsh` process. Test code runs in a child interpreter,
  so mocking built-ins can't break the assertions.

## Running

```sh
mocktcl                               # all tests under tests/, with a text coverage report
mocktcl tests/a_test_suite            # a directory
mocktcl tests/test_my_app.tcl::test_add
mocktcl -k parse                      # tests whose FILE::NAME contains "parse"
mocktcl -v -j 4                       # verbose output, 4 files in parallel
mocktcl -x                            # stop after the first file with a failure
mocktcl -s                            # don't capture test output
```

Exit codes: `0` everything passed, `1` a failure, error, or coverage below threshold, `2` usage
error, `5` no tests collected.

## Coverage

Coverage is on by default. mocktcl measures every `*.tcl` / `*.tm` file under the project
root, except the tests directory and hidden directories. Files that never get sourced
are reported at 0%.

```sh
mocktcl --cov src --cov-omit 'src/vendor/*'
mocktcl --cov-report text --cov-report lcov:build/lcov.info --cov-report html:build/coverage
mocktcl --fail-under 85
mocktcl --no-cov
```

- **Line coverage**: every command, including those inside proc bodies, control
  structures, `[command substitutions]`, `namespace eval`, `try`/`catch`, `dict for`, `lmap`
  and TclOO methods.
- **Branch coverage**: every arm of `if`/`elseif`/`else` and `switch`, including the implicit
  "no arm taken" path when an `if` has no `else` or a `switch` has no `default`.

Instrumentation adds probes on the same line as the code they measure, so line numbers in
error messages don't change. Code that is built and evaluated as strings at runtime isn't measured.

## Configuration

Options can go in `mocktcl.toml` or under `[tool.mocktcl]` in `pyproject.toml`. Command-line
options override them.

```toml
[tool.mocktcl]
tests_dir = "tests"
cov = ["src"]
cov_omit = ["src/generated/*"]
cov_report = ["text", "lcov:build/lcov.info"]
fail_under = 80
tclsh = "tclsh8.6"
jobs = 4
timeout = 60
```

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q        # fails below 100% line + branch coverage
cd examples/calculator && ../../.venv/bin/mocktcl -v
```
