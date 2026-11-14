file mkdir build
read_verilog [glob rtl/*.v]
read_verilog board/uart_tx.v
read_verilog board/status_uart.v
read_verilog board/arty_t2t_top.v
read_xdc board/arty_t2t.xdc
synth_design -top arty_t2t_top -part xc7a100tcsg324-1
opt_design
place_design
route_design
report_timing_summary -file build/timing_summary.txt
report_utilization -file build/utilization.txt
write_bitstream -force build/arty_t2t_top.bit
