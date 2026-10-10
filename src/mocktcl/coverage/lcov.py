"""lcov tracefile (lcov.info) writer."""

from __future__ import annotations

from pathlib import Path

from .model import CoverageData


def render(data: CoverageData, root: Path, test_name: str = "") -> str:
    out: list[str] = []
    for f in data.files:
        if f.error:
            continue
        out.append(f"TN:{test_name}")
        out.append(f"SF:{(root / f.path).as_posix()}")
        for (line, block, arm), n in f.branches.items():
            taken = str(n) if f.lines.get(line) else "-"
            out.append(f"BRDA:{line},{block},{arm},{taken}")
        out.append(f"BRF:{f.branches_total}")
        out.append(f"BRH:{f.branches_hit}")
        for line, n in f.lines.items():
            out.append(f"DA:{line},{n}")
        out.append(f"LF:{f.lines_total}")
        out.append(f"LH:{f.lines_hit}")
        out.append("end_of_record")
    return "\n".join(out) + ("\n" if out else "")


def write(data: CoverageData, root: Path, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(data, root), encoding="utf-8")
