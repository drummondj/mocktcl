---
name: write-tcl-tests
description: Write Tcl tests that use mocktcl (test procs, expect* assertions, mock, hooks). Use when adding Tcl test files to a project or to mocktcl's fixtures/examples.
---

# Writing mocktcl tests

Layout: put test files in `tests/`, named `test_*.tcl`. Subdirectories become
suites. Files without the `test_` prefix are helpers and are only loaded if a
test file sources them:

```tcl
source [file join [file dirname [info script]] helpers.tcl]
source [file join [file dirname [info script]] .. src calc.tcl]   ;# code under test
```

Each `proc test_* {}` is one test. Tests run in definition order.

```tcl
proc before_all {} { ... }    ;# optional, once per file
proc before_each {} { ... }   ;# optional, before every test
proc after_each {} { ... }    ;# optional, always runs after every test
proc after_all {} { ... }     ;# optional, once per file

proc test_add {} {
    expect [calc::add 1 2] 3
    expect_not [calc::add 1 2] 4 "addition is broken"
    expect [expr 10 * 0.66] 6.6                    ;# float rounding noise is tolerated
    expect_near $slack 0.12 0.001                  ;# explicit tolerance
    expect_contains [calc::describe 5] "five"
    expect_list [calc::factors 12] {6 2 4 3 1 12}
    expect_list_contains [calc::factors 12] {2 3}
    expect_error {calc::div 1 0} "*divide by zero*"
}

proc test_uses_mock {} {
    mock ::calc::log {msg} { return "" }            ;# replaces the proc for this test only
    mock clock {args} { return 1700000000 }         ;# built-ins can be mocked too
    calc::add 1 2
    expect_called ::calc::log 1
}

proc test_not_ready {} { skip "waiting on upstream fix" }
```

Rules:
- Each assertion takes an optional extra argument, a custom failure message.
- `expect`/`expect_not` compare decimal numbers with a relative tolerance of 1e-9, and compare integers
  and strings exactly. Comparisons with zero are exact unless the project sets `float_zero_tolerance`
  (mocktcl.toml or `--float-zero-tolerance`). Otherwise use `expect_near ... 0 tol`. Use `expect_near` for explicit tolerances.
- See `examples/sdc` for testing proc-less scripts such as SDC constraints. Read them at global level
  (`uplevel #0 source`), mock the tool's commands, and inspect their arguments with `mock_calls`.
- A mock lasts for the test it was created in (including `before_each`). A mock created at file
  level or in `before_all` lasts for the whole file.
- Don't mock `proc`, `rename`, `namespace`, `uplevel`, `info`, `source` or `catch`.
- `exit` inside code under test fails the test instead of killing the run.
- Each test file runs in a fresh `tclsh` process, so files never share state.
