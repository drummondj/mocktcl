"""Find test files and the test procs they define."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .tclparse import TclParseError, TclSource

TEST_PREFIX = "test_"


class SelectionError(ValueError):
    pass


@dataclass
class TestFile:
    path: Path  # absolute
    rel: str  # relative to project root, '/'-separated
    tests: list[str]  # statically discovered test procs, definition order
    only: bool = False  # tests is an explicit selection
    body_lines: dict[str, int] = field(default_factory=dict)  # proc name -> line of its body's "{"


def read_source(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def top_level_procs(text: str) -> dict[str, int]:
    """Top-level proc definitions: name -> line of the body's opening brace."""
    try:
        cmds = TclSource(text).parse_script()
    except TclParseError:
        return {}
    procs: dict[str, int] = {}
    for cmd in cmds:
        if cmd.literal(0) in ("proc", "::proc") and len(cmd.words) == 4:
            name = cmd.literal(1)
            if name is None:
                continue
            name = name[2:] if name.startswith("::") else name
            procs.setdefault(name, cmd.words[3].line)
    return procs


def static_tests(text: str) -> list[str]:
    """Names of top-level ``proc test_*`` definitions, in definition order."""
    return [n for n in top_level_procs(text) if n.startswith(TEST_PREFIX) and "::" not in n]


def _walk(directory: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fn in sorted(filenames):
            if fn.startswith(TEST_PREFIX) and fn.endswith(".tcl"):
                found.append(Path(dirpath) / fn)
    return found


def rel_to(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def collect(selectors: list[str], root: Path, keyword: str = "") -> list[TestFile]:
    """Resolve CLI selectors (dirs, files, ``file.tcl::test_name``) to test files."""
    selected: dict[Path, set[str] | None] = {}  # None = all tests in file
    order: list[Path] = []

    def add(path: Path, name: str | None) -> None:
        if path not in selected:
            selected[path] = set() if name else None
            order.append(path)
        current = selected[path]
        if name is None:
            selected[path] = None
        elif current is not None:
            current.add(name)

    for sel in selectors:
        target, _, name = sel.partition("::")
        p = (root / target).resolve() if not os.path.isabs(target) else Path(target).resolve()
        if p.is_dir():
            if name:
                raise SelectionError(f"cannot select a test name in a directory: {sel}")
            for f in _walk(p):
                add(f, None)
        elif p.is_file():
            add(p, name or None)
        else:
            raise SelectionError(f"no such file or directory: {target}")

    kw = keyword.lower()
    files: list[TestFile] = []
    for path in order:
        rel = rel_to(path, root)
        procs = top_level_procs(read_source(path))
        tests = [n for n in procs if n.startswith(TEST_PREFIX) and "::" not in n]
        names = selected[path]
        only = names is not None
        if names is not None:
            tests = [t for t in tests if t in names] + sorted(n for n in names if n not in tests)
        if kw:
            tests = [t for t in tests if kw in f"{rel}::{t}".lower()]
        files.append(TestFile(path, rel, tests, only, procs))
    return files
