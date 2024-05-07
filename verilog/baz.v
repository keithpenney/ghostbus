`timescale 1ns/1ps

// An interposer

module baz #(
  parameter AW = 24,
  parameter DW = 32
) (
  input clk,
  input [AW-1:0] addr,
  input [DW-1:0] din,
  output [DW-1:0] dout,
  input we
);

`ifdef GHOSTBUS_LIVE
`GHOSTBUS_MAGIC
`endif

wire [DW-1:0] dout_bar0, dout_bar1; // Is this going to kill the whole concept dead?

bar #(
  .AW(AW),
  .DW(DW)
) bar_0 (
  .clk(clk),
  .addr(addr),
  .din(din),
  .dout(dout_bar0),
  .we(we)
);

bar #(
  .AW(AW),
  .DW(DW)
) bar_1 (
  .clk(clk),
  .addr(addr),
  .din(din),
  .dout(dout_bar1),
  .we(we)
);

endmodule
