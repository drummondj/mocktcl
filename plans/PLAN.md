# mocktcl — Implementation Plan

Source of truth for requirements: [SPECIFICATION.md](SPECIFICATION.md).

## Status

- [x] Read specification
- [x] Install Tcl (`tclsh` 8.6.14 via apt `tcl`; dev venv at `.venv` with pytest)
- [x] CLAUDE.md and project skills (`.claude/skills/`)
- [x] Phase 1 — Tcl parser
- [x] Phase 2 — Instrumenter
- [x] Phase 3 — Tcl harness runtime (runner, assertions, mocks, coverage probes)
- [x] Phase 4 — Python runner + CLI
- [x] Phase 5 — Coverage reports (text, lcov, HTML)
- [x] Phase 6 — Examples, end-to-end tests, docs

## Architecture

```
            ┌──────────── Python (mocktcl CLI) ────────────┐
 tests/ ──► │ discovery → instrument sources → spawn tclsh │──► console report
 src .tcl ─►│   (tclparse, instrument)    (runner)         │──► lcov.info / HTML / text
            └───────────────┬──────────────────────────────┘
                            │ per test file: tclsh harness.tcl <job.json-ish args>
                            ▼
            ┌────────── tclsh process (one per test file) ──────────┐
            │ parent interp: harness.tcl (assertions, mock registry,│
            │                coverage counters, result writer)      │
            │   └── child interp: user test file + code under test  │
            │        aliases → expect*, mock, skip, coverage probes │
            └───────────────────────────────────────────────────────┘
```

Key decisions:

1. **One `tclsh` process per test file.** Crash isolation (`exit`, segfaulting
   extensions), clean global state, and trivially parallel (`-j N`).
2. **Parent/child interpreters inside each process.** Test code runs in a child
   interp. Assertions, mock bookkeeping and coverage counters live in the parent
   and are exposed through `interp alias`. A test mocking a built-in like `string`
   or `clock` therefore can't break the framework itself. Prototype showed alias
   errors keep `-errorcode` and an alias probe costs ~0.33µs.
3. **Coverage by source instrumentation done in Python.** Python parses Tcl
   (the 12 rules of the Tcl syntax), finds every command in script positions
   (top level, `proc` bodies, `if`/`while`/`for`/`foreach`/`switch`/`namespace eval`/
   `catch`/`try`/`dict for`/`lmap`/TclOO bodies…), and inserts probes **on the same
   line** (`::mocktcl::_l 17; original command`) so line numbers stay intact.
   Branch probes are inserted at the start of each `if`/`switch` arm, and an
   implicit `else`/`default` arm is appended when missing.
4. **Source interception.** In the child interp `source` is wrapped: if the file
   is in the instrumented set the instrumented text is evaluated (`uplevel 1`,
   `info script` set to the original path, `return` semantics preserved);
   otherwise the real `source` runs. Works for `package require` too, because
   `pkgIndex.tcl` scripts call `source` by name.
5. **Results protocol:** the harness writes JSON lines to a results file whose
   path Python passes on the command line. Test stdout/stderr go to the process
   pipes, are captured by Python, and are shown for failing files (`-s` disables
   capture).

## Package layout

```
pyproject.toml              # console script: mocktcl = mocktcl.cli:main
src/mocktcl/
  __init__.py
  __main__.py               # python -m mocktcl
  cli.py                    # argparse, config, exit codes
  config.py                 # [tool.mocktcl] in pyproject.toml / mocktcl.toml
  discovery.py              # find test files + test procs (definition order)
  tclparse.py               # Tcl tokenizer: commands, words, offsets, lines
  instrument.py             # probe insertion + probe manifest
  runner.py                 # spawn tclsh per file, parse results, parallel
  results.py                # dataclasses: TestResult, FileResult, RunResult
  console.py                # progress + summary output
  coverage/
    __init__.py
    model.py                # merge hits → per-file line/branch data
    text.py                 # terminal table
    lcov.py                 # lcov.info writer
    html.py                 # index + annotated source pages
  tcl/
    harness.tcl             # Tcl runtime (package data)
tests/                      # pytest suite for mocktcl itself
examples/
  calculator/               # sample project: src/*.tcl + tests/ using mocktcl
```

## Phase 1 — Tcl parser (`tclparse.py`)

A parser that follows Tcl's own parsing rules but stays forgiving: it never
evaluates anything and never raises on input `tclsh` would accept.

- `parse_script(text, base_offset=0, base_line=1) -> list[Command]`
- `Command(start, end, line, words: list[Word])`; `Word(kind, start, end,
  content_start, content_end, line)` where kind ∈ `braced | quoted | bare | expand`.
- Rules handled: command separators (`;`, newline), comments only at command
  start (`#` up to an unescaped newline; backslash-newline continues it),
  brace matching with backslash escapes (braces in comments still count, as in Tcl),
  quoted words with nested `[...]`, bare words with `[...]`/`$var`/`${var}`/`$a(idx)`,
  backslash-newline as a word separator, `{*}` expansion prefix.
- `parse_list_words(text, base)`: splits a braced list (used by `switch` arm lists)
  into words with offsets.
- When it hits malformed input (an unbalanced brace) the parser stops at the end
  of the text. The instrumenter then gives up on that file: it is reported as
  not instrumented and is sourced unmodified.

## Phase 2 — Instrumenter (`instrument.py`)

- Input: file path + text. Output: instrumented text plus a `FileManifest`:
  `lines: {probe_id: line}`, `branches: {probe_id: (line, block, arm)}`,
  `executable_lines: set[int]`.
- Probe ids are integers that are unique across the whole run (allocated by a
  `ProbeAllocator`), so hits from all processes merge into one dict.
- Line probe: inserts `::mocktcl::_l <id>; ` immediately before each command in
  a script position.
- Script-position table (`SCRIPT_ARGS`), keyed by command name (leading `::`
  stripped):
  - `proc name args BODY`; `namespace eval ns BODY`; `while c BODY`;
    `for INIT c NEXT BODY`; `foreach … BODY`; `lmap … BODY`; `catch BODY …`;
    `time BODY ?n?`; `dict for|map {k v} d BODY`; `dict with d … BODY`;
    `dict update d k v … BODY`; `uplevel ?level? BODY` (only when its single script arg is braced);
    `eval BODY` (single braced arg); `try BODY ?on/trap … BODY? ?finally BODY?`;
    `if` (custom), `switch` (custom);
    TclOO: `oo::class create Name DEFSCRIPT`, `oo::define Name DEFSCRIPT`,
    and inside definition scripts `method name args BODY`,
    `constructor args BODY`, `destructor BODY`.
- Only braced words are recursed into (quoted/bare bodies are dynamic and are
  left alone).
- Branch coverage:
  - `if`: each arm body gets `::mocktcl::_b <id>; ` at its start. Without an
    `else`, ` else {::mocktcl::_b <id>}` is appended (the probe returns "" so the
    `if` still returns ""). If any arm body isn't braced, branch probes are
    skipped for that `if`.
  - `switch`: handles both forms (inline arms, or a single braced arm list), and the
    options `-exact -glob -regexp -nocase -matchvar -indexvar --`. `-` fall-through
    arms share the next body's arm. If there is no `default` arm, an implicit one
    is appended.
  - Block numbering follows lcov: `BRDA:<line>,<block>,<arm>,<taken>`.

## Phase 3 — Tcl harness (`src/mocktcl/tcl/harness.tcl`)

Invocation: `tclsh harness.tcl <job-file>`. The job file is a Tcl dict written
by Python: `test_file`, `tests` (ordered names), `instrumented` (orig path → instrumented
path), `results`, `project_root`.

Parent interp responsibilities:
- Create the child interp and set up its environment:
  - aliases `::mocktcl::_l`, `::mocktcl::_b` → parent hit counters (return "").
  - assertion wrappers defined in the child, so `info frame -1` gives the
    test-file line; each forwards to a parent alias that compares and raises
    `-errorcode {MOCKTCL ASSERT}`.
  - `mock`, `expect_called` → parent mock registry.
  - `skip reason` → `-errorcode {MOCKTCL SKIP}`.
  - `exit` → raises an error ("exit N called") instead of killing the run.
  - wrap `source` as described in decision 4.
  - `argv0`, `argv`, `argc` and `auto_path` copied over.
- Source the test file in the child. If that errors, emit a `file_error` event.
- Test order: the names Python lists first, then any other `::test_*` procs
  found in the child (sorted).
- Per test: reset mock call counts → `before_each` (if defined) → test →
  `after_each` (always) → restore mocks added during this test (in reverse) →
  emit a result.
  `before_all` / `after_all` run once per file.
- Status classification: `pass`; `fail` (errorcode `MOCKTCL ASSERT`); `skip`;
  `error` (any other error, with errorInfo).
- At the end, emit a `coverage` event with the hit counts.
- JSON is written by a minimal Tcl encoder (string escaping only; numbers
  are written as numbers).

Assertions (all take an optional trailing failure message):

| command | passes when |
|---|---|
| `expect a b` | `a eq b`; or both are numbers, equal as numbers, or (if either is non-integer) within a relative tolerance of 1e-9. If one side is 0, an absolute tolerance is used instead: `float_zero_tolerance`, which defaults to 1e-12 and can be set to 0 for exact comparison. A failed comparison with 0 by a tiny decimal adds a hint. |
| `expect_not a b` | negation of `expect` |
| `expect_near a b tol` (extra) | both are numbers and `abs(a - b) <= tol` |
| `expect_contains s sub` | `sub` is a substring of `s` |
| `expect_list l1 l2` | same multiset of elements, any order |
| `expect_list_contains l1 l2` | every element of `l2` is in `l1` |
| `expect_called mock n` | mock was called exactly `n` times in this test |
| `expect_error script ?pattern?` (extra) | script raises; message matches the glob `pattern` |

Mocking: `mock name argspec body`
- Resolves `name` with `namespace which -command` at the caller's level;
  unqualified names that don't resolve are treated as `::name`.
- If the command exists it is renamed to `::mocktcl::orig::<n>`. A proc is
  created under the original fully qualified name (so it runs in the original
  namespace). Its body starts with a call-count alias and then the user body.
  Works for procs, built-ins (`clock`, `open`, `exec`, `after`…) and commands
  that don't exist yet.
- Mocks made inside a test or `before_each` are restored after the test. Mocks
  made at file level or in `before_all` last for the whole file.
- Not supported (documented): mocking `proc`, `rename`, `namespace`, `uplevel`, `info`,
  `source`, `catch`, and the probe/assertion commands.

## Phase 4 — Python runner + CLI

```
mocktcl [PATHS...] [-k EXPR] [-j N] [-s] [-v|-q] [-x]
        [--tests-dir tests] [--tclsh PATH]
        [--no-cov] [--cov PATH ...] [--cov-omit GLOB ...]
        [--cov-report text|lcov[:file]|html[:dir]] [--fail-under PCT]
```
- PATHS: files, directories, or `file.tcl::test_name`. Defaults to `tests/`.
- Discovery: walk recursively for `test_*.tcl` (sorted). Test procs are found by
  parsing top-level `proc test_*` commands, in definition order.
- `-k`: case-insensitive substring match against `relpath::test_name`.
- Coverage sources: `--cov` paths (default: project root) collect `*.tcl` / `*.tm`,
  minus the tests directory, hidden dirs, `.venv`, and anything matching
  `--cov-omit`. All of them are instrumented up front into a temporary dir, so
  files that are never sourced still show up at 0%.
- Exit codes: 0 all passed; 1 failures/errors or coverage below `--fail-under`;
  2 usage/internal error; 5 no tests collected.
- Config: `[tool.mocktcl]` in `pyproject.toml`, or `mocktcl.toml`, with the
  same keys as the long options (`tests_dir`, `cov`, `cov_omit`, `cov_report`,
  `fail_under`, `tclsh`). CLI overrides config.

Console output (pytest-like): one progress line per file (`tests/test_x.tcl ..F.s`),
then failure details (file:line, assertion message, custom message, captured
output), then a summary line with counts and duration.

## Phase 5 — Coverage reports

- Model: `FileCoverage(path, lines: {line: count}, branches: {(line, block, arm): count})`.
  A line's count is the max over the probes on that line.
- **text**: table of `File | Lines | Miss | Line% | Branches | BrMiss | Branch% | Missing`,
  where Missing lists line ranges such as `12-15, 20`. Last row is TOTAL.
- **lcov**: `TN:`, `SF:`, `DA:`, `LF/LH`, `BRDA`, `BRF/BRH`, `end_of_record`
  (no function records yet; `FN`/`FNDA` from proc probes is a later option).
- **html**: `index.html` with a sortable summary table, plus one page per file
  with line numbers, hit counts, green/red/yellow (partial branch) highlighting, inline CSS,
  and no external assets.

## Phase 6 — Examples, tests, docs

- `examples/calculator/`: `src/calc.tcl` (namespace + procs + if/switch), a
  `tests/` tree with a sub-suite, helpers, fixtures and mocks of a proc and of `clock`.
- pytest suite:
  - `test_tclparse.py`: words/commands/lines/comments/braces/quotes/continuations.
  - `test_instrument.py`: the instrumented code has the same line count as the
    original, `tclsh` gives the same results, and the probe manifest is correct.
  - `test_harness.py`: each assertion pass/fail, mocks (proc, namespaced proc,
    built-in, non-existent, restore between tests), before/after hooks, skip,
    `exit` trapping, file load errors.
  - `test_cli.py`: end-to-end on example projects, exit codes, `-k`, path
    selection, lcov/html output.
- README with usage.

## Out of scope / later

- Expression-level branch coverage (`&&`, `||`, `?:`).
- Coverage for code evaluated from dynamically built strings, or in user-created
  interps or threads.
- Function (proc) coverage records in lcov.
- Watch mode, JUnit XML output (easy to add on top of the results model).
