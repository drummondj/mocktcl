mocktcl
=======

mocktcl is a testing framework for TCL including scripts, procs and namespaces.

It provides:

1. A test runner.
2. Assertion functions.
3. Mocking for procs, built-in commands and fixtures.
4. Line and branch coverage metrics

It is written in Python.

## 1. Test runner

mocktcl is a CLI to discover, run, and collect test metrics.

Test files are stored in a `tests` directory and are prefixed with `test_`. Sub-directories can be created to group tests into test suites, which mocktcl will recursively walk to discover tests. Files without a `test_` prefix can be added to define helper functions, fixtures and mocks that are re-used across tests.

```
tests/
   test_my_app.tcl
   test_my_package.tcl
   a_test_suite/
      test_something.tcl
      test_something_else.tcl
   fixtures/
      a_model.tcl
   helpers.tcl
   mocks.tcl
```

The CLI can choose specific files or directories to run. By default, mocktcl runs all tests in the `tests` directory.

Each test file contains procs, prefixed with `test_`.

```tcl
proc test_something_works {} {
    ...
}
```

Line and branch coverage metrics are collected and reported.

## 2. Assertion functions

The following assertions are used to determine pass/fail:

```tcl
expect <v1> <v2> : v1 == v2
expect_not <v2> <v2> : v1 != v2
expect_contains <v1> <v2> : v1 contains the chacaters in v2
expect_list <l1> <l2> : l1 and l2 contain the same elements but not nessesarily in the same order
expect_list_contains <l1> <l2> : l1 is a superset of l2
expect_called <mock> <n> : asserts that the mock was called n times
```

Each expect function has an optional third argument to specify a failure message, for example:

```tcl
expect $v1 "correct value" "Some custom failure message"
```

## 3. Mocking

procs can be mocked using the mock function:

```tcl
mock <my_proc_name> { [args ...] } {
    ... body ...
}
```

This works just like a normal proc apart from the number of calls can be asserted with expect_called.

## 4. Coverage metrics

Reported in the following formats:

1. lcov.info
2. HTML
3. Text report




