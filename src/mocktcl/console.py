"""Console progress and summary output."""

from __future__ import annotations

import os
import sys
from typing import TextIO

from .results import ERROR, FAIL, PASS, SKIP, FileResult, RunResult, TestResult

_MARK = {PASS: ".", FAIL: "F", ERROR: "E", SKIP: "s"}
_WORD = {PASS: "PASSED", FAIL: "FAILED", ERROR: "ERROR", SKIP: "SKIPPED"}
_COLOR = {PASS: "32", FAIL: "31", ERROR: "31", SKIP: "33"}


class Console:
    def __init__(self, stream: TextIO = sys.stdout, verbosity: int = 0, color: bool | None = None):
        self.out = stream
        self.verbosity = verbosity
        if color is None:
            color = stream.isatty() and "NO_COLOR" not in os.environ
        self.color = color

    def c(self, text: str, status: str | None = None, code: str | None = None) -> str:
        code = code or (_COLOR.get(status, "") if status else "")
        return f"\x1b[{code}m{text}\x1b[0m" if self.color and code else text

    def write(self, text: str = "") -> None:
        self.out.write(text + "\n")
        self.out.flush()

    def header(self, tcl_version: str, n_files: int) -> None:
        if self.verbosity >= 0:
            s = "" if n_files == 1 else "s"
            self.write(self.c(f"mocktcl: tclsh {tcl_version}, {n_files} test file{s}", code="1"))

    def file_done(self, fr: FileResult) -> None:
        if self.verbosity < 0 or not (fr.tests or fr.errors):
            return
        if self.verbosity >= 1:
            for t in fr.tests:
                extra = f" ({t.message})" if t.status == SKIP and t.message else ""
                self.write(f"{t.nodeid} {self.c(_WORD[t.status], t.status)}{extra}  [{t.duration_ms}ms]")
            for e in fr.errors:
                self.write(f"{fr.file} {self.c('ERROR', ERROR)} {e.message.splitlines()[0] if e.message else ''}")
            return
        marks = "".join(self.c(_MARK[t.status], t.status) for t in fr.tests)
        if fr.errors:
            marks += self.c("E", ERROR)
        self.write(f"{fr.file} {marks}")

    def _detail(self, t: TestResult, fr: FileResult | None, show_info: bool) -> None:
        where = f" (line {t.line})" if t.line else ""
        title = t.nodeid if t.name != "<file>" else t.file
        self.write(self.c(f"___ {title}{where} ___", t.status))
        if not t.errorinfo.startswith(t.message):
            self.write(t.message)
        if show_info and t.errorinfo:
            self.write(t.errorinfo)
        self.write("")

    def summary(self, run: RunResult) -> None:
        problems = [(fr, t) for fr in run.files for t in [*fr.errors, *fr.tests] if t.status in (FAIL, ERROR)]
        if problems and self.verbosity >= -1:
            self.write("")
            self.write(self.c("=" * 25 + " FAILURES " + "=" * 25, FAIL))
            shown_output: set[str] = set()
            for fr, t in problems:
                self._detail(t, fr, show_info=t.status == ERROR)
                if fr.output.strip() and fr.file not in shown_output:
                    shown_output.add(fr.file)
                    self.write(f"--- captured output: {fr.file} ---")
                    self.write(fr.output.rstrip())
                    self.write("")
        counts = [
            (run.count(PASS), "passed", PASS),
            (run.count(FAIL), "failed", FAIL),
            (run.count(ERROR) + len(run.file_errors), "errors" if run.count(ERROR) + len(run.file_errors) != 1 else "error", ERROR),
            (run.count(SKIP), "skipped", SKIP),
        ]
        parts = [self.c(f"{n} {word}", status) for n, word, status in counts if n]
        if not parts:
            parts = ["no tests ran"]
        self.write(f"{', '.join(parts)} in {run.duration_ms / 1000:.2f}s")
