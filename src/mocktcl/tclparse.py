"""A forgiving, non-evaluating Tcl tokenizer.

Splits a Tcl script into commands and words, recording absolute character
offsets and line numbers so callers can rewrite the source text in place.
It follows the Tcl syntax rules (see the Tcl(n) man page): command separators,
comments at command start, braced/quoted/bare words, command substitution,
variable substitution, backslash-newline and the ``{*}`` expansion prefix.
"""

from __future__ import annotations

import bisect
from collections.abc import Callable
from dataclasses import dataclass, field

__all__ = ["TclParseError", "Word", "Command", "TclSource"]

_SPACE = " \t\r\f\v"
_WS = _SPACE + "\n"
_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


class TclParseError(ValueError):
    def __init__(self, message: str, offset: int, line: int):
        super().__init__(f"line {line}: {message}")
        self.offset = offset
        self.line = line


@dataclass
class Word:
    kind: str  # "braced" | "quoted" | "bare"
    start: int  # offset of first character (after any {*} prefix)
    end: int  # offset after last character
    content_start: int  # inside braces/quotes; same as start/end for bare
    content_end: int
    line: int
    expand: bool = False
    literal: str | None = None  # value if the word has no substitutions


@dataclass
class Command:
    start: int
    end: int  # offset after the last word
    line: int
    words: list[Word] = field(default_factory=list)
    # (start, end) of the scripts in this command's [command substitutions]
    substs: list[tuple[int, int]] = field(default_factory=list)

    def literal(self, index: int) -> str | None:
        if 0 <= index < len(self.words):
            return self.words[index].literal
        return None


class TclSource:
    """Parser over one source text. All offsets are absolute into ``text``."""

    def __init__(self, text: str):
        self.text = text
        self._line_starts = [0] + [i + 1 for i, c in enumerate(text) if c == "\n"]
        self._substs: list[list[tuple[int, int]]] = []  # stack, one entry per command being parsed

    # -- public API ---------------------------------------------------------

    def line_of(self, offset: int) -> int:
        return bisect.bisect_right(self._line_starts, offset)

    def parse_script(self, start: int = 0, end: int | None = None) -> list[Command]:
        end = len(self.text) if end is None else end
        cmds, pos = self._script(start, end, nested=False)
        return cmds

    def parse_list(self, start: int, end: int) -> list[Word]:
        """Split a Tcl list (e.g. the arm list of ``switch``) into words."""
        words: list[Word] = []
        i = start
        t = self.text
        while True:
            while i < end and (t[i] in _WS or (t[i] == "\\" and i + 1 < end and t[i + 1] == "\n")):
                i += 2 if t[i] == "\\" else 1
            if i >= end:
                return words
            w, i = self._word(i, end, nested=False, list_mode=True)
            words.append(w)

    def expr_operands(self, start: int, end: int) -> list[tuple[int, int]]:
        """(start, end) of each ``&&``/``||`` operand and ``?:`` condition in an expression.

        Everything else in the expression is left opaque. Raises TclParseError on
        anything the scanner doesn't understand.
        """
        self._substs.append([])  # [command substitutions] are skipped, not recorded
        try:
            return _ExprScanner(self, start, end).scan()
        finally:
            self._substs.pop()

    # -- internals ----------------------------------------------------------

    def _error(self, message: str, offset: int) -> TclParseError:
        return TclParseError(message, offset, self.line_of(offset))

    def _script(self, i: int, end: int, nested: bool) -> tuple[list[Command], int]:
        t = self.text
        cmds: list[Command] = []
        while i < end:
            c = t[i]
            if c in _WS or c == ";":
                i += 1
            elif c == "\\" and i + 1 < end and t[i + 1] == "\n":
                i += 2
            elif nested and c == "]":
                return cmds, i
            elif c == "#":
                i = self._comment(i, end)
            else:
                cmd, i = self._command(i, end, nested)
                cmds.append(cmd)
        return cmds, i

    def _comment(self, i: int, end: int) -> int:
        t = self.text
        while i < end:
            c = t[i]
            if c == "\\":
                i += 2
            elif c == "\n":
                return i + 1
            else:
                i += 1
        return end

    def _command(self, i: int, end: int, nested: bool) -> tuple[Command, int]:
        cmd = Command(start=i, end=i, line=self.line_of(i))
        self._substs.append(cmd.substs)
        try:
            return self._command_words(cmd, i, end, nested)
        finally:
            self._substs.pop()

    def _command_words(self, cmd: Command, i: int, end: int, nested: bool) -> tuple[Command, int]:
        t = self.text
        while True:
            while i < end:
                c = t[i]
                if c in _SPACE:
                    i += 1
                elif c == "\\" and i + 1 < end and t[i + 1] == "\n":
                    i += 2
                else:
                    break
            if i >= end:
                break
            c = t[i]
            if c == "\n" or c == ";" or (nested and c == "]"):
                break
            w, i = self._word(i, end, nested)
            cmd.words.append(w)
            cmd.end = w.end
        return cmd, i

    def _word(self, i: int, end: int, nested: bool, list_mode: bool = False) -> tuple[Word, int]:
        t = self.text
        expand = False
        if (
            not list_mode
            and t.startswith("{*}", i)
            and i + 3 < end
            and t[i + 3] not in _WS
            and t[i + 3] != ";"
        ):
            expand = True
            i += 3
        start = i
        line = self.line_of(i)
        c = t[i]
        if c == "{":
            close = self._match_brace(i, end)
            j = close + 1
            self._check_after_close(j, end, nested, list_mode, "close-brace")
            content = t[i + 1 : close]
            return Word("braced", start, j, i + 1, close, line, expand, content), j
        if c == '"':
            j = self._quoted(i, end, list_mode)
            self._check_after_close(j, end, nested, list_mode, "close-quote")
            content = t[i + 1 : j - 1]
            lit = content if list_mode else _literal(content)
            return Word("quoted", start, j, i + 1, j - 1, line, expand, lit), j
        j = self._bare(i, end, nested, list_mode)
        content = t[i:j]
        lit = content if list_mode else _literal(content)
        return Word("bare", start, j, i, j, line, expand, lit), j

    def _check_after_close(self, j: int, end: int, nested: bool, list_mode: bool, what: str) -> None:
        if j >= end:
            return
        c = self.text[j]
        if c in _WS or (not list_mode and c == ";") or (nested and c == "]"):
            return
        if c == "\\" and j + 1 < end and self.text[j + 1] == "\n":
            return
        raise self._error(f"extra characters after {what}", j)

    def _match_brace(self, i: int, end: int) -> int:
        t = self.text
        depth = 0
        j = i
        while j < end:
            c = t[j]
            if c == "\\":
                j += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return j
            j += 1
        raise self._error("missing close-brace", i)

    def _quoted(self, i: int, end: int, list_mode: bool) -> int:
        t = self.text
        j = i + 1
        while j < end:
            c = t[j]
            if c == "\\":
                j += 2
            elif c == '"':
                return j + 1
            elif c == "[" and not list_mode:
                j = self._bracket(j, end)
            else:
                j += 1
        raise self._error('missing "', i)

    def _bracket(self, i: int, end: int) -> int:
        _, k = self._script(i + 1, end, nested=True)
        if k >= end or self.text[k] != "]":
            raise self._error("missing close-bracket", i)
        self._substs[-1].append((i + 1, k))
        return k + 1

    def _bare(self, i: int, end: int, nested: bool, list_mode: bool) -> int:
        t = self.text
        j = i
        while j < end:
            c = t[j]
            if c in _WS:
                break
            if list_mode:
                j += 2 if c == "\\" else 1
                continue
            if c == ";" or (nested and c == "]"):
                break
            if c == "\\":
                if j + 1 < end and t[j + 1] == "\n":
                    break
                j += 2
            elif c == "[":
                j = self._bracket(j, end)
            elif c == "$":
                j = self._variable(j, end)
            else:
                j += 1
        return min(j, end)

    def _variable(self, i: int, end: int) -> int:
        """Skip a ``$`` substitution starting at ``i``; return offset after it."""
        t = self.text
        j = i + 1
        if j < end and t[j] == "{":
            k = t.find("}", j, end)
            if k < 0:
                raise self._error("missing close-brace for variable name", i)
            return k + 1
        while j < end and (t[j].isalnum() or t[j] == "_" or (t[j] == ":" and t.startswith("::", j))):
            j += 2 if t[j] == ":" else 1
        if j < end and t[j] == "(" and j > i + 1:
            j += 1
            while j < end and t[j] != ")":
                c = t[j]
                if c == "\\":
                    j += 2
                elif c == "[":
                    j = self._bracket(j, end)
                elif c == "$":
                    j = self._variable(j, end)
                else:
                    j += 1
            j += 1
        return j


_EXPR_PUNCT = ("&&", "||", "?", ":", "(", ")", ",")
_ATOM = "atom"


class _ExprScanner:
    """Finds the operands of ``?:``, ``||`` and ``&&`` in a Tcl expression (see expr(n)).

    Those are the lowest-precedence operators, so anything between them is one
    opaque operand. Parentheses and function arguments are scanned recursively.
    """

    def __init__(self, src: TclSource, start: int, end: int):
        self.src = src
        self.end = end
        self.tokens = self._tokenize(start, end)
        self.k = 0
        self.spans: list[tuple[int, int]] = []

    def scan(self) -> list[tuple[int, int]]:
        self._ternary()
        if self.k < len(self.tokens):
            raise self._error("unexpected token")
        return self.spans

    def _tokenize(self, i: int, end: int) -> list[tuple[str, int, int]]:
        src, t = self.src, self.src.text
        tokens: list[tuple[str, int, int]] = []
        while i < end:
            c = t[i]
            if c in _WS:
                i += 1
                continue
            if c == "\\" and i + 1 < end and t[i + 1] == "\n":
                i += 2
                continue
            kind, j = _ATOM, i + 1
            if t[i : i + 2] in _EXPR_PUNCT:
                kind, j = t[i : i + 2], i + 2
            elif c in _EXPR_PUNCT:
                kind = c
            elif c == "$":
                j = src._variable(i, end)
            elif c == "[":
                j = src._bracket(i, end)
            elif c == "{":
                j = src._match_brace(i, end) + 1
            elif c == '"':
                j = src._quoted(i, end, list_mode=False)
            elif c.isalnum() or c in "_.":
                while j < end and (t[j].isalnum() or t[j] in "_."):
                    j += 1
            tokens.append((kind, i, j))
            i = j
        return tokens

    def _peek(self) -> str | None:
        return self.tokens[self.k][0] if self.k < len(self.tokens) else None

    def _error(self, message: str) -> TclParseError:
        offset = self.tokens[self.k][1] if self.k < len(self.tokens) else self.end
        return self.src._error(f"expression: {message}", offset)

    def _expect(self, kind: str) -> int:
        if self._peek() != kind:
            raise self._error(f"expected '{kind}'")
        self.k += 1
        return self.tokens[self.k - 1][2]

    # Each rule returns (start, end, compound): compound means the span is itself an
    # &&/|| chain, possibly in parentheses. Only its simple parts get probes.

    def _ternary(self) -> tuple[int, int, bool]:
        start, end, compound = self._or()
        if self._peek() == "?":
            self.spans.append((start, end))
            self.k += 1
            self._ternary()
            self._expect(":")
            _, end, _ = self._ternary()
            compound = False
        return start, end, compound

    def _or(self) -> tuple[int, int, bool]:
        return self._chain("||", self._and)

    def _and(self) -> tuple[int, int, bool]:
        return self._chain("&&", self._operand)

    def _chain(self, op: str, part: Callable[[], tuple[int, int, bool]]) -> tuple[int, int, bool]:
        parts = [part()]
        while self._peek() == op:
            self.k += 1
            parts.append(part())
        if len(parts) == 1:
            return parts[0]
        self.spans.extend((start, end) for start, end, compound in parts if not compound)
        return parts[0][0], parts[-1][1], True

    def _operand(self) -> tuple[int, int, bool]:
        start = end = -1
        groups: list[bool] = []  # per token: is it a parenthesized compound?
        while (kind := self._peek()) is not None and (kind == _ATOM or kind == "("):
            if start < 0:
                start = self.tokens[self.k][1]
            if kind == _ATOM:
                end = self.tokens[self.k][2]
                self.k += 1
                groups.append(False)
                continue
            self.k += 1  # ( of a group or a function's argument list
            args = [] if self._peek() == ")" else [self._ternary()]
            while self._peek() == ",":
                self.k += 1
                args.append(self._ternary())
            end = self._expect(")")
            groups.append(len(args) == 1 and args[0][2])
        if start < 0:
            raise self._error("missing operand")
        return start, end, groups == [True]


def _literal(content: str) -> str | None:
    """Value of a bare/quoted word, or None if it contains substitutions."""
    if "$" in content or "[" in content:
        return None
    if "\\" not in content:
        return content
    out = []
    i = 0
    while i < len(content):
        c = content[i]
        if c == "\\" and i + 1 < len(content):
            n = content[i + 1]
            out.append(_SIMPLE_ESCAPES.get(n, n))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)
