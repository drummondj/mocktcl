source [file join [file dirname [info script]] helpers.tcl]
# load_src is our own helper (defined in tests/helpers.tcl), not a mocktcl command.
# It sources a file from the project's src/ folder, wherever mocktcl is run from.
load_src calc.tcl

proc test_add {} {
    expect [calc::add 1 2] 3
    expect_not [calc::add 1 2] 4
}

proc test_div {} {
    expect [calc::div 6 3] 2.0
    expect [calc::div 6 3] 2 "numeric comparison"
    expect_error {calc::div 1 0} "*divide by zero*"
}

proc test_sign {} {
    expect [calc::sign -5] negative
    expect [calc::sign 0] zero
}

proc test_describe {} {
    expect [calc::describe 1] one
    expect_contains [calc::describe 4] "four"
}

proc test_factors {} {
    expect_list [calc::factors 12] {12 6 4 3 2 1}
    expect_list_contains [calc::factors 12] {2 3}
}

proc test_log_is_mocked {} {
    mock calc::log {msg} { return "" }
    calc::add 1 1
    calc::add 2 2
    expect_called calc::log 2
}

proc test_clock_is_mocked {} {
    mock clock {args} {
        if {[lindex $args 0] eq "seconds"} { return 0 }
        return 1970
    }
    expect [calc::timestamp] 1970
}

proc test_log_restored_after_mock {} {
    calc::add 5 5
    expect_contains [lindex $calc::history end] "add 5 5"
}

proc test_skipped {} {
    skip "demonstrates skip"
}
