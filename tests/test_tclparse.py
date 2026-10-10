import pytest

from mocktcl.tclparse import TclParseError, TclSource


def words(script: str) -> list[list[str]]:
    src = TclSource(script)
    return [[script[w.start : w.end] for w in c.words] for c in src.parse_script()]


def test_simple_commands_and_separators():
    assert words("set a 1; set b 2\nputs $a") == [["set", "a", "1"], ["set", "b", "2"], ["puts", "$a"]]


def test_comments_only_at_command_start():
    assert words("# comment ; not a command\nset x #notcomment") == [["set", "x", "#notcomment"]]
    assert words("set a 1 ;# trailing comment\nset b 2") == [["set", "a", "1"], ["set", "b", "2"]]


def test_comment_continued_with_backslash_newline():
    assert words("# comment \\\n still comment\nset a 1") == [["set", "a", "1"]]


def test_braced_words_nest_and_span_lines():
    assert words("proc f {a b} {\n  if {$a} { return {x} }\n}") == [
        ["proc", "f", "{a b}", "{\n  if {$a} { return {x} }\n}"]
    ]


def test_braces_in_comments_still_count_inside_braces():
    # Tcl counts braces even inside comments when matching a braced word.
    assert words("proc f {} {\n # {\n set x 1\n # }\n}") == [["proc", "f", "{}", "{\n # {\n set x 1\n # }\n}"]]


def test_escaped_braces():
    assert words(r"set a \{ ; set b {a\}b}") == [["set", "a", r"\{"], ["set", "b", r"{a\}b}"]]


def test_quoted_words_with_command_substitution():
    assert words('puts "a [list b "c d"] e"; set x 1') == [["puts", '"a [list b "c d"] e"'], ["set", "x", "1"]]


def test_bare_word_with_brackets_containing_spaces_and_semicolons():
    assert words("set x [foo a; bar b]x\nset y 2") == [["set", "x", "[foo a; bar b]x"], ["set", "y", "2"]]


def test_variable_forms():
    assert words("puts ${a b}c $arr(x[y z]) $::ns::v") == [["puts", "${a b}c", "$arr(x[y z])", "$::ns::v"]]


def test_backslash_newline_separates_words():
    assert words("set a \\\n   1\nset b 2") == [["set", "a", "1"], ["set", "b", "2"]]


def test_expand_prefix():
    src = TclSource("list {*}$args {*}")
    cmd = src.parse_script()[0]
    assert [w.expand for w in cmd.words] == [False, True, False]


def test_line_numbers():
    src = TclSource("set a 1\n\nproc f {} {\n  return 1\n}\nf")
    cmds = src.parse_script()
    assert [c.line for c in cmds] == [1, 3, 6]
    body = cmds[1].words[3]
    inner = src.parse_script(body.content_start, body.content_end)
    assert [c.line for c in inner] == [4]


def test_literals():
    src = TclSource('set "a b" {c d} e\\ f $g [h]')
    cmd = src.parse_script()[0]
    assert [w.literal for w in cmd.words] == ["set", "a b", "c d", "e f", None, None]


def test_parse_list():
    text = '{1 2} { a } "b c" -  d'
    src = TclSource(text)
    assert [w.literal for w in src.parse_list(0, len(text))] == ["1 2", " a ", "b c", "-", "d"]


@pytest.mark.parametrize("bad", ["proc f {} {", 'puts "abc', "set x [foo", "set x {a}b"])
def test_malformed_input_raises(bad):
    with pytest.raises(TclParseError):
        TclSource(bad).parse_script()
