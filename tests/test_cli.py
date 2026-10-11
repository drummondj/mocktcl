"""CLI behaviour: selection, exit codes, config and coverage reports."""

import shutil
from pathlib import Path

import pytest

from mocktcl.cli import main

from .conftest import requires_tcl

pytestmark = requires_tcl

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "calculator"
SDC_EXAMPLE = EXAMPLE.parent / "sdc"

SIMPLE = {
    "src/m.tcl": """
        proc m::sign {n} {
            if {$n < 0} {
                return neg
            }
            return pos
        }
        namespace eval m {}
    """,
    "tests/test_one.tcl": """
        namespace eval m {}
        source src/m.tcl
        proc test_neg {} { expect [m::sign -1] neg }
        proc test_other {} { expect 1 1 }
    """,
    "tests/sub/test_two.tcl": "proc test_two {} { expect 1 1 }\n",
}


def test_example_project(run_cli, tmp_path):
    root = tmp_path / "calculator"
    shutil.copytree(EXAMPLE, root)
    code, out = run_cli(root, "--cov-report", "text", "--cov-report", "lcov", "--cov-report", "html")
    assert code == 0, out
    assert "12 passed, 1 skipped" in out
    assert "src/calc.tcl" in out and "src/report.tcl" in out
    lcov = (root / "lcov.info").read_text()
    # calc::between: "$n <= $hi" (block 2 on line 25) was never false
    assert "BRDA:25,2,0,1\nBRDA:25,2,1,0" in lcov
    assert (root / "coverage_html" / "index.html").is_file()


def test_sdc_example_project(run_cli, tmp_path):
    root = tmp_path / "sdc"
    shutil.copytree(SDC_EXAMPLE, root)
    code, out = run_cli(root, "--fail-under", "100")
    assert code == 0, out
    assert "6 passed" in out
    assert "constraints/top.sdc" in out and "100.0%" in out


def test_runs_all_tests_recursively_by_default(project, run_cli):
    root = project(SIMPLE)
    code, out = run_cli(root, "--no-cov")
    assert code == 0
    assert "tests/test_one.tcl .." in out
    assert "tests/sub/test_two.tcl ." in out


def test_select_file_dir_and_test(project, run_cli):
    root = project(SIMPLE)
    code, out = run_cli(root, "--no-cov", "tests/sub")
    assert "test_two.tcl" in out and "test_one" not in out
    code, out = run_cli(root, "--no-cov", "-v", "tests/test_one.tcl::test_other")
    assert "test_other PASSED" in out and "test_neg" not in out


def test_keyword_filter(project, run_cli):
    root = project(SIMPLE)
    code, out = run_cli(root, "--no-cov", "-v", "-k", "NEG")
    assert code == 0
    assert "test_neg PASSED" in out
    assert "test_other" not in out and "test_two" not in out


def test_missing_path_is_usage_error(project, run_cli):
    root = project(SIMPLE)
    code, out = run_cli(root, "nope")
    assert code == 2
    assert "no such file or directory" in out


def test_no_tests_exit_code(project, run_cli):
    root = project({"tests/test_empty.tcl": "set x 1\n"})
    code, _ = run_cli(root, "--no-cov")
    assert code == 5


def test_missing_tclsh(project, capsys):
    root = project(SIMPLE)
    code = main(["--root", str(root), "--tclsh", "/no/such/tclsh"])
    assert code == 2
    assert "cannot run" in capsys.readouterr().err


def test_text_report_and_branches(project, run_cli):
    root = project(SIMPLE)
    code, out = run_cli(root)
    assert code == 0
    row = next(l for l in out.splitlines() if l.startswith("src/m.tcl"))
    # lines 1 (proc), 2 (if), 3 (return neg), 5 (return pos), 7 (namespace)
    assert row.split()[1:4] == ["5", "1", "80.0%"]
    assert row.split()[4:7] == ["2", "1", "50.0%"]
    assert row.rstrip().endswith("5")
    assert "tests/" not in out.split("File")[1]


def test_lcov_contents(project, run_cli):
    root = project(SIMPLE)
    run_cli(root, "--cov-report", "lcov:out/cov.info")
    lcov = (root / "out" / "cov.info").read_text()
    assert f"SF:{root.as_posix()}/src/m.tcl" in lcov
    assert "DA:3,1" in lcov and "DA:5,0" in lcov
    assert "BRDA:2,0,0,1" in lcov and "BRDA:2,0,1,0" in lcov
    assert "LF:5\nLH:4" in lcov and "BRF:2\nBRH:1" in lcov
    assert lcov.endswith("end_of_record\n")


def test_html_report(project, run_cli):
    root = project(SIMPLE)
    run_cli(root, "--cov-report", "html:htmlcov")
    index = (root / "htmlcov" / "index.html").read_text()
    assert "src/m.tcl" in index
    page = (root / "htmlcov" / "src_m.tcl.html").read_text()
    assert "class='miss'" in page and "class='hit'" in page


def test_unsourced_file_reported_at_zero(project, run_cli):
    root = project({**SIMPLE, "src/unused.tcl": "proc u {} {\n    return 1\n}\n"})
    code, out = run_cli(root)
    row = next(l for l in out.splitlines() if l.startswith("src/unused.tcl"))
    assert "0.0%" in row


def test_cov_and_omit(project, run_cli):
    root = project({**SIMPLE, "other/x.tcl": "set a 1\n"})
    code, out = run_cli(root, "--cov", "src")
    assert "other/x.tcl" not in out
    code, out = run_cli(root, "--cov-omit", "other/*")
    assert "other/x.tcl" not in out and "src/m.tcl" in out


def test_fail_under(project, run_cli):
    root = project(SIMPLE)
    code, out = run_cli(root, "--fail-under", "90")
    assert code == 1
    assert "below --fail-under" in out
    code, _ = run_cli(root, "--fail-under", "50")
    assert code == 0


def test_config_file(project, run_cli):
    root = project({**SIMPLE, "pyproject.toml": '[tool.mocktcl]\ncov_report = ["lcov:c.info"]\nfail_under = 99\n'})
    code, out = run_cli(root)
    assert code == 1
    assert (root / "c.info").is_file()


def test_bad_config(project, run_cli):
    root = project({**SIMPLE, "mocktcl.toml": "bogus = 1\n"})
    code, out = run_cli(root)
    assert code == 2
    assert "unknown option 'bogus'" in out


CONDITIONS = {
    "src/c.tcl": """
        proc c::both {a b} {
            if {$a && [string is digit $b]} { return yes }
            return no
        }
        namespace eval c {}
    """,
    "tests/test_c.tcl": """
        namespace eval c {}
        source src/c.tcl
        proc test_both {} {
            expect [c::both 1 7] yes
            expect [c::both 0 7] no
            expect_error {c::both maybe 7} "*expected boolean*"
        }
    """,
}


def test_condition_coverage(project, run_cli):
    root = project(CONDITIONS)
    code, out = run_cli(root, "--cov-report", "lcov")
    assert code == 0, out
    lcov = (root / "lcov.info").read_text()
    # block 0: the if arms; block 1: $a (true, false); block 2: [string is digit $b] (never false)
    for brda in ("2,0,0,1", "2,0,1,1", "2,1,0,1", "2,1,1,1", "2,2,0,1", "2,2,1,0"):
        assert f"BRDA:{brda}" in lcov
    assert "BRF:6\nBRH:5" in lcov


@pytest.mark.parametrize("config", ["", "cov_conditions = false\n"])
def test_condition_coverage_off(project, run_cli, config):
    root = project({**CONDITIONS, "mocktcl.toml": config})
    code, out = run_cli(root, "--cov-report", "lcov", *([] if config else ["--no-cov-conditions"]))
    assert code == 0, out
    assert "BRF:2\nBRH:2" in (root / "lcov.info").read_text()


def test_parallel_and_exitfirst(project, run_cli):
    files = {f"tests/test_{i}.tcl": f"proc test_{i} {{}} {{ expect {i} {i} }}\n" for i in range(6)}
    files["tests/test_0.tcl"] = "proc test_0 {} { expect 0 1 }\n"
    root = project(files)
    code, out = run_cli(root, "--no-cov", "-j", "4")
    assert code == 1
    assert "5 passed, 1 failed" in out
    code, out = run_cli(root, "--no-cov", "-x")
    assert "1 failed" in out and "passed" not in out


def test_timeout(project, run_cli):
    root = project({"tests/test_slow.tcl": "proc test_slow {} { after 5000 }\n"})
    code, out = run_cli(root, "--no-cov", "--timeout", "0.5")
    assert code == 1
    assert "timeout" in out


def test_unparseable_source_reported(project, run_cli):
    root = project({**SIMPLE, "src/broken.tcl": "proc b {} {\n"})
    code, out = run_cli(root)
    assert "not instrumented" in out


def test_unknown_report_type(project, run_cli):
    root = project(SIMPLE)
    code, out = run_cli(root, "--cov-report", "xml")
    assert code == 2
    assert "unknown coverage report type: xml" in out


def test_very_quiet_hides_text_report_and_header(project, run_cli):
    root = project(SIMPLE)
    code, out = run_cli(root, "-qq")
    assert code == 0
    assert "Line%" not in out and "mocktcl:" not in out


def test_fail_under_with_failing_tests_keeps_exit_code(project, run_cli):
    root = project({**SIMPLE, "tests/test_bad.tcl": "proc test_bad {} { expect 1 2 }\n"})
    code, out = run_cli(root, "--fail-under", "100")
    assert code == 1
    assert "below --fail-under" in out


def test_keep_tmp(project, run_cli):
    root = project(SIMPLE)
    code, out = run_cli(root, "--keep-tmp")
    kept = Path(out.split("temp files kept in ")[1].split()[0])
    try:
        assert (kept / "results_0.jsonl").is_file()
        assert any((kept / "instrumented").iterdir())
    finally:
        shutil.rmtree(kept)


def test_unparseable_source_skipped_by_lcov_and_html(project, run_cli):
    root = project({**SIMPLE, "src/broken.tcl": "proc b {} {\n"})
    run_cli(root, "--cov-report", "lcov", "--cov-report", "html")
    assert "broken.tcl" not in (root / "lcov.info").read_text()
    assert "not instrumented" in (root / "coverage_html" / "index.html").read_text()


def test_cov_single_file_and_omitted_file(project, run_cli):
    root = project({**SIMPLE, "src/other.tcl": "set a 1\n"})
    code, out = run_cli(root, "--cov", "src/m.tcl", "--cov", "src/other.tcl", "--cov-omit", "other.tcl")
    assert "src/m.tcl" in out and "src/other.tcl" not in out


def test_cov_path_inside_tests_dir_is_excluded(project, run_cli):
    root = project({**SIMPLE, "tests/helper.tcl": "set a 1\n"})
    code, out = run_cli(root, "--cov", "tests")
    assert "helper.tcl" not in out
    assert "TOTAL" in out


def test_verbose_shows_file_errors(project, run_cli):
    root = project({"tests/test_a.tcl": "error {cannot load}\n"})
    code, out = run_cli(root, "--no-cov", "-v")
    assert code == 1
    assert "tests/test_a.tcl ERROR cannot load" in out


def test_module_entry_point(monkeypatch, capsys):
    import runpy

    import pytest

    monkeypatch.setattr("sys.argv", ["mocktcl", "--version"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("mocktcl", run_name="__main__")
    assert exc.value.code == 0
    assert "mocktcl 0.1.0" in capsys.readouterr().out
