"""Coverage instrumentation of Tcl source.

Inserts probe commands in front of every command in a script position, plus
branch probes at the start of every ``if``/``switch`` arm. All insertions are
made on the same line as the code they precede, so line numbers never shift.

Probe commands (provided by the harness, both return ""):
    ::mocktcl::_l <id>   line/statement probe
    ::mocktcl::_b <id>   branch-arm probe
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from .tclparse import Command, TclParseError, TclSource, Word

LINE_PROBE = "::mocktcl::_l"
BRANCH_PROBE = "::mocktcl::_b"

SCRIPT = "script"
OO_DEFINE = "oo"

# Resolver: given a command, return [(word_index, context)] of script bodies.
Resolver = Callable[[Command], list[tuple[int, str]]]


def _fixed(n_words: int | tuple[int, ...], *indexes: int, ctx: str = SCRIPT) -> Resolver:
    counts = (n_words,) if isinstance(n_words, int) else n_words

    def resolve(cmd: Command) -> list[tuple[int, str]]:
        if len(cmd.words) not in counts:
            return []
        return [(i if i >= 0 else len(cmd.words) + i, ctx) for i in indexes]

    return resolve


def _foreach(cmd: Command) -> list[tuple[int, str]]:
    n = len(cmd.words)
    return [(n - 1, SCRIPT)] if n >= 4 and n % 2 == 0 else []


def _catch(cmd: Command) -> list[tuple[int, str]]:
    return [(1, SCRIPT)] if 2 <= len(cmd.words) <= 4 else []


def _time(cmd: Command) -> list[tuple[int, str]]:
    return [(1, SCRIPT)] if len(cmd.words) in (2, 3) else []


def _dict(cmd: Command) -> list[tuple[int, str]]:
    sub, n = cmd.literal(1), len(cmd.words)
    if sub in ("for", "map") and n == 5:
        return [(4, SCRIPT)]
    if sub == "with" and n >= 4:
        return [(n - 1, SCRIPT)]
    if sub == "update" and n >= 6 and n % 2 == 0:
        return [(n - 1, SCRIPT)]
    return []


def _namespace(cmd: Command) -> list[tuple[int, str]]:
    return [(3, SCRIPT)] if cmd.literal(1) == "eval" and len(cmd.words) == 4 else []


def _uplevel(cmd: Command) -> list[tuple[int, str]]:
    n = len(cmd.words)
    if n == 2:
        return [(1, SCRIPT)]
    level = cmd.literal(1)
    if n == 3 and level is not None and level.lstrip("#").isdigit():
        return [(2, SCRIPT)]
    return []


def _try(cmd: Command) -> list[tuple[int, str]]:
    n = len(cmd.words)
    if n < 2:
        return []
    out = [(1, SCRIPT)]
    i = 2
    while i < n:
        kw = cmd.literal(i)
        if kw in ("on", "trap") and i + 3 < n:
            if cmd.literal(i + 3) != "-":
                out.append((i + 3, SCRIPT))
            i += 4
        elif kw == "finally" and i + 1 < n:
            out.append((i + 1, SCRIPT))
            i += 2
        else:
            break
    return out


def _oo_class(cmd: Command) -> list[tuple[int, str]]:
    return [(3, OO_DEFINE)] if cmd.literal(1) == "create" and len(cmd.words) == 4 else []


def _oo_method(cmd: Command) -> list[tuple[int, str]]:
    return [(len(cmd.words) - 1, SCRIPT)] if len(cmd.words) >= 4 else []


# Commands whose arguments are scripts, per context.
SCRIPT_ARGS: dict[str, Resolver] = {
    "proc": _fixed(4, 3),
    "while": _fixed(3, 2),
    "for": _fixed(5, 1, 3, 4),
    "foreach": _foreach,
    "lmap": _foreach,
    "catch": _catch,
    "time": _time,
    "dict": _dict,
    "namespace": _namespace,
    "uplevel": _uplevel,
    "eval": _fixed(2, 1),
    "try": _try,
    "oo::class": _oo_class,
    "oo::define": _fixed(3, 2, ctx=OO_DEFINE),
    "oo::objdefine": _fixed(3, 2, ctx=OO_DEFINE),
}

OO_DEFINE_ARGS: dict[str, Resolver] = {
    "method": _oo_method,
    "constructor": _fixed(3, 2),
    "destructor": _fixed(2, 1),
}

CONTEXTS: dict[str, dict[str, Resolver]] = {SCRIPT: SCRIPT_ARGS, OO_DEFINE: OO_DEFINE_ARGS}


@dataclass
class FileManifest:
    path: str
    line_probes: dict[int, int] = field(default_factory=dict)  # probe id -> line
    branch_probes: dict[int, tuple[int, int, int]] = field(default_factory=dict)  # id -> (line, block, arm)
    error: str | None = None

    @property
    def executable_lines(self) -> set[int]:
        return set(self.line_probes.values())


class ProbeAllocator:
    """Hands out probe ids that are unique across all files in a run."""

    def __init__(self, start: int = 1):
        self._next = start

    def take(self) -> int:
        pid = self._next
        self._next += 1
        return pid


class _Instrumenter:
    def __init__(self, text: str, manifest: FileManifest, alloc: ProbeAllocator):
        self.src = TclSource(text)
        self.manifest = manifest
        self.alloc = alloc
        self.inserts: list[tuple[int, int, str]] = []  # (offset, seq, text)
        self.blocks = 0

    def insert(self, offset: int, text: str) -> None:
        self.inserts.append((offset, len(self.inserts), text))

    def script(self, start: int, end: int, ctx: str) -> None:
        for cmd in self.src.parse_script(start, end):
            self.command(cmd, ctx)

    def body(self, word: Word, ctx: str = SCRIPT) -> None:
        if word.kind == "braced" and not word.expand:
            self.script(word.content_start, word.content_end, ctx)

    def command(self, cmd: Command, ctx: str) -> None:
        if ctx == SCRIPT:
            pid = self.alloc.take()
            self.manifest.line_probes[pid] = cmd.line
            self.insert(cmd.start, f"{LINE_PROBE} {pid}; ")
        for start, end in cmd.substs:
            self.script(start, end, SCRIPT)
        if any(w.expand for w in cmd.words):
            return
        name = cmd.literal(0)
        if name is None:
            return
        name = name[2:] if name.startswith("::") else name
        if ctx == SCRIPT and name == "if":
            self.if_command(cmd)
            return
        if ctx == SCRIPT and name == "switch":
            self.switch_command(cmd)
            return
        resolver = CONTEXTS[ctx].get(name)
        if resolver is None:
            return
        for index, body_ctx in resolver(cmd):
            self.body(cmd.words[index], body_ctx)

    # -- branches -----------------------------------------------------------

    def branch_probe(self, line: int, block: int, arm: int) -> str:
        pid = self.alloc.take()
        self.manifest.branch_probes[pid] = (line, block, arm)
        return f"{BRANCH_PROBE} {pid}"

    def arms(self, cmd: Command, bodies: list[Word], has_default: bool, implicit_at: int, implicit_text: str) -> None:
        """Instrument arm bodies; add branch probes when every arm is braced."""
        if all(b.kind == "braced" and not b.expand for b in bodies):
            block = self.blocks
            self.blocks += 1
            for arm, b in enumerate(bodies):
                self.insert(b.content_start, self.branch_probe(cmd.line, block, arm) + "; ")
            if not has_default:
                probe = self.branch_probe(cmd.line, block, len(bodies))
                self.insert(implicit_at, implicit_text.format(probe=probe))
        for b in bodies:
            self.body(b)

    def if_command(self, cmd: Command) -> None:
        words, n = cmd.words, len(cmd.words)
        bodies: list[Word] = []
        has_else = False
        i = 1
        while True:
            i += 1  # skip condition
            if i < n and cmd.literal(i) == "then":
                i += 1
            if i >= n:
                return  # malformed
            bodies.append(words[i])
            i += 1
            if i >= n:
                break
            kw = cmd.literal(i)
            if kw == "elseif":
                i += 1  # now at the condition, skipped at the top of the loop
                continue
            if kw == "else":
                i += 1
            if i >= n:
                return  # malformed
            bodies.append(words[i])
            has_else = True
            i += 1
            break
        if i != n:
            return
        self.arms(cmd, bodies, has_else, cmd.end, " else {{{probe}}}")

    def switch_command(self, cmd: Command) -> None:
        words, n = cmd.words, len(cmd.words)
        i = 1
        while i < n:
            opt = cmd.literal(i)
            if opt is None or not opt.startswith("-") or i == n - 2:
                break
            i += 1
            if opt == "--":
                break
            if opt in ("-matchvar", "-indexvar"):
                i += 1
        i += 1  # skip the string being matched
        remaining = n - i
        if remaining == 1:
            arm_list = words[i]
            if arm_list.kind != "braced":
                return
            pairs = self.src.parse_list(arm_list.content_start, arm_list.content_end)
            implicit_at = arm_list.content_end
        elif remaining >= 2:
            pairs = words[i:]
            implicit_at = cmd.end
        else:
            return
        if len(pairs) % 2:
            return
        bodies = [pairs[k + 1] for k in range(0, len(pairs), 2) if pairs[k + 1].literal != "-"]
        has_default = pairs[-2].literal == "default" if pairs else False
        self.arms(cmd, bodies, has_default, implicit_at, " default {{{probe}}}")

    # -- output -------------------------------------------------------------

    def render(self) -> str:
        text = self.src.text
        out: list[str] = []
        pos = 0
        for offset, _, snippet in sorted(self.inserts):
            out.append(text[pos:offset])
            out.append(snippet)
            pos = offset
        out.append(text[pos:])
        return "".join(out)


def instrument(text: str, path: str, alloc: ProbeAllocator | None = None) -> tuple[str, FileManifest]:
    """Return (instrumented_text, manifest). On parse errors the text is unchanged."""
    alloc = alloc or ProbeAllocator()
    manifest = FileManifest(path)
    inst = _Instrumenter(text, manifest, alloc)
    try:
        inst.script(0, len(text), SCRIPT)
    except TclParseError as e:
        return text, FileManifest(path, error=str(e))
    return inst.render(), manifest


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m mocktcl.instrument FILE.tcl", file=sys.stderr)
        return 2
    with open(argv[0], encoding="utf-8") as f:
        text, manifest = instrument(f.read(), argv[0])
    if manifest.error:
        print(f"parse error: {manifest.error}", file=sys.stderr)
        return 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
