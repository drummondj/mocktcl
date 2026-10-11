# Shared helpers for the SDC tests (not a test file: no test_ prefix).
set ::project_root [file normalize [file join [file dirname [info script]] ..]]

# Source an SDC file the way an EDA tool does: at the global level, so
# variables such as clk_period are read from (and set in) global scope.
proc read_sdc {name} {
    uplevel #0 [list source [file join $::project_root constraints $name]]
}

# Stand-ins for the tool's SDC commands. These commands don't exist in plain
# tclsh; mock creates them for the current test and removes them afterwards.
# Real tools return opaque "collections"; here a plain Tcl list of port names
# plays that role.
proc mock_sdc_commands {} {
    mock all_inputs {} { return {i_clk i_data i_valid} }
    mock all_outputs {} { return {o_data o_ready} }
    mock get_ports {pattern} { return $pattern }
    mock remove_from_collection {collection remove} {
        return [lmap port $collection { if {$port in $remove} continue; set port }]
    }
    # The commands under test do nothing; we only inspect their arguments
    # afterwards with mock_calls.
    mock create_clock {args} {}
    mock set_input_delay {args} {}
    mock set_output_delay {args} {}
}
