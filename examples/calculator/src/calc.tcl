# A small calculator library used to demonstrate mocktcl.
namespace eval calc {
    variable history {}
}

proc calc::log {msg} {
    variable history
    lappend history "[clock seconds] $msg"
}

proc calc::add {a b} {
    log "add $a $b"
    return [expr {$a + $b}]
}

proc calc::div {a b} {
    if {$b == 0} {
        error "divide by zero"
    }
    log "div $a $b"
    return [expr {double($a) / $b}]
}

proc calc::between {n lo hi} {
    return [expr {$n >= $lo && $n <= $hi}]
}

proc calc::sign {n} {
    if {$n < 0} {
        return negative
    } elseif {$n == 0} {
        return zero
    } else {
        return positive
    }
}

proc calc::describe {n} {
    switch -- $n {
        1 { return one }
        2 { return two }
        3 -
        4 { return "three or four" }
    }
    return "number $n"
}

proc calc::factors {n} {
    set out {}
    for {set i 1} {$i <= $n} {incr i} {
        if {$n % $i == 0} {
            lappend out $i
        }
    }
    return $out
}

proc calc::timestamp {} {
    return [clock format [clock seconds] -format %Y -gmt 1]
}
