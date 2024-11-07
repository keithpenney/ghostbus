`timescale 1ns/1ps

`ifndef GHOSTBUS_LIVE
  `define GHOSTBUSPORTS
  `define GHOSTBUS_submod_foo
  `define GHOSTBUS_submod_foo_bar_0
  `define GHOSTBUS_submod_foo_baz_0
`endif

module submod_foo #(
  parameter AW = 24,
  parameter DW = 32,
  parameter GW = 8,
  parameter RD = 8
) (
  input clk
  `GHOSTBUSPORTS
);

reg [3:0] foo_reg=0;                            // Non-host-accessible register

(* ghostbus *) reg [GW-1:0] foo_reg=8'h42;  // Host-accessible register (will be auto-decoded)
(* ghostbus_addr='h40 *) reg [3:0] foo_ram [0:RD-1]; // Host-accessible RAM with pre-defined relative address (0x40)

submod_baz #(
  .AW(AW),
  .DW(DW)
) baz_0 (
  .clk(clk),
  .demo_sig(foo_reg[0])
  `GHOSTBUS_submod_foo_baz_0
);

submod_bar #(
  .AW(AW),
  .DW(DW)
) bar_0 (
  .clk(clk),
  .demo_sig(foo_reg[1])
  `GHOSTBUS_submod_foo_bar_0
);

`GHOSTBUS_submod_foo

endmodule
