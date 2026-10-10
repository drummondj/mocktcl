"""Self-contained HTML coverage report: index page plus one page per file."""

from __future__ import annotations

import html
import re
from pathlib import Path

from .model import CoverageData, FileCoverage, pct

CSS = """
:root { --bg:#fff; --fg:#1d1d1f; --muted:#6b6b70; --rule:#e2e2e6; --hit:#e3f5e1; --miss:#fbe3e3;
        --part:#fff4cc; --bar:#2e9d4b; --barbg:#f0d6d6; --link:#1a5fb4; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#17171a; --fg:#e8e8ea; --muted:#9a9aa2; --rule:#2c2c31; --hit:#173a1f; --miss:#4a1d1d;
          --part:#47391a; --bar:#3fb862; --barbg:#4a2626; --link:#8ab4f8; } }
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
       font:14px/1.45 system-ui, -apple-system, Segoe UI, sans-serif; }
main { max-width: 1100px; margin: 0 auto; }
h1 { font-size: 20px; margin: 0 0 4px; }
.sub { color: var(--muted); margin-bottom: 20px; }
a { color: var(--link); text-decoration: none; } a:hover { text-decoration: underline; }
.table-wrap { overflow-x: auto; }
table.summary { border-collapse: collapse; width: 100%; }
.summary th, .summary td { padding: 6px 10px; border-bottom: 1px solid var(--rule); text-align: right;
                           white-space: nowrap; font-variant-numeric: tabular-nums; }
.summary th:first-child, .summary td:first-child { text-align: left; }
.summary th { cursor: pointer; user-select: none; color: var(--muted); font-weight: 600; }
.summary tfoot td { font-weight: 600; }
.bar { display:inline-block; width:80px; height:8px; background:var(--barbg); border-radius:4px;
       vertical-align: middle; margin-right: 8px; overflow:hidden; }
.bar span { display:block; height:100%; background:var(--bar); }
pre.src { margin: 0; font: 12.5px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.src-wrap { overflow-x: auto; border: 1px solid var(--rule); border-radius: 6px; }
table.src { border-collapse: collapse; width: 100%; }
.src td { padding: 0 8px; vertical-align: top; }
.src td.n, .src td.c { text-align: right; color: var(--muted); user-select: none;
                       font: 12.5px/1.5 ui-monospace, monospace; white-space: nowrap; }
.src tr.hit td.code { background: var(--hit); }
.src tr.miss td.code { background: var(--miss); }
.src tr.part td.code { background: var(--part); }
.legend span { display:inline-block; padding: 1px 8px; border-radius: 4px; margin-right: 6px; }
"""

SORT_JS = """
document.querySelectorAll('table.summary th').forEach((th, i) => {
  th.addEventListener('click', () => {
    const tbody = th.closest('table').tBodies[0];
    const asc = th.dataset.dir !== 'asc'; th.dataset.dir = asc ? 'asc' : 'desc';
    const key = r => { const c = r.cells[i]; return c.dataset.v !== undefined ? parseFloat(c.dataset.v) : c.textContent; };
    [...tbody.rows].sort((a, b) => { const x = key(a), y = key(b);
      return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1); }).forEach(r => tbody.appendChild(r));
  });
});
"""


def _page(title: str, body: str, script: str = "") -> str:
    js = f"<script>{script}</script>" if script else ""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
        f"<body><main>{body}</main>{js}</body></html>"
    )


def _bar(p: float) -> str:
    return f"<span class='bar'><span style='width:{p:.0f}%'></span></span>"


def _page_name(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", path) + ".html"


def _file_page(f: FileCoverage, source: str) -> str:
    partial = f.partial_lines()
    arms: dict[int, list[int]] = {}
    for (line, _, _), n in f.branches.items():
        arms.setdefault(line, []).append(n)
    rows = []
    for i, text in enumerate(source.splitlines(), start=1):
        cls, count, title = "", "", ""
        if i in f.lines:
            n = f.lines[i]
            count = str(n) if n else "0"
            cls = "miss" if not n else ("part" if i in partial else "hit")
        if i in arms:
            taken = sum(1 for n in arms[i] if n)
            title = f" title='{taken}/{len(arms[i])} branches taken'"
        rows.append(
            f"<tr class='{cls}'{title}><td class='n'>{i}</td><td class='c'>{count}</td>"
            f"<td class='code'><pre class='src'>{html.escape(text) or ' '}</pre></td></tr>"
        )
    lp, bp = pct(f.lines_hit, f.lines_total), pct(f.branches_hit, f.branches_total)
    body = (
        f"<p><a href='index.html'>&larr; All files</a></p><h1>{html.escape(f.path)}</h1>"
        f"<div class='sub'>Lines {f.lines_hit}/{f.lines_total} ({lp:.1f}%) &middot; "
        f"Branches {f.branches_hit}/{f.branches_total} ({bp:.1f}%)</div>"
        "<p class='legend'><span style='background:var(--hit)'>executed</span>"
        "<span style='background:var(--miss)'>not executed</span>"
        "<span style='background:var(--part)'>branch not fully taken</span></p>"
        f"<div class='src-wrap'><table class='src'>{''.join(rows)}</table></div>"
    )
    return _page(f.path, body)


def write(data: CoverageData, outdir: Path) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for f in data.files:
        name = html.escape(f.path)
        if f.error:
            rows.append(f"<tr><td>{name}</td><td colspan='4'>not instrumented: {html.escape(f.error)}</td></tr>")
            continue
        page = _page_name(f.path)
        (outdir / page).write_text(_file_page(f, data.sources.get(f.path, "")), encoding="utf-8")
        lp, bp = pct(f.lines_hit, f.lines_total), pct(f.branches_hit, f.branches_total)
        rows.append(
            f"<tr><td><a href='{page}'>{name}</a></td>"
            f"<td data-v='{lp:.3f}'>{_bar(lp)}{lp:.1f}%</td>"
            f"<td data-v='{f.lines_total - f.lines_hit}'>{f.lines_hit}/{f.lines_total}</td>"
            f"<td data-v='{bp:.3f}'>{bp:.1f}%</td>"
            f"<td data-v='{f.branches_total - f.branches_hit}'>{f.branches_hit}/{f.branches_total}</td></tr>"
        )
    lp = data.line_percent
    bp = pct(data.branches_hit, data.branches_total)
    body = (
        "<h1>Coverage report</h1>"
        f"<div class='sub'>Lines {data.lines_hit}/{data.lines_total} ({lp:.1f}%) &middot; "
        f"Branches {data.branches_hit}/{data.branches_total} ({bp:.1f}%) &middot; generated by mocktcl</div>"
        "<div class='table-wrap'><table class='summary'><thead><tr><th>File</th><th>Lines</th>"
        "<th>Hit/Total</th><th>Branches</th><th>Hit/Total</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        f"<tfoot><tr><td>Total</td><td>{_bar(lp)}{lp:.1f}%</td><td>{data.lines_hit}/{data.lines_total}</td>"
        f"<td>{bp:.1f}%</td><td>{data.branches_hit}/{data.branches_total}</td></tr></tfoot></table></div>"
    )
    index = outdir / "index.html"
    index.write_text(_page("Coverage report", body, SORT_JS), encoding="utf-8")
    return index
