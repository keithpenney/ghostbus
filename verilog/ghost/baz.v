`timescale 1ns/1ps

// An interposer

module baz #(
  parameter AW = 24,
  parameter DW = 32
) (
  input clk,
);

`ifdef GHOSTBUS_LIVE
`GHOSTBUS_MAGIC
`endif

wire [DW-1:0] dout_bar0, dout_bar1; // Is this going to kill the whole concept dead?

bar #(
  .AW(AW-1),
  .DW(DW)
) bar_0 (
  .clk(clk),
`ifdef GHOSTBUS_LIVE
`GHOSTBUS_bar_0
`endif
);

bar #(
  .AW(AW),
  .DW(DW)
) bar_1 (
  .clk(clk),
`ifdef GHOSTBUS_LIVE
`GHOSTBUS_bar_1
`endif
);

endmodule
