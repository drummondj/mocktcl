"""Terminal coverage table."""

from __future__ import annotations

from .model import CoverageData, line_ranges, pct


def render(data: CoverageData, show_missing: bool = True) -> str:
    header = ["File", "Lines", "Miss", "Line%", "Branches", "BrMiss", "Branch%"]
    if show_missing:
        header.append("Missing")
    rows: list[list[str]] = []
    for f in data.files:
        if f.error:
            row = [f.path, "-", "-", "-", "-", "-", "-"]
            if show_missing:
                row.append(f"not instrumented: {f.error}")
            rows.append(row)
            continue
        row = [
            f.path,
            str(f.lines_total),
            str(f.lines_total - f.lines_hit),
            f"{pct(f.lines_hit, f.lines_total):.1f}%",
            str(f.branches_total),
            str(f.branches_total - f.branches_hit),
            f"{pct(f.branches_hit, f.branches_total):.1f}%",
        ]
        if show_missing:
            row.append(line_ranges(f.missing_lines))
        rows.append(row)
    total = [
        "TOTAL",
        str(data.lines_total),
        str(data.lines_total - data.lines_hit),
        f"{data.line_percent:.1f}%",
        str(data.branches_total),
        str(data.branches_total - data.branches_hit),
        f"{pct(data.branches_hit, data.branches_total):.1f}%",
    ]
    if show_missing:
        total.append("")

    table = [header, *rows, total]
    widths = [max(len(r[i]) for r in table) for i in range(len(header))]
    numeric = range(1, 7)

    def fmt(r: list[str]) -> str:
        cells = [c.rjust(widths[i]) if i in numeric else c.ljust(widths[i]) for i, c in enumerate(r)]
        return "  ".join(cells).rstrip()

    rule = "-" * len(fmt(header))
    lines = [fmt(header), rule, *(fmt(r) for r in rows), rule, fmt(total)]
    return "\n".join(lines) + "\n"
