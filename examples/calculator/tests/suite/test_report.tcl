source [file join [file dirname [info script]] .. helpers.tcl]
source [file join [file dirname [info script]] .. fixtures numbers.tcl]
# load_src is our own helper (defined in tests/helpers.tcl), not a mocktcl command.
# It sources a file from the project's src/ folder, wherever mocktcl is run from.
load_src report.tcl

proc before_each {} {
    set ::calls 0
}

proc test_summary {} {
    expect [report::summary [fixture_numbers]] "total=12 mean=4.0"
}

proc test_empty_summary {} {
    expect [report::summary {}] empty
}

proc test_summary_uses_add {} {
    mock calc::add {a b} { incr ::calls; expr {$a + $b} }
    report::summary {1 2 3}
    expect_called calc::add 3
    expect $::calls 3
}
