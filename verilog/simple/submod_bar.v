`timescale 1ns/1ps

`ifndef GHOSTBUS_LIVE
  `define GHOSTBUSPORTS
  `define GHOSTBUS_submod_bar
`else
  `include "defs.vh"
`endif

module submod_bar #(
  parameter AW = 24,
  parameter DW = 32
) (
   input clk
  ,input demo_sig
  `GHOSTBUSPORTS
);

reg [3:0] bar_reg=1;                            // Non-host-accessible register

(* ghostbus_ha *) reg signed [7:0] bar_ha_reg=8'hcc;      // Host-accessible register (will be auto-decoded)
(* ghostbus_ha *) reg [31:0] bar_ha_reg_two=32'hceceface;  // Another host-accessible register

(* ghostbus_ha, ghostbus_addr='h100 *)
reg [7:0] bar_ram [0:63];                       // Host-accessible RAM with pre-defined relative address (0x100)

localparam ext_aw = 2;
localparam ext_dw = 8;

(* ghostbus_ext="ext_i, clk" *) wire bus_clk;
(* ghostbus_ext="ext_i, addr" *) wire [ext_aw-1:0] ext_addr;
(* ghostbus_ext="ext_i, wdata" *) wire [ext_dw-1:0] ext_wdata;
(* ghostbus_ext="ext_i, rdata" *) wire [ext_dw-1:0] ext_rdata;
(* ghostbus_ext="ext_i, we" *) wire ext_we;

extmod #(
  .aw(ext_aw),
  .dw(ext_dw)
) extmod_i (
  .clk(bus_clk), // input
  .addr(ext_addr), // input [aw-1:0]
  .din(ext_wdata), // input [dw-1:0]
  .dout(ext_rdata), // output [dw-1:0]
  .we(ext_we) // input
);

`GHOSTBUS_submod_bar

endmodule
