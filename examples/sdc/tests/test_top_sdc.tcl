source [file join [file dirname [info script]] helpers.tcl]

proc before_each {} {
    unset -nocomplain ::clk_period
    mock_sdc_commands
}

proc test_create_clock_uses_clk_period {} {
    set ::clk_period 10
    read_sdc top.sdc
    expect_called create_clock 1
    expect [mock_calls create_clock] {{CLK -period 10 i_clk}}
}

proc test_input_delay_is_66_percent_of_period {} {
    set ::clk_period 10
    read_sdc top.sdc
    expect_called set_input_delay 1
    lassign [lindex [mock_calls set_input_delay] 0] delay ports
    # 10 * 0.66 is 6.6000000000000005 in floating point; expect allows for
    # that kind of rounding noise automatically.
    expect $delay 6.6
    expect_list $ports {i_data i_valid}
}

proc test_clock_port_has_no_input_delay {} {
    set ::clk_period 10
    read_sdc top.sdc
    lassign [lindex [mock_calls set_input_delay] 0] delay ports
    expect [lsearch -exact $ports i_clk] -1 "i_clk must be removed from the input delay ports"
}

proc test_output_delay_is_half_the_period {} {
    set ::clk_period 10
    read_sdc top.sdc
    expect_called set_output_delay 1
    lassign [lindex [mock_calls set_output_delay] 0] delay ports
    expect $delay 5.0
    expect_list $ports {o_data o_ready}
}

proc test_delays_follow_a_different_period {} {
    set ::clk_period 2.5
    read_sdc top.sdc
    expect [mock_calls create_clock] {{CLK -period 2.5 i_clk}}
    expect [lindex [mock_calls set_input_delay] 0 0] 1.65
    expect [lindex [mock_calls set_output_delay] 0 0] 1.25
}

proc test_clk_period_must_be_set_first {} {
    expect_error {read_sdc top.sdc} {can't read "clk_period"*}
    expect_called create_clock 0
}
