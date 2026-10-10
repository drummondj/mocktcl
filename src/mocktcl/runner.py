"""Run test files: one ``tclsh`` process per file, in parallel if requested."""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .discovery import TestFile
from .results import ERROR, FileResult, RunResult, TestResult

_TCL_SPECIAL = set(' \t\r;$[]{}"\\')


def tcl_str(s: str) -> str:
    """Quote a string as a single Tcl list element using backslash escapes."""
    if s == "":
        return "{}"
    out = []
    for c in s:
        if c == "\n":
            out.append("\\n")
        elif c in _TCL_SPECIAL:
            out.append("\\" + c)
        else:
            out.append(c)
    return "".join(out)


def tcl_list(items: list[str]) -> str:
    return " ".join(tcl_str(i) for i in items)


def tcl_dict(d: dict[str, str]) -> str:
    return " ".join(f"{tcl_str(k)} {tcl_str(v)}" for k, v in d.items())


def harness_path() -> Path:
    return Path(str(resources.files("mocktcl") / "tcl" / "harness.tcl"))


@dataclass
class RunConfig:
    root: Path
    tclsh: str
    workdir: Path
    tcl_map: dict[str, str]
    keyword: str = ""
    capture: bool = True
    jobs: int = 1
    timeout: float | None = None


_PROC_FRAME = re.compile(r'\(procedure "(?:::)?([^"]+)" line (\d+)\)')


def locate(errorinfo: str, tf: TestFile, test: str | None = None) -> int | None:
    """Map a ``(procedure "x" line N)`` frame to a line of the test file.

    Prefers the frame of the test proc itself, then the deepest proc defined in the test file.
    """
    frames = [(m.group(1), int(m.group(2))) for m in _PROC_FRAME.finditer(errorinfo)]
    frames = [(name, line) for name, line in frames if name in tf.body_lines]
    for name, line in sorted(frames, key=lambda f: f[0] != test):
        return tf.body_lines[name] + line - 1
    return None


def run_file(tf: TestFile, cfg: RunConfig, index: int) -> FileResult:
    job_file = cfg.workdir / f"job_{index}.tcl"
    results_file = cfg.workdir / f"results_{index}.jsonl"
    job = {
        "test_file": str(tf.path),
        "rel_path": tf.rel,
        "tests": tcl_list(tf.tests),
        "only": "1" if tf.only else "0",
        "filter": cfg.keyword.lower(),
        "instrumented": tcl_dict(cfg.tcl_map),
        "results": str(results_file),
    }
    job_file.write_text(tcl_dict(job), encoding="utf-8")
    result = FileResult(tf.rel)
    start = time.monotonic()
    try:
        proc = subprocess.run(
            [cfg.tclsh, str(harness_path()), str(job_file)],
            cwd=cfg.root,
            stdout=subprocess.PIPE if cfg.capture else None,
            stderr=subprocess.STDOUT if cfg.capture else None,
            stdin=subprocess.DEVNULL,
            timeout=cfg.timeout,
        )
        returncode: int | str = proc.returncode
        result.output = proc.stdout.decode("utf-8", "replace") if proc.stdout else ""
    except subprocess.TimeoutExpired as e:
        returncode = f"timeout after {cfg.timeout}s"
        result.output = e.stdout.decode("utf-8", "replace") if e.stdout else ""
    except OSError as e:
        returncode = f"could not start {cfg.tclsh}: {e}"
    result.duration_ms = int((time.monotonic() - start) * 1000)

    done = False
    if results_file.exists():
        for raw in results_file.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = ev.get("event")
            if kind in ("test", "file_error") and not isinstance(ev.get("line"), int):
                ev["line"] = locate(ev.get("errorinfo", ""), tf, ev.get("name"))
            if kind == "test":
                result.tests.append(
                    TestResult(
                        file=tf.rel,
                        name=ev["name"],
                        status=ev["status"],
                        message=ev.get("message", ""),
                        line=ev["line"] if isinstance(ev.get("line"), int) else None,
                        errorinfo=ev.get("errorinfo", ""),
                        duration_ms=ev.get("duration_ms", 0),
                    )
                )
            elif kind == "file_error":
                result.errors.append(
                    TestResult(
                        file=tf.rel,
                        name="<file>",
                        status=ERROR,
                        message=ev.get("message", ""),
                        line=ev["line"] if isinstance(ev.get("line"), int) else None,
                        errorinfo=ev.get("errorinfo", ""),
                    )
                )
            elif kind == "coverage":
                result.hits = {int(k): v for k, v in ev.get("hits", {}).items()}
            elif kind == "done":
                done = True
    if not done:
        result.errors.append(
            TestResult(
                file=tf.rel,
                name="<file>",
                status=ERROR,
                message=f"tclsh did not finish the test file (exit status {returncode})",
            )
        )
    return result


def run_files(
    files: list[TestFile],
    cfg: RunConfig,
    on_result: Callable[[FileResult], None],
    stop_on_fail: bool = False,
) -> RunResult:
    run = RunResult()
    start = time.monotonic()
    cfg.workdir.mkdir(parents=True, exist_ok=True)

    def results() -> Iterator[FileResult]:
        if cfg.jobs <= 1:
            for i, tf in enumerate(files):
                yield run_file(tf, cfg, i)
            return
        pool = ThreadPoolExecutor(max_workers=cfg.jobs)
        try:
            futures = [pool.submit(run_file, tf, cfg, i) for i, tf in enumerate(files)]
            for fut in futures:
                yield fut.result()
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

    gen = results()
    for fr in gen:
        run.files.append(fr)
        on_result(fr)
        if stop_on_fail and fr.failed:
            gen.close()
            break
    run.duration_ms = int((time.monotonic() - start) * 1000)
    return run
