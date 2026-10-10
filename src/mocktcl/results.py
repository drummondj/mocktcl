"""Result data model shared by the runner and the reporters."""

from __future__ import annotations

from dataclasses import dataclass, field

PASS, FAIL, ERROR, SKIP = "pass", "fail", "error", "skip"


@dataclass
class TestResult:
    __test__ = False  # not a pytest test class

    file: str  # path relative to project root
    name: str
    status: str
    message: str = ""
    line: int | None = None
    errorinfo: str = ""
    duration_ms: int = 0

    @property
    def nodeid(self) -> str:
        return f"{self.file}::{self.name}"


@dataclass
class FileResult:
    file: str
    tests: list[TestResult] = field(default_factory=list)
    errors: list[TestResult] = field(default_factory=list)  # file-level errors (load, hooks, crash)
    output: str = ""  # captured stdout/stderr of the tclsh process
    hits: dict[int, int] = field(default_factory=dict)
    duration_ms: int = 0

    @property
    def failed(self) -> bool:
        return bool(self.errors) or any(t.status in (FAIL, ERROR) for t in self.tests)


@dataclass
class RunResult:
    files: list[FileResult] = field(default_factory=list)
    duration_ms: int = 0

    @property
    def tests(self) -> list[TestResult]:
        return [t for f in self.files for t in f.tests]

    def count(self, status: str) -> int:
        return sum(1 for t in self.tests if t.status == status)

    @property
    def file_errors(self) -> list[TestResult]:
        return [e for f in self.files for e in f.errors]

    @property
    def ok(self) -> bool:
        return not any(f.failed for f in self.files)

    def merged_hits(self) -> dict[int, int]:
        hits: dict[int, int] = {}
        for f in self.files:
            for pid, n in f.hits.items():
                hits[pid] = hits.get(pid, 0) + n
        return hits
