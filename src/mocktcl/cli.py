"""Command-line entry point."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__, config
from .console import Console
from .coverage import html as html_report
from .coverage import lcov as lcov_report
from .coverage import text as text_report
from .coverage.model import build_coverage, find_sources, instrument_project
from .discovery import SelectionError, collect
from .runner import RunConfig, run_files

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_NO_TESTS = 0, 1, 2, 5


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mocktcl",
        description="Run Tcl tests with assertions, mocking and line/branch coverage.",
    )
    p.add_argument("paths", nargs="*", help="test files, directories, or FILE::TEST_NAME (default: tests dir)")
    p.add_argument("-k", dest="keyword", default="", metavar="TEXT", help="only run tests whose FILE::NAME contains TEXT")
    p.add_argument("-j", "--jobs", type=int, default=None, metavar="N", help="run N test files in parallel")
    p.add_argument("-s", "--no-capture", action="store_true", help="don't capture test output")
    p.add_argument("-v", "--verbose", action="count", default=0, help="one line per test")
    p.add_argument("-q", "--quiet", action="count", default=0, help="less output")
    p.add_argument("-x", "--exitfirst", action="store_true", help="stop after the first file with a failure")
    p.add_argument("--root", type=Path, default=None, help="project root (default: current directory)")
    p.add_argument("--tests-dir", default=None, help="directory holding tests (default: tests)")
    p.add_argument("--tclsh", default=None, help="tclsh executable (default: tclsh)")
    p.add_argument("--timeout", type=float, default=None, metavar="SEC", help="per-file timeout in seconds")
    p.add_argument("--no-cov", action="store_true", help="disable coverage")
    p.add_argument("--cov", action="append", default=None, metavar="PATH",
                   help="source path to measure (repeatable; default: project root)")
    p.add_argument("--cov-omit", action="append", default=None, metavar="GLOB",
                   help="exclude matching source files (repeatable)")
    p.add_argument("--cov-report", action="append", default=None, metavar="TYPE[:DEST]",
                   help="text, lcov[:file], html[:dir] (repeatable; default: text)")
    p.add_argument("--fail-under", type=float, default=None, metavar="PCT",
                   help="fail if total line coverage is below PCT")
    p.add_argument("--keep-tmp", action="store_true", help="keep the temp dir with jobs, results and instrumented code")
    p.add_argument("--version", action="version", version=f"mocktcl {__version__}")
    return p


def tcl_version(tclsh: str) -> str | None:
    try:
        proc = subprocess.run([tclsh], input=b"puts [info patchlevel]\n", capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.decode().strip() if proc.returncode == 0 else None


def parse_reports(specs: list[str], root: Path) -> list[tuple[str, Path | None]]:
    reports: list[tuple[str, Path | None]] = []
    for spec in specs:
        kind, _, dest = spec.partition(":")
        if kind not in ("text", "lcov", "html"):
            raise SelectionError(f"unknown coverage report type: {kind}")
        if kind == "text":
            reports.append((kind, None))
        else:
            default = "lcov.info" if kind == "lcov" else "coverage_html"
            reports.append((kind, root / (dest or default)))
    return reports


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = (args.root or Path.cwd()).resolve()
    err = Console(sys.stderr, color=False)
    try:
        cfg = config.load(root)
    except config.ConfigError as e:
        err.write(f"mocktcl: {e}")
        return EXIT_USAGE

    tests_dir = args.tests_dir or cfg.get("tests_dir", "tests")
    tclsh = args.tclsh or cfg.get("tclsh", "tclsh")
    jobs = args.jobs or cfg.get("jobs", 1)
    timeout = args.timeout or cfg.get("timeout")
    cov_paths = args.cov or cfg.get("cov") or ["."]
    cov_omit = args.cov_omit or cfg.get("cov_omit", [])
    fail_under = args.fail_under if args.fail_under is not None else cfg.get("fail_under")
    verbosity = args.verbose - args.quiet
    console = Console(sys.stdout, verbosity)

    version = tcl_version(tclsh)
    if version is None:
        err.write(f"mocktcl: cannot run '{tclsh}'; install Tcl or pass --tclsh")
        return EXIT_USAGE

    try:
        reports = [] if args.no_cov else parse_reports(args.cov_report or cfg.get("cov_report") or ["text"], root)
        selectors = args.paths or [tests_dir]
        files = collect(selectors, root, args.keyword)
    except SelectionError as e:
        err.write(f"mocktcl: {e}")
        return EXIT_USAGE
    if args.keyword or any("::" in s for s in selectors):
        files = [f for f in files if f.tests or not f.only]

    tmp = Path(tempfile.mkdtemp(prefix="mocktcl-"))
    try:
        project = None
        if not args.no_cov:
            sources = find_sources([Path(p) for p in cov_paths], root, [root / tests_dir], cov_omit)
            project = instrument_project(sources, root, tmp / "instrumented")

        console.header(version, len(files))
        run_cfg = RunConfig(
            root=root,
            tclsh=tclsh,
            workdir=tmp,
            tcl_map=project.tcl_map if project else {},
            keyword=args.keyword,
            capture=not args.no_capture,
            jobs=max(1, jobs),
            timeout=timeout,
        )
        run = run_files(files, run_cfg, console.file_done, stop_on_fail=args.exitfirst)
        console.summary(run)

        exit_code = EXIT_OK if run.ok else EXIT_FAILED
        if not run.tests and not run.file_errors:
            exit_code = EXIT_NO_TESTS

        if project is not None:
            data = build_coverage(project, run.merged_hits())
            for kind, dest in reports:
                if kind == "text":
                    if verbosity >= -1:
                        console.write("")
                        console.write(text_report.render(data).rstrip())
                elif kind == "lcov":
                    lcov_report.write(data, root, dest)
                    console.write(f"lcov report written to {dest}")
                elif kind == "html":
                    index = html_report.write(data, dest)
                    console.write(f"HTML report written to {index}")
            if fail_under is not None and data.line_percent < fail_under:
                console.write(f"FAIL: line coverage {data.line_percent:.1f}% is below --fail-under {fail_under}%")
                if exit_code == EXIT_OK:
                    exit_code = EXIT_FAILED
        return exit_code
    finally:
        if args.keep_tmp:
            err.write(f"mocktcl: temp files kept in {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
