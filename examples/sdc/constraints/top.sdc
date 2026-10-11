# Timing constraints for the example design.
# Whoever reads this file (the EDA tool, or a test) must set clk_period,
# in ns, before sourcing it.
create_clock CLK -period $clk_period [get_ports i_clk]
set_input_delay [expr $clk_period * 0.66] [remove_from_collection [all_inputs] [get_ports i_clk]]
set_output_delay [expr $clk_period * 0.5] [all_outputs]
