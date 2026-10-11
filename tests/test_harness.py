"""End-to-end behaviour of the Tcl harness, driven through the CLI."""

import json

from .conftest import requires_tcl

pytestmark = requires_tcl


def test_assertions_pass(project, run_cli):
    root = project({"tests/test_a.tcl": """
        proc test_all {} {
            expect abc abc
            expect 2 2.0
            expect_not a b
            expect_contains "hello world" "lo wo"
            expect_list {a b c b} {b c b a}
            expect_list_contains {a b c} {c a}
            expect_error {error "bad thing"} "*bad*"
            expect_error {error x}
        }
    """})
    code, out = run_cli(root, "--no-cov", "-v")
    assert code == 0, out
    assert "test_all PASSED" in out


def test_each_assertion_fails_with_message(project, run_cli):
    root = project({"tests/test_a.tcl": """
        proc test_expect {} { expect 1 2 "custom message" }
        proc test_expect_not {} { expect_not 1 1 }
        proc test_contains {} { expect_contains abc z }
        proc test_list {} { expect_list {a b} {a a} }
        proc test_list_contains {} { expect_list_contains {a b} {c} }
        proc test_error_none {} { expect_error {set x 1} }
        proc test_error_pattern {} { expect_error {error abc} "*xyz*" }
        proc test_called {} { mock foo {} {}; expect_called foo 1 }
    """})
    code, out = run_cli(root, "--no-cov")
    assert code == 1
    assert "tests/test_a.tcl FFFFFFFF" in out
    assert "custom message\nexpected \"2\" but got \"1\"" in out
    assert "expected value other than \"1\"" in out
    assert 'expected "abc" to contain "z"' in out
    assert 'missing: "a"' in out and 'unexpected: "b"' in out
    assert 'missing: "c"' in out
    assert "expected an error but the script returned \"1\"" in out
    assert 'expected error matching "*xyz*" but got "abc"' in out
    assert "expected ::foo to be called 1 time but it was called 0" in out
    assert "test_expect (line 1)" in out
    assert "test_called (line 8)" in out


def test_assertion_wrong_args_is_an_error(project, run_cli):
    root = project({"tests/test_a.tcl": "proc test_x {} {\n    expect 1\n}\n"})
    code, out = run_cli(root, "--no-cov")
    assert code == 1
    assert "test_x (line 2)" in out
    assert 'wrong # args: should be "expect actual expected ?message?"' in out


def test_errors_report_test_file_line(project, run_cli):
    root = project({"tests/test_a.tcl": """
        proc helper {} { error kaboom }

        proc test_x {} {
            set a 1
            helper
        }
    """})
    code, out = run_cli(root, "--no-cov")
    assert code == 1
    assert "test_x (line 5)" in out
    assert "kaboom" in out
    assert "$child eval" not in out


def test_mock_proc_namespaced_builtin_and_missing(project, run_cli):
    root = project({
        "src/lib.tcl": """
            namespace eval lib {}
            proc lib::now {} { return [clock seconds] }
            proc lib::greet {name} { return "hello [lib::fmt $name]" }
            proc lib::fmt {name} { return $name }
            proc lib::remote {} { return [fetch_remote] }
        """,
        "tests/test_mock.tcl": """
            source src/lib.tcl
            proc test_namespaced {} {
                mock lib::fmt {name} { return "<$name>" }
                expect [lib::greet bob] "hello <bob>"
                expect [lib::greet amy] "hello <amy>"
                expect_called lib::fmt 2
                expect_called ::lib::fmt 2
                expect [mock_calls lib::fmt] {bob amy}
            }
            proc test_restored {} {
                expect [lib::greet bob] "hello bob"
            }
            proc test_builtin {} {
                mock clock {args} { return 42 }
                expect [lib::now] 42
                expect_called clock 1
            }
            proc test_builtin_restored {} {
                expect [string is integer [clock seconds]] 1
                expect_not [clock seconds] 42
            }
            proc test_missing_command {} {
                mock fetch_remote {} { return data }
                expect [lib::remote] data
            }
            proc test_missing_removed {} {
                expect_error {lib::remote} "*invalid command name*"
            }
            proc test_remock_same_test {} {
                mock lib::fmt {n} { return A }
                mock lib::fmt {n} { return B }
                expect [lib::fmt x] B
            }
            proc test_remock_restored {} {
                expect [lib::fmt x] x
            }
            proc test_mock_string_does_not_break_assertions {} {
                mock string {args} { return broken }
                expect 1 1
                expect_contains abc b
            }
        """,
    })
    code, out = run_cli(root, "--no-cov", "-v")
    assert code == 0, out
    assert out.count("PASSED") == 9


def test_counts_reset_between_tests(project, run_cli):
    root = project({"tests/test_a.tcl": """
        proc f {} {}
        mock f {} {}
        proc test_one {} { f; f; expect_called f 2 }
        proc test_two {} { f; expect_called f 1 }
    """})
    code, out = run_cli(root, "--no-cov")
    assert code == 0, out


def test_file_level_mock_lasts_for_file(project, run_cli):
    root = project({"tests/test_a.tcl": """
        proc f {} { return real }
        proc before_all {} { mock f {} { return mocked } }
        proc test_one {} { expect [f] mocked }
        proc test_two {} { expect [f] mocked }
    """})
    code, out = run_cli(root, "--no-cov")
    assert code == 0, out


def test_hooks_order(project, run_cli, tmp_path):
    log = tmp_path / "log.txt"
    root = project({"tests/test_a.tcl": f"""
        set ::log [open {{{log}}} w]
        proc before_all {{}} {{ puts $::log before_all }}
        proc before_each {{}} {{ puts $::log before_each }}
        proc after_each {{}} {{ puts $::log after_each }}
        proc after_all {{}} {{ puts $::log after_all; close $::log }}
        proc test_a {{}} {{ puts $::log a }}
        proc test_b {{}} {{ puts $::log b; expect 1 2 }}
    """})
    code, _ = run_cli(root, "--no-cov")
    assert code == 1
    assert log.read_text().split() == [
        "before_all", "before_each", "a", "after_each", "before_each", "b", "after_each", "after_all",
    ]


def test_before_each_failure_marks_test_error(project, run_cli):
    root = project({"tests/test_a.tcl": """
        proc before_each {} { error "setup broke" }
        proc test_a {} {}
    """})
    code, out = run_cli(root, "--no-cov")
    assert code == 1
    assert "before_each: setup broke" in out


def test_skip(project, run_cli):
    root = project({"tests/test_a.tcl": 'proc test_a {} { skip "not today" }\n'})
    code, out = run_cli(root, "--no-cov", "-v")
    assert code == 0
    assert "SKIPPED (not today)" in out
    assert "1 skipped" in out


def test_exit_is_trapped(project, run_cli):
    root = project({"tests/test_a.tcl": """
        proc test_exit {} { exit 4 }
        proc test_after {} { expect 1 1 }
    """})
    code, out = run_cli(root, "--no-cov")
    assert code == 1
    assert "exit 4 called" in out
    assert "1 passed" in out


def test_load_error(project, run_cli):
    root = project({"tests/test_a.tcl": "proc test_a {} {}\nerror {cannot load}\n"})
    code, out = run_cli(root, "--no-cov")
    assert code == 1
    assert "tests/test_a.tcl (line 2)" in out
    assert "cannot load" in out


def test_dynamically_defined_tests_run(project, run_cli):
    root = project({"tests/test_a.tcl": """
        foreach n {1 2} { proc test_gen_$n {} {} }
        proc test_static {} {}
    """})
    code, out = run_cli(root, "--no-cov", "-v")
    assert code == 0
    lines = [l for l in out.splitlines() if "PASSED" in l]
    assert [l.split("::")[1].split()[0] for l in lines] == ["test_static", "test_gen_1", "test_gen_2"]


def test_captured_output_shown_for_failures(project, run_cli):
    root = project({"tests/test_a.tcl": 'proc test_a {} { puts "debug 123"; expect 1 2 }\n'})
    code, out = run_cli(root, "--no-cov")
    assert "debug 123" in out


def test_info_script_and_return_in_instrumented_source(project, run_cli):
    root = project({
        "src/a.tcl": """
            set ::where [file tail [info script]]
            return
            set ::where wrong
        """,
        "tests/test_a.tcl": """
            source src/a.tcl
            proc test_a {} { expect $::where a.tcl }
        """,
    })
    code, out = run_cli(root, "--cov-report", "text")
    assert code == 0, out
    assert "src/a.tcl" in out


def test_package_require_is_covered(project, run_cli):
    root = project({
        "lib/mypkg/pkgIndex.tcl": "package ifneeded mypkg 1.0 [list source [file join $dir mypkg.tcl]]\n",
        "lib/mypkg/mypkg.tcl": """
            package provide mypkg 1.0
            proc mypkg::hello {} { return hi }
            namespace eval mypkg {}
        """,
        "tests/test_a.tcl": """
            lappend auto_path [file join [pwd] lib]
            namespace eval mypkg {}
            package require mypkg
            proc test_a {} { expect [mypkg::hello] hi }
        """,
    })
    code, out = run_cli(root, "--cov-report", "lcov")
    assert code == 0, out
    lcov = (root / "lcov.info").read_text()
    assert "mypkg.tcl" in lcov
    assert "DA:2,1" in lcov


def test_float_rounding_is_tolerated(project, run_cli):
    root = project({"tests/test_a.tcl": """
        proc test_tolerant {} {
            expect [expr 10 * 0.66] 6.6
            expect [expr {0.1 + 0.2}] 0.3
            expect 5.0 5
            expect 2.5e-9 [expr {2.5 * 1e-9}]
            expect Inf Inf
            expect_not 6.6 6.0
            expect_not 1.0000001 1.0
            expect_not 10000000000000000001 10000000000000000000
            expect_not Inf 1e308
            expect_not NaN 1.0
            expect_not abc 1.0
        }
    """})
    code, out = run_cli(root, "--no-cov", "-v")
    assert code == 0, out


def test_float_tolerance_limits(project, run_cli):
    root = project({"tests/test_a.tcl": """
        proc test_zero_is_exact {} { expect [expr {0.1 + 0.2 - 0.3}] 0 }
        proc test_not_with_rounding_noise {} { expect_not 6.6 [expr 10 * 0.66] }
    """})
    code, out = run_cli(root, "--no-cov")
    assert code == 1
    assert 'expected "0" but got "5.551115123125783e-17"' in out
    assert 'expected value other than "6.6000000000000005"' in out


def test_expect_near(project, run_cli):
    root = project({"tests/test_a.tcl": """
        proc test_pass {} {
            expect_near 6.62 6.6 0.05
            expect_near 6.6 6.6 0
            expect_near 6.601 6.6 0.001
            expect_near 6.599 6.6 0.001
            expect_near [expr {0.1 + 0.2 - 0.3}] 0 1e-12
        }
        proc test_fail {} { expect_near 6.0 6.6 0.001 "input delay" }
        proc test_negative_tolerance {} { expect_near 6.0 6.6 -1 }
        proc test_text {} { expect_near abc 6.6 0.1 }
        proc test_nan {} { expect_near NaN 6.6 0.1 }
        proc test_missing_tolerance {} { expect_near 6.0 6.6 }
    """})
    code, out = run_cli(root, "--no-cov", "-v")
    assert code == 1
    assert "test_pass PASSED" in out
    assert 'input delay\nexpected "6.6" +/- 0.001 but got "6.0" (difference 0.6)' in out
    assert 'tolerance must not be negative but got "-1"' in out
    assert 'actual must be a number but got "abc"' in out
    assert 'actual must be a number but got "NaN"' in out
    assert 'should be "expect_near actual expected tolerance ?message?"' in out


ZERO_TESTS = {"tests/test_a.tcl": """
    proc test_noise {} { expect [expr {0.1 + 0.2 - 0.3}] 0 }
    proc test_zero_first {} { expect 0.0 [expr {0.1 + 0.2 - 0.3}] }
    proc test_real_difference {} { expect 0.5 0 }
    proc test_integer {} { expect 1 0 }
"""}


def test_zero_comparison_is_exact_by_default_with_hint(project, run_cli):
    root = project(ZERO_TESTS)
    code, out = run_cli(root, "--no-cov")
    assert code == 1
    assert "tests/test_a.tcl FFFF" in out
    hint = '(if this is floating-point rounding noise, use "expect_near <value> 0 <tolerance>", ' \
        "or set float_zero_tolerance in mocktcl.toml)"
    assert out.count(hint) == 2  # only for the tiny decimal differences
    assert 'expected "0" but got "0.5"\n\n' in out


def test_float_zero_tolerance_from_cli(project, run_cli):
    root = project(ZERO_TESTS)
    code, out = run_cli(root, "--no-cov", "--float-zero-tolerance", "1e-12")
    assert "tests/test_a.tcl ..FF" in out


def test_float_zero_tolerance_from_config(project, run_cli):
    root = project({**ZERO_TESTS, "mocktcl.toml": "float_zero_tolerance = 1e-12\n"})
    code, out = run_cli(root, "--no-cov")
    assert "tests/test_a.tcl ..FF" in out
    code, out = run_cli(root, "--no-cov", "--float-zero-tolerance", "0")
    assert "tests/test_a.tcl FFFF" in out


def test_negative_float_zero_tolerance(project, run_cli):
    root = project(ZERO_TESTS)
    code, out = run_cli(root, "--float-zero-tolerance", "-1")
    assert code == 2
    assert "float_zero_tolerance must not be negative" in out
