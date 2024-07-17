`timescale 1ns/1ps

module bar #(
  parameter AW = 24,
  parameter DW = 32
) (
   input clk
  ,input demo_sig
`ifdef GHOSTBUS_LIVE
`GHOSTBUS_ports
`else
  `ifdef MANUAL_TEST
  // Manual ports
  ,input  gb_clk
  ,input  [11:0] gb_addr
  ,input  [31:0] gb_dout
  ,output [31:0] gb_din
  ,input  gb_we
  `endif
`endif
);

reg [3:0] bar_reg=1;                            // Non-host-accessible register

(* ghostbus_ha *) reg [7:0] bar_ha_reg=8'hcc;      // Host-accessible register (will be auto-decoded)
(* ghostbus_ha *) reg [31:0] bar_ha_reg_two=32'hceceface;  // Another host-accessible register

(* ghostbus_ha, ghostbus_addr='h100 *)
reg [7:0] bar_ram [0:63];                       // Host-accessible RAM with pre-defined relative address (0x100)

bif #(
  .AW(12),
  .DW(8)
) bif_0 (
  .clk(clk)
);

bif #(
  .AW(1),
  .DW(4)
) bif_1 (
  .clk(clk)
);

localparam ext_aw = 2;
localparam ext_dw = 8;

(* ghostbus_ext="ext_i, clk" *) wire bus_clk;
(* ghostbus_ext="ext_i, addr" *) wire [ext_aw-1:0] ext_addr;
(* ghostbus_ext="ext_i, wdata" *) wire [ext_dw-1:0] ext_wdata;
(* ghostbus_ext="ext_i, rdata" *) wire [ext_dw-1:0] ext_rdata;
(* ghostbus_ext="ext_i, we" *) wire ext_we;

ext #(
  .aw(ext_aw),
  .dw(ext_dw)
) ext_i (
  .clk(bus_clk), // input
  .addr(ext_addr), // input [aw-1:0]
  .din(ext_wdata), // input [dw-1:0]
  .dout(ext_rdata), // output [dw-1:0]
  .we(ext_we) // input
);

reg [1:0] garbage=2'b11;
wire [1:0] trash;
bof bof_i (
  .clk(clk), // input
  .garbage(garbage), // input [1:0]
  .trash(trash) // output [1:0]
);

`ifdef GHOSTBUS_LIVE
`GHOSTBUS_bar
`endif

endmodule
