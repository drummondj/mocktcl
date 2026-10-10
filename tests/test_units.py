"""Unit tests for the modules that don't need tclsh."""

import json
import subprocess
from pathlib import Path

import pytest

from mocktcl import config, discovery, runner
from mocktcl.console import Console
from mocktcl.coverage.model import line_ranges
from mocktcl.discovery import SelectionError, TestFile, collect


# -- config ------------------------------------------------------------------


def test_config_from_mocktcl_toml_section(tmp_path):
    (tmp_path / "mocktcl.toml").write_text('[mocktcl]\ncov = "src"\ncov-omit = ["x/*"]\njobs = 2\n')
    assert config.load(tmp_path) == {"cov": ["src"], "cov_omit": ["x/*"], "jobs": 2}


def test_config_top_level_keys(tmp_path):
    (tmp_path / "mocktcl.toml").write_text("fail_under = 90.5\n")
    assert config.load(tmp_path) == {"fail_under": 90.5}


def test_config_absent(tmp_path):
    assert config.load(tmp_path) == {}
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    assert config.load(tmp_path) == {}


def test_config_wrong_type(tmp_path):
    (tmp_path / "mocktcl.toml").write_text('jobs = "four"\n')
    with pytest.raises(config.ConfigError, match="'jobs' has the wrong type"):
        config.load(tmp_path)


def test_config_invalid_toml(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.mocktcl\n")
    with pytest.raises(config.ConfigError, match="pyproject.toml"):
        config.load(tmp_path)


# -- discovery ---------------------------------------------------------------


def test_read_source_falls_back_to_latin1(tmp_path):
    p = tmp_path / "x.tcl"
    p.write_bytes(b"set a \xe9\n")
    assert discovery.read_source(p) == "set a é\n"


def test_top_level_procs():
    text = "proc ::test_a {} {}\nproc $name {} {}\nproc test_a {} {}\nproc ns::test_b {} {\n}\n"
    assert discovery.top_level_procs(text) == {"test_a": 1, "ns::test_b": 4}
    assert discovery.top_level_procs("proc f {} {") == {}


def test_rel_to_outside_root(tmp_path):
    assert discovery.rel_to(Path("/elsewhere/x.tcl"), tmp_path) == "/elsewhere/x.tcl"


def make_tests(tmp_path):
    t = tmp_path / "tests"
    t.mkdir()
    (t / "test_a.tcl").write_text("proc test_one {} {}\nproc test_two {} {}\n")
    (t / ".hidden").mkdir()
    (t / ".hidden" / "test_h.tcl").write_text("proc test_h {} {}\n")
    return t


def test_collect_merges_selectors(tmp_path):
    make_tests(tmp_path)
    [f] = collect(["tests/test_a.tcl::test_two", "tests/test_a.tcl::test_one"], tmp_path)
    assert (f.tests, f.only) == (["test_one", "test_two"], True)
    [f] = collect(["tests/test_a.tcl::test_two", "tests/test_a.tcl"], tmp_path)
    assert (f.tests, f.only) == (["test_one", "test_two"], False)
    [f] = collect(["tests/test_a.tcl", "tests/test_a.tcl::test_two"], tmp_path)
    assert f.only is False


def test_collect_unknown_test_name_is_kept_for_harness(tmp_path):
    make_tests(tmp_path)
    [f] = collect(["tests/test_a.tcl::test_dynamic"], tmp_path)
    assert f.tests == ["test_dynamic"]


def test_collect_skips_hidden_dirs_and_accepts_absolute_paths(tmp_path):
    t = make_tests(tmp_path)
    files = collect([str(t)], tmp_path)
    assert [f.rel for f in files] == ["tests/test_a.tcl"]


def test_collect_rejects_test_name_on_directory(tmp_path):
    make_tests(tmp_path)
    with pytest.raises(SelectionError, match="cannot select a test name"):
        collect(["tests::test_one"], tmp_path)


# -- runner ------------------------------------------------------------------


def test_tcl_quoting():
    assert runner.tcl_str("") == "{}"
    assert runner.tcl_str('a b\n{$x}[y];"\\') == 'a\\ b\\n\\{\\$x\\}\\[y\\]\;\\"\\\\'
    assert runner.tcl_dict({"k": "v w"}) == "k v\\ w"


def make_cfg(tmp_path, tclsh="tclsh"):
    return runner.RunConfig(root=tmp_path, tclsh=tclsh, workdir=tmp_path, tcl_map={})


def test_run_file_reports_unstartable_tclsh(tmp_path):
    tf = TestFile(tmp_path / "test_x.tcl", "test_x.tcl", [])
    result = runner.run_file(tf, make_cfg(tmp_path, "/no/such/tclsh"), 0)
    assert [e.message for e in result.errors] == [
        "tclsh did not finish the test file (exit status could not start /no/such/tclsh: "
        "[Errno 2] No such file or directory: '/no/such/tclsh')"
    ]


def test_run_file_ignores_corrupt_result_lines(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        (tmp_path / "results_0.jsonl").write_text(
            'not json\n{"event":"test","name":"test_x","status":"pass","line":""}\n{"event":"done"}\n'
        )
        return subprocess.CompletedProcess(cmd, 0, b"", None)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    tf = TestFile(tmp_path / "test_x.tcl", "test_x.tcl", [])
    result = runner.run_file(tf, make_cfg(tmp_path), 0)
    assert [(t.name, t.status, t.line) for t in result.tests] == [("test_x", "pass", None)]
    assert result.errors == []


def test_locate_prefers_test_frame():
    tf = TestFile(Path("t.tcl"), "t.tcl", [], body_lines={"helper": 10, "test_a": 20})
    info = '(procedure "helper" line 2)\n(procedure "::test_a" line 3)\n(procedure "other" line 9)'
    assert runner.locate(info, tf, "test_a") == 22
    assert runner.locate(info, tf, None) == 11
    assert runner.locate("(procedure \"other\" line 9)", tf) is None


# -- misc ----------------------------------------------------------------------


def test_line_ranges():
    assert line_ranges([]) == ""
    assert line_ranges([1, 2, 3, 7, 9, 10]) == "1-3, 7, 9-10"


def test_console_color(tmp_path):
    import io

    out = io.StringIO()
    console = Console(out, color=True)
    assert console.c("x", "pass") == "\x1b[32mx\x1b[0m"
    assert console.c("x") == "x"
    assert Console(out).color is False  # StringIO is not a tty
