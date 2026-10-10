# Shared helpers: not a test file (no test_ prefix).
set ::project_root [file normalize [file join [file dirname [info script]] ..]]

proc load_src {name} {
    uplevel #0 [list source [file join $::project_root src $name]]
}
