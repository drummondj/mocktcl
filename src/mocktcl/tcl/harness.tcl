# mocktcl harness: runs the tests of one test file.
#
# Usage: tclsh harness.tcl JOBFILE
#
# JOBFILE holds a Tcl dict written by the Python runner:
#   test_file     absolute path of the test file
#   rel_path      path shown in reports
#   tests         ordered list of statically discovered test procs to run
#   only          1 if `tests` is an explicit selection (no dynamic extras)
#   filter        -k substring filter (lower case), or ""
#   instrumented  dict: normalized source path -> instrumented copy
#   results       path of the JSON-lines results file to write
#
# The parent interpreter (this file) owns assertions, mock bookkeeping and
# coverage counters. Test code runs in a child interpreter and reaches the
# parent through aliases, so mocking built-ins can't break the framework.

namespace eval ::mocktcl {
    variable job
    variable child
    variable out
    variable hits
    array set hits {}
    variable mocks {}       ;# stack of {fq saved}
    variable counts {}      ;# fq -> call count in the current test
    variable calls {}       ;# fq -> list of argument lists in the current test
    variable saved_seq 0
    variable sources {}     ;# normalized path -> instrumented text (cache)
}

# --- results output --------------------------------------------------------

proc ::mocktcl::json {s} {
    set s [string map [list \\ \\\\ \" \\\" \n \\n \r \\r \t \\t] $s]
    if {[regexp {[\x00-\x1f]} $s]} {
        set buf ""
        foreach ch [split $s ""] {
            scan $ch %c code
            if {$code < 32} {
                append buf [format \\u%04x $code]
            } else {
                append buf $ch
            }
        }
        set s $buf
    }
    return "\"$s\""
}

# emit KEY VALUE ... ; keys listed in `numeric` are written as JSON numbers.
proc ::mocktcl::emit {args} {
    variable out
    set numeric {line duration_ms}
    set parts {}
    foreach {k v} $args {
        if {$k in $numeric && [string is entier -strict $v]} {
            lappend parts "[json $k]:$v"
        } else {
            lappend parts "[json $k]:[json $v]"
        }
    }
    puts $out "{[join $parts ,]}"
    flush $out
}

proc ::mocktcl::emit_coverage {} {
    variable out
    variable hits
    set parts {}
    foreach id [array names hits] {
        lappend parts "\"$id\":$hits($id)"
    }
    puts $out "{\"event\":\"coverage\",\"hits\":{[join $parts ,]}}"
    flush $out
}

# --- coverage probes -------------------------------------------------------

proc ::mocktcl::hit {id} {
    variable hits
    incr hits($id)
    return
}

proc ::mocktcl::instrumented {path} {
    variable job
    variable sources
    if {[dict exists $sources $path]} {
        return [list 1 [dict get $sources $path]]
    }
    set map [dict get $job instrumented]
    if {![dict exists $map $path]} {
        return {}
    }
    set f [open [dict get $map $path]]
    fconfigure $f -encoding utf-8
    set text [read $f]
    close $f
    dict set sources $path $text
    return [list 1 $text]
}

# --- assertions ------------------------------------------------------------

proc ::mocktcl::show {v} {
    if {[string length $v] > 200} {
        set v "[string range $v 0 196]..."
    }
    return "\"$v\""
}

# Floating-point values that differ by less than this fraction of the larger
# one are treated as equal, so rounding noise such as 10 * 0.66 giving
# 6.6000000000000005 doesn't fail `expect ... 6.6`.
set ::mocktcl::float_rel_tol 1e-9

# A number Tcl can do arithmetic with: rejects text and NaN (Inf is allowed).
proc ::mocktcl::number {x} {
    return [expr {[string is double -strict $x] && ![catch {expr {double($x)}}]}]
}

proc ::mocktcl::finite {x} {
    return [expr {abs(double($x)) <= 1.7976931348623157e308}]
}

# Equality used by expect/expect_not: exact for strings and integers,
# within a relative tolerance when either value is a non-integer number.
proc ::mocktcl::equal {a b} {
    if {$a eq $b} {
        return 1
    }
    if {![number $a] || ![number $b]} {
        return 0
    }
    if {$a == $b} {
        return 1
    }
    if {[string is entier -strict $a] && [string is entier -strict $b]} {
        return 0
    }
    if {![finite $a] || ![finite $b]} {
        return 0
    }
    set tol [expr {$::mocktcl::float_rel_tol * max(abs(double($a)), abs(double($b)))}]
    return [expr {abs($a - $b) <= $tol}]
}

proc ::mocktcl::usage {kind syntax frame} {
    return -code error -errorcode [list MOCKTCL USAGE $frame] \
        "wrong # args: should be \"$kind $syntax\""
}

# Each check returns "" on success or a failure description.
proc ::mocktcl::check_expect {actual expected} {
    if {[equal $actual $expected]} {
        return ""
    }
    return "expected [show $expected] but got [show $actual]"
}

proc ::mocktcl::check_expect_not {actual unexpected} {
    if {![equal $actual $unexpected]} {
        return ""
    }
    return "expected value other than [show $unexpected]"
}

proc ::mocktcl::check_expect_near {actual expected tolerance} {
    foreach {name v} [list actual $actual expected $expected tolerance $tolerance] {
        if {![number $v]} {
            error "$name must be a number but got \"$v\""
        }
    }
    if {$tolerance < 0} {
        error "tolerance must not be negative but got \"$tolerance\""
    }
    set diff [expr {abs($actual - $expected)}]
    # Allow for rounding noise in the subtraction itself, so values exactly on
    # the boundary (6.601 vs 6.6 +/- 0.001) pass.
    set noise [expr {$::mocktcl::float_rel_tol * max(abs(double($actual)), abs(double($expected)))}]
    if {$diff <= $tolerance + $noise} {
        return ""
    }
    return "expected [show $expected] +/- $tolerance but got [show $actual] (difference [format %.6g $diff])"
}

proc ::mocktcl::check_expect_contains {haystack needle} {
    if {[string first $needle $haystack] >= 0} {
        return ""
    }
    return "expected [show $haystack] to contain [show $needle]"
}

proc ::mocktcl::check_expect_list {actual expected} {
    if {[catch {llength $actual}] || [catch {llength $expected}]} {
        return "arguments are not valid lists"
    }
    if {[lsort $actual] eq [lsort $expected]} {
        return ""
    }
    set missing {}
    set rest $actual
    foreach e $expected {
        set i [lsearch -exact $rest $e]
        if {$i < 0} {
            lappend missing $e
        } else {
            set rest [lreplace $rest $i $i]
        }
    }
    set msg "expected list with elements [show $expected] but got [show $actual]"
    if {[llength $missing]} {
        append msg "; missing: [show $missing]"
    }
    if {[llength $rest]} {
        append msg "; unexpected: [show $rest]"
    }
    return $msg
}

proc ::mocktcl::check_expect_list_contains {actual subset} {
    if {[catch {llength $actual}] || [catch {llength $subset}]} {
        return "arguments are not valid lists"
    }
    set missing {}
    foreach e $subset {
        if {[lsearch -exact $actual $e] < 0} {
            lappend missing $e
        }
    }
    if {![llength $missing]} {
        return ""
    }
    return "expected [show $actual] to contain [show $subset]; missing: [show $missing]"
}

proc ::mocktcl::check_expect_called {fq n} {
    variable counts
    variable mocks
    set mocked 0
    foreach m $mocks {
        if {[lindex $m 0] eq $fq} {
            set mocked 1
        }
    }
    if {!$mocked} {
        return "[show $fq] is not a mock"
    }
    if {![string is entier -strict $n]} {
        error "expected integer call count but got \"$n\""
    }
    set actual [expr {[dict exists $counts $fq] ? [dict get $counts $fq] : 0}]
    if {$actual == $n} {
        return ""
    }
    set s [expr {$n == 1 ? "" : "s"}]
    return "expected $fq to be called $n time$s but it was called $actual"
}

proc ::mocktcl::check_expect_error {rc result pattern} {
    if {$rc != 1} {
        return "expected an error but the script returned [show $result]"
    }
    if {[string match $pattern $result]} {
        return ""
    }
    return "expected error matching [show $pattern] but got [show $result]"
}

# Assertion entry point (aliased into the child).
# Usage from child wrappers: _assert KIND FRAME ARGS...
proc ::mocktcl::assert {kind frame args} {
    set arity [dict get {
        expect 2 expect_not 2 expect_near 3 expect_contains 2 expect_list 2
        expect_list_contains 2 expect_called 2 expect_error 3
    } $kind]
    set n [llength $args]
    if {$n != $arity && $n != $arity + 1} {
        set syntax [dict get {
            expect "actual expected ?message?"
            expect_not "actual unexpected ?message?"
            expect_near "actual expected tolerance ?message?"
            expect_contains "string substring ?message?"
            expect_list "list1 list2 ?message?"
            expect_list_contains "list subset ?message?"
            expect_called "mock count ?message?"
            expect_error "script ?pattern? ?message?"
        } $kind]
        usage $kind $syntax $frame
    }
    if {[catch {check_$kind {*}[lrange $args 0 $arity-1]} failure]} {
        return -code error -errorcode [list MOCKTCL USAGE $frame] "$kind: $failure"
    }
    if {$failure eq ""} {
        return
    }
    if {$n > $arity && [lindex $args end] ne ""} {
        set failure "[lindex $args end]\n$failure"
    }
    return -code error -errorcode [list MOCKTCL ASSERT $frame] "$kind failed: $failure"
}

# --- mocks -----------------------------------------------------------------

proc ::mocktcl::qualify {name} {
    if {[string match ::* $name]} {
        return $name
    }
    return ::$name
}

proc ::mocktcl::mock {name fq params body} {
    variable child
    variable mocks
    variable saved_seq
    if {$fq eq ""} {
        set fq [qualify $name]
        set saved ""
        set ns [namespace qualifiers $fq]
        if {$ns ne ""} {
            $child eval [list namespace eval $ns {}]
        }
    } else {
        set saved ::mocktcl::orig::[incr saved_seq]
        $child eval [list rename $fq $saved]
    }
    lappend mocks [list $fq $saved]
    # The call recorder shares the first line with the body so mock line
    # numbers in error traces match the user's source.
    set recorder "::mocktcl::_called [list $fq] \[info level 0\];"
    if {[catch {$child eval [list proc $fq $params "$recorder$body"]} err]} {
        restore_mocks [expr {[llength $mocks] - 1}]
        return -code error -errorcode {MOCKTCL USAGE} "cannot mock $fq: $err"
    }
    return
}

proc ::mocktcl::called {fq cmdline} {
    variable counts
    variable calls
    dict incr counts $fq
    dict lappend calls $fq [lrange $cmdline 1 end]
    return
}

proc ::mocktcl::mock_calls {fq} {
    variable calls
    if {[dict exists $calls $fq]} {
        return [dict get $calls $fq]
    }
    return {}
}

# Undo mocks until only `keep` remain on the stack.
proc ::mocktcl::restore_mocks {keep} {
    variable child
    variable mocks
    while {[llength $mocks] > $keep} {
        lassign [lindex $mocks end] fq saved
        set mocks [lrange $mocks 0 end-1]
        catch {$child eval [list rename $fq ""]}
        if {$saved ne ""} {
            catch {$child eval [list rename $saved $fq]}
        }
    }
}

proc ::mocktcl::child_exit {{code 0}} {
    return -code error -errorcode [list MOCKTCL EXIT $code] "exit $code called"
}

# --- child interpreter -----------------------------------------------------

proc ::mocktcl::make_child {} {
    variable child
    variable job
    set c [interp create]
    set child $c
    $c eval {
        namespace eval ::mocktcl::orig {}
    }
    interp alias $c ::mocktcl::_l {} ::mocktcl::hit
    interp alias $c ::mocktcl::_b {} ::mocktcl::hit
    interp alias $c ::mocktcl::_assert {} ::mocktcl::assert
    interp alias $c ::mocktcl::_mock {} ::mocktcl::mock
    interp alias $c ::mocktcl::_called {} ::mocktcl::called
    interp alias $c ::mocktcl::_mock_calls {} ::mocktcl::mock_calls
    interp alias $c ::mocktcl::_instrumented {} ::mocktcl::instrumented
    interp alias $c ::exit {} ::mocktcl::child_exit
    $c eval [list set ::argv0 [dict get $job test_file]]
    $c eval {
        set ::argv {}
        set ::argc 0
    }
    $c eval [list set ::auto_path $::auto_path]
    $c eval {
        foreach ::mocktcl::kind {
            expect expect_not expect_near expect_contains expect_list
            expect_list_contains
        } {
            proc ::$::mocktcl::kind {args} [string map [list KIND $::mocktcl::kind] {
                ::mocktcl::_assert KIND [info frame -1] {*}$args
            }]
        }
        unset ::mocktcl::kind

        proc ::expect_called {name args} {
            set fq [uplevel 1 [list namespace which -command $name]]
            if {$fq eq ""} {
                set fq [expr {[string match ::* $name] ? $name : "::$name"}]
            }
            ::mocktcl::_assert expect_called [info frame -1] $fq {*}$args
        }

        proc ::expect_error {script {pattern *} args} {
            set rc [catch {uplevel 1 $script} result opts]
            if {$rc == 1 && [lindex [dict get $opts -errorcode] 0] eq "MOCKTCL"} {
                return -options $opts $result
            }
            ::mocktcl::_assert expect_error [info frame -1] $rc $result $pattern {*}$args
        }

        proc ::mock {name params body} {
            set fq [uplevel 1 [list namespace which -command $name]]
            ::mocktcl::_mock $name $fq $params $body
        }

        proc ::mock_calls {name} {
            set fq [uplevel 1 [list namespace which -command $name]]
            if {$fq eq ""} {
                set fq [expr {[string match ::* $name] ? $name : "::$name"}]
            }
            ::mocktcl::_mock_calls $fq
        }

        proc ::skip {{reason ""}} {
            return -code error -errorcode {MOCKTCL SKIP} $reason
        }

        rename ::source ::mocktcl::_real_source
        proc ::source {args} {
            set path [lindex $args end]
            set code [::mocktcl::_instrumented [file normalize $path]]
            if {![llength $code]} {
                return [uplevel 1 [list ::mocktcl::_real_source {*}$args]]
            }
            set previous [info script]
            info script $path
            set rc [catch {uplevel 1 [lindex $code 1]} result opts]
            info script $previous
            if {$rc == 2} {
                return $result
            }
            return -options $opts $result
        }
    }
}

proc ::mocktcl::has_proc {name} {
    variable child
    return [expr {[$child eval [list info procs ::$name]] ne ""}]
}

# Run NAME in the child; returns {status message line errorinfo}.
proc ::mocktcl::run_in_child {name} {
    variable child
    set rc [catch {$child eval [list ::$name]} result opts]
    return [classify $rc $result $opts ::$name]
}

# Remove the harness's own frames from the end of an errorInfo trace.
proc ::mocktcl::trim_info {info {entry ""}} {
    set markers [list \
        "\n    invoked from within\n\"\$child eval" \
        "\n    invoked from within\n\"::mocktcl::_real_source" \
        "\n    invoked from within\n\"uplevel 1 \[lindex \$code 1\]\""]
    if {$entry ne ""} {
        lappend markers "\n    invoked from within\n\"$entry\""
    }
    foreach marker $markers {
        set i [string first $marker $info]
        if {$i >= 0} {
            set info [string range $info 0 $i-1]
        }
    }
    return $info
}

proc ::mocktcl::frame_line {frame} {
    variable job
    if {[dict exists $frame line] && [dict exists $frame file]
            && [file normalize [dict get $frame file]] eq [dict get $job test_file]} {
        return [dict get $frame line]
    }
    return ""
}

proc ::mocktcl::classify {rc result opts {entry ""}} {
    variable job
    if {$rc == 0 || $rc == 2} {
        return [list pass "" "" ""]
    }
    if {$rc != 1} {
        set what [expr {$rc == 3 ? "break" : $rc == 4 ? "continue" : "code $rc"}]
        return [list error "invoked \"$what\" outside of a loop" "" ""]
    }
    set ec [dict get $opts -errorcode]
    set info [dict get $opts -errorinfo]
    if {[lindex $ec 0] eq "MOCKTCL"} {
        switch -- [lindex $ec 1] {
            ASSERT {
                set frame [lindex $ec 2]
                set line ""
                if {[dict exists $frame line]} {
                    set line [dict get $frame line]
                    if {[dict exists $frame file]} {
                        set file [dict get $frame file]
                        if {[file normalize $file] ne [file normalize [dict get $job test_file]]} {
                            set result "$result\n(at $file:$line)"
                        }
                    } elseif {[dict exists $frame proc]} {
                        set result "$result\n(at line $line of proc [dict get $frame proc])"
                        set line ""
                    }
                }
                return [list fail $result $line ""]
            }
            SKIP {
                return [list skip $result "" ""]
            }
            USAGE {
                return [list error $result [frame_line [lindex $ec 2]] ""]
            }
        }
    }
    set info [trim_info $info $entry]
    return [list error $result [error_line $info] $info]
}

# Best-effort: find the test file line in an errorInfo trace.
proc ::mocktcl::error_line {info} {
    variable job
    set file [dict get $job test_file]
    foreach {- f l} [regexp -all -inline {\(file "([^"]*)" line (\d+)\)} $info] {
        if {[file normalize $f] eq $file} {
            return $l
        }
    }
    return ""
}

# --- main ------------------------------------------------------------------

proc ::mocktcl::select_tests {} {
    variable child
    variable job
    set tests [dict get $job tests]
    if {[dict get $job only]} {
        return $tests
    }
    set filter [dict get $job filter]
    set rel [dict get $job rel_path]
    foreach p [lsort [$child eval {info procs ::test_*}]] {
        set p [string range $p 2 end]
        if {$p in $tests} {
            continue
        }
        if {$filter eq "" || [string first $filter [string tolower "${rel}::$p"]] >= 0} {
            lappend tests $p
        }
    }
    return $tests
}

proc ::mocktcl::run_test {name} {
    variable mocks
    variable counts
    variable calls
    set counts {}
    set calls {}
    set mark [llength $mocks]
    set start [clock microseconds]
    set outcome [list pass "" "" ""]
    if {[has_proc before_each]} {
        set outcome [run_in_child before_each]
        if {[lindex $outcome 0] eq "fail" || [lindex $outcome 0] eq "error"} {
            lset outcome 1 "before_each: [lindex $outcome 1]"
        }
    }
    if {[lindex $outcome 0] eq "pass"} {
        if {[has_proc $name]} {
            set outcome [run_in_child $name]
        } else {
            set outcome [list error "test proc $name is not defined" "" ""]
        }
    }
    if {[has_proc after_each]} {
        set after [run_in_child after_each]
        if {[lindex $outcome 0] eq "pass" && [lindex $after 0] ne "pass"} {
            set outcome $after
            lset outcome 1 "after_each: [lindex $outcome 1]"
        }
    }
    restore_mocks $mark
    set ms [expr {([clock microseconds] - $start) / 1000}]
    lassign $outcome status message line info
    emit event test name $name status $status message $message line $line \
        errorinfo $info duration_ms $ms
}

proc ::mocktcl::main {jobfile} {
    variable job
    variable out
    variable child
    set f [open $jobfile]
    fconfigure $f -encoding utf-8
    set job [read $f]
    close $f
    set out [open [dict get $job results] w]
    fconfigure $out -encoding utf-8 -translation lf

    make_child
    set test_file [dict get $job test_file]
    emit event start file [dict get $job rel_path]
    if {[catch {$child eval [list source $test_file]} result opts]} {
        set info [trim_info [dict get $opts -errorinfo]]
        emit event file_error message $result errorinfo $info line [error_line $info]
    } else {
        set tests [select_tests]
        set ok 1
        if {[has_proc before_all]} {
            lassign [run_in_child before_all] status message line info
            if {$status ne "pass"} {
                set ok 0
                emit event file_error message "before_all: $message" errorinfo $info line $line
            }
        }
        if {$ok} {
            foreach t $tests {
                run_test $t
            }
            if {[has_proc after_all]} {
                lassign [run_in_child after_all] status message line info
                if {$status ne "pass"} {
                    emit event file_error message "after_all: $message" errorinfo $info line $line
                }
            }
        }
    }
    emit_coverage
    emit event done
    close $out
}

::mocktcl::main [lindex $argv 0]
