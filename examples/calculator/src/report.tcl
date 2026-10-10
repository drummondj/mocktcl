source [file join [file dirname [info script]] calc.tcl]

namespace eval report {}

proc report::summary {numbers} {
    set total 0
    foreach n $numbers {
        set total [calc::add $total $n]
    }
    if {[llength $numbers]} {
        return "total=$total mean=[calc::div $total [llength $numbers]]"
    }
    return "empty"
}

proc report::unused {} {
    return "never called"
}
