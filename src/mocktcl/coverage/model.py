"""Coverage sources, instrumentation of a whole project, and result model."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..discovery import read_source, rel_to
from ..instrument import FileManifest, ProbeAllocator, instrument

SOURCE_SUFFIXES = (".tcl", ".tm")
ALWAYS_SKIP_DIRS = {"__pycache__", "node_modules", "venv"}


def tcl_normalize(path: Path) -> str:
    """Match Tcl's ``file normalize``: symlinks resolved in all but the last component."""
    path = Path(os.path.abspath(path))
    return str(Path(os.path.realpath(path.parent)) / path.name)


def find_sources(cov_paths: list[Path], root: Path, exclude_dirs: list[Path], omit: list[str]) -> list[Path]:
    excluded = {tcl_normalize(d) for d in exclude_dirs}
    found: dict[str, Path] = {}

    def omitted(p: Path) -> bool:
        rel = rel_to(p, root)
        return any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(p.name, pat) for pat in omit)

    for base in cov_paths:
        base = base if base.is_absolute() else root / base
        if base.is_file():
            if not omitted(base):
                found.setdefault(tcl_normalize(base), base)
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(
                d
                for d in dirnames
                if not d.startswith(".")
                and d not in ALWAYS_SKIP_DIRS
                and tcl_normalize(Path(dirpath) / d) not in excluded
            )
            if tcl_normalize(Path(dirpath)) in excluded:
                continue
            for fn in sorted(filenames):
                p = Path(dirpath) / fn
                if fn.endswith(SOURCE_SUFFIXES) and not omitted(p):
                    found.setdefault(tcl_normalize(p), p)
    return [found[k] for k in sorted(found)]


@dataclass
class InstrumentedProject:
    manifests: dict[str, FileManifest] = field(default_factory=dict)  # rel path -> manifest
    sources: dict[str, str] = field(default_factory=dict)  # rel path -> original text
    tcl_map: dict[str, str] = field(default_factory=dict)  # normalized original -> instrumented copy


def instrument_project(files: list[Path], root: Path, outdir: Path) -> InstrumentedProject:
    alloc = ProbeAllocator()
    project = InstrumentedProject()
    outdir.mkdir(parents=True, exist_ok=True)
    for n, path in enumerate(files):
        rel = rel_to(path, root)
        text = read_source(path)
        new_text, manifest = instrument(text, rel, alloc)
        project.manifests[rel] = manifest
        project.sources[rel] = text
        if manifest.error:
            continue
        copy = outdir / f"{n}_{path.name}"
        copy.write_text(new_text, encoding="utf-8")
        project.tcl_map[tcl_normalize(path)] = str(copy)
    return project


@dataclass
class FileCoverage:
    path: str
    lines: dict[int, int] = field(default_factory=dict)  # line -> hit count
    branches: dict[tuple[int, int, int], int] = field(default_factory=dict)  # (line, block, arm) -> hits
    error: str | None = None

    @property
    def lines_total(self) -> int:
        return len(self.lines)

    @property
    def lines_hit(self) -> int:
        return sum(1 for n in self.lines.values() if n)

    @property
    def branches_total(self) -> int:
        return len(self.branches)

    @property
    def branches_hit(self) -> int:
        return sum(1 for n in self.branches.values() if n)

    @property
    def missing_lines(self) -> list[int]:
        return sorted(line for line, n in self.lines.items() if not n)

    def partial_lines(self) -> set[int]:
        """Lines that were executed but have at least one branch arm never taken."""
        return {line for (line, _, _), n in self.branches.items() if not n and self.lines.get(line)}


def pct(hit: int, total: int) -> float:
    return 100.0 * hit / total if total else 100.0


@dataclass
class CoverageData:
    files: list[FileCoverage]
    sources: dict[str, str]

    @property
    def lines_total(self) -> int:
        return sum(f.lines_total for f in self.files)

    @property
    def lines_hit(self) -> int:
        return sum(f.lines_hit for f in self.files)

    @property
    def branches_total(self) -> int:
        return sum(f.branches_total for f in self.files)

    @property
    def branches_hit(self) -> int:
        return sum(f.branches_hit for f in self.files)

    @property
    def line_percent(self) -> float:
        return pct(self.lines_hit, self.lines_total)


def build_coverage(project: InstrumentedProject, hits: dict[int, int]) -> CoverageData:
    files: list[FileCoverage] = []
    for rel, manifest in project.manifests.items():
        fc = FileCoverage(rel, error=manifest.error)
        for pid, line in manifest.line_probes.items():
            fc.lines[line] = max(fc.lines.get(line, 0), hits.get(pid, 0))
        for pid, key in manifest.branch_probes.items():
            fc.branches[key] = hits.get(pid, 0)
        fc.lines = dict(sorted(fc.lines.items()))
        fc.branches = dict(sorted(fc.branches.items()))
        files.append(fc)
    files.sort(key=lambda f: f.path)
    return CoverageData(files, project.sources)


def line_ranges(lines: list[int]) -> str:
    """[1,2,3,7,9,10] -> '1-3, 7, 9-10'"""
    out: list[str] = []
    start = prev = None
    for n in lines:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(out)
