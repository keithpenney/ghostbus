`timescale 1ns/1ps

`ifndef GHOSTBUS_LIVE
  `define GHOSTBUSPORTS
  `define GHOSTBUS_submod_foo
  `define GHOSTBUS_submod_foo_bar_0
  `define GHOSTBUS_submod_foo_baz_0
`else
  `include "defs.vh"
`endif

module submod_foo #(
  parameter AW = 24,
  parameter DW = 32,
  parameter GW = 8,
  parameter RD = 8
) (
  input clk
  `ifdef HAND_ROLLED
  ,input  GBPORT_clk
  ,input [23:0] GBPORT_addr
  ,input [31:0] GBPORT_dout
  ,output [31:0] GBPORT_din
  ,input  GBPORT_we
  ,input  GBPORT_wstb
  ,input  GBPORT_rstb
  `else
  `GHOSTBUSPORTS
  `endif
);

(* ghostbus *) reg [GW-1:0] foo_reg=8'h42;  // Host-accessible register (will be auto-decoded)
(* ghostbus_addr='h40 *) reg [3:0] foo_ram [0:RD-1]; // Host-accessible RAM with pre-defined relative address (0x40)

`GHOSTBUS_submod_foo

submod_baz #(
  .AW(AW),
  .DW(DW)
) baz_0 (
  .clk(clk),
  .demo_sig(foo_reg[0])
  `ifdef HAND_ROLLED
  // TODO
  ,.GBPORT_clk(1'b0) // input
  ,.GBPORT_addr(24'h000000) // input [23:0]
  ,.GBPORT_dout(32'h00000000) // input [31:0]
  ,.GBPORT_din() // output [31:0]
  ,.GBPORT_we(1'b0) // input
  ,.GBPORT_wstb(1'b0) // input
  ,.GBPORT_rstb(1'b0) // input
  `else
  `GHOSTBUS_submod_foo_baz_0
  `endif
);

submod_bar #(
  .AW(AW),
  .DW(DW)
) bar_0 (
  .clk(clk),
  .demo_sig(foo_reg[1])
  `GHOSTBUS_submod_foo_bar_0
);

endmodule
