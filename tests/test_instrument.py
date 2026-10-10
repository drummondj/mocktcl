import textwrap

import pytest

from mocktcl.instrument import ProbeAllocator, instrument

from .conftest import requires_tcl, tcl_eval

PROBES = """
namespace eval ::mocktcl {}
array set ::H {}
proc ::mocktcl::_l {id} { incr ::H($id); return }
proc ::mocktcl::_b {id} { incr ::H($id); return }
"""


def inst(script: str):
    return instrument(textwrap.dedent(script).lstrip("\n"), "x.tcl", ProbeAllocator())


def run_both(script: str) -> tuple[str, str, dict[int, int]]:
    """Run original and instrumented script; return (orig_out, inst_out, hits)."""
    script = textwrap.dedent(script).lstrip("\n")
    text, manifest = instrument(script, "x.tcl")
    assert manifest.error is None
    original = tcl_eval(script)
    dump = "\nputs ::HITS:[array get ::H]"
    out = tcl_eval(PROBES + text + dump)
    out, _, hits = out.rpartition("::HITS:")
    words = hits.split()
    return original, out.strip(), {int(words[i]): int(words[i + 1]) for i in range(0, len(words), 2)}


SAMPLE = """
namespace eval calc {
    proc classify {n} {
        if {$n < 0} {
            return negative
        } elseif {$n == 0} { return zero }
        switch -glob -- $n {
            1* { set r one }
            2* -
            3* { set r twothree }
        }
        set out {}
        foreach i {1 2} { lappend out $i }
        for {set i 0} {$i < 2} {incr i} { lappend out $i }
        while {0} { break }
        catch { lappend out c }
        try { lappend out t } on error {e} { lappend out e } finally { lappend out f }
        dict for {k v} {a 1} { lappend out $k }
        return [list $out [expr {$n > 10 ? "big" : "small"}]]
    }
}
puts [calc::classify 5]
puts [calc::classify 25]
puts [calc::classify -1]
"""


def test_line_count_is_preserved():
    text, _ = inst(SAMPLE)
    assert text.count("\n") == textwrap.dedent(SAMPLE).lstrip("\n").count("\n")


def test_probes_are_on_same_line_as_commands():
    text, manifest = inst(SAMPLE)
    lines = text.splitlines()
    for pid, line in manifest.line_probes.items():
        assert f"::mocktcl::_l {pid};" in lines[line - 1]


def test_executable_lines():
    _, manifest = inst(SAMPLE)
    # Every line holding a command, including those inside nested bodies.
    assert manifest.executable_lines == {1, 2, 3, 4, 5, 6, 7, 9, 11, 12, 13, 14, 15, 16, 17, 18, 21, 22, 23}


def test_branch_blocks():
    _, manifest = inst(SAMPLE)
    arms = sorted(manifest.branch_probes.values())
    # if: then, elseif, implicit else; switch: 1*, 2*/3*, implicit default
    assert arms == [(3, 0, 0), (3, 0, 1), (3, 0, 2), (6, 1, 0), (6, 1, 1), (6, 1, 2)]


@requires_tcl
def test_instrumented_code_behaves_identically():
    original, instrumented, hits = run_both(SAMPLE)
    assert original == instrumented


@requires_tcl
def test_branch_hits():
    script = """
    proc f {x} {
        if {$x} { return a }
        return b
    }
    f 1; f 1; f 0
    """
    _, _, hits = run_both(script)
    _, manifest = inst(script)
    by_arm = {arm: hits.get(pid, 0) for pid, (_, _, arm) in manifest.branch_probes.items()}
    assert by_arm == {0: 2, 1: 1}


@requires_tcl
def test_if_without_else_still_returns_empty():
    original, instrumented, _ = run_both('puts "<[if {0} {set x 1}]>"')
    assert original == instrumented == "<>"


@requires_tcl
def test_switch_without_default_still_returns_empty():
    original, instrumented, _ = run_both('puts "<[switch x {a {set y 1}}]>"')
    assert original == instrumented == "<>"


@requires_tcl
def test_empty_bodies():
    original, instrumented, _ = run_both('proc f {} {}\nputs "<[f]>[if 1 {}]"')
    assert original == instrumented


@requires_tcl
def test_if_with_then_and_implicit_else_keyword():
    script = 'puts [if {0} then {set a 1} {set a 2}]'
    original, instrumented, _ = run_both(script)
    assert original == instrumented == "2"
    _, manifest = inst(script)
    assert len(manifest.branch_probes) == 2  # explicit arms only


@requires_tcl
def test_switch_inline_form_and_options():
    script = """
    proc g {v} { switch -regexp -matchvar m -- $v {^a(.)$} {return [lindex $m 1]} default {return none} }
    puts [g ab][g zz]
    """
    original, instrumented, _ = run_both(script)
    assert original == instrumented == "bnone"


@requires_tcl
def test_tcloo_methods_are_instrumented():
    script = """
    oo::class create Counter {
        variable n
        constructor {} { set n 0 }
        method incr {} {
            incr n
            return $n
        }
    }
    set c [Counter new]
    $c incr
    puts [$c incr]
    """
    original, instrumented, hits = run_both(script)
    assert original == instrumented == "2"
    _, manifest = inst(script)
    assert {3, 5, 6} <= manifest.executable_lines
    covered = {manifest.line_probes[p] for p in hits if p in manifest.line_probes}
    assert {3, 5, 6} <= covered


@requires_tcl
def test_return_from_sourced_toplevel_and_uplevel():
    script = """
    proc outer {} { set v 1; inner; return $v }
    proc inner {} { uplevel 1 { set v 2 } }
    puts [outer]
    """
    original, instrumented, _ = run_both(script)
    assert original == instrumented == "2"


def test_data_arguments_are_not_instrumented():
    text, _ = inst("set body {puts hi}\nlist {a b} {c d}\n")
    assert text.count("::mocktcl::_l") == 2


def test_dynamic_bodies_are_skipped():
    text, manifest = inst("if $cond $body\nproc f args $b\n")
    assert len(manifest.branch_probes) == 0
    assert text.count("::mocktcl::_l") == 2


def test_parse_error_returns_original_text():
    src = "proc f {} {\n"
    text, manifest = inst(src)
    assert text == src
    assert manifest.error and "close-brace" in manifest.error


def test_probe_ids_unique_across_files():
    alloc = ProbeAllocator()
    _, m1 = instrument("set a 1\nset b 2\n", "a.tcl", alloc)
    _, m2 = instrument("set c 3\n", "b.tcl", alloc)
    assert not set(m1.line_probes) & set(m2.line_probes)


@pytest.mark.parametrize(
    "script",
    [
        "dict with d { set a 1 }",
        "dict update d k v { set v 1 }",
        "lmap x {1 2} { expr {$x * 2} }",
        "time { set a 1 } 10",
        "namespace eval ns { variable x 1 }",
        "uplevel #0 { set a 1 }",
        "eval { set a 1 }",
    ],
)
def test_other_script_commands_are_recursed(script):
    _, manifest = inst(script)
    assert len(manifest.line_probes) == 2


@requires_tcl
def test_command_substitutions_are_instrumented():
    script = """
    proc pick {a} {
        set r [if {$a} {list yes} else {list no}]
        set n [catch {
            error oops
        } msg]
        return "$r $n $msg [lmap x {1 2} {
            expr {$x * 2}
        }]"
    }
    puts [pick 1]
    """
    original, instrumented, hits = run_both(script)
    assert original == instrumented == "yes 1 oops 2 4"
    _, manifest = inst(script)
    assert {4, 7} <= manifest.executable_lines
    assert len(manifest.branch_probes) == 2
    covered = {manifest.line_probes[p] for p in hits if p in manifest.line_probes}
    assert {4, 7} <= covered
