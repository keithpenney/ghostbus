`timescale 1ns/1ps

// An interposer

`ifndef GHOSTBUS_LIVE
  `define GHOSTBUSPORTS
  `define GHOSTBUS_submod_baz
  `define GHOSTBUS_submod_baz_bar_0
  `define GHOSTBUS_submod_baz_bar_1
`endif

module submod_baz #(
  parameter AW = 24,
  parameter DW = 32
) (
  input clk,
  input demo_sig
  `GHOSTBUSPORTS
);

// Interesting demo: Enabling this doubles the size of the memory map!
//(* ghostbus_ha *) reg [7:0] baz_reg=100;

submod_bar #(
  .AW(AW-1),
  .DW(DW)
) bar_0 (
  .clk(clk),
  .demo_sig(demo_sig)
  `GHOSTBUS_submod_baz_bar_0
);

submod_bar #(
  .AW(AW),
  .DW(DW)
) bar_1 (
  .clk(clk),
  .demo_sig(demo_sig)
  `GHOSTBUS_submod_baz_bar_1
);

`GHOSTBUS_submod_baz

endmodule
