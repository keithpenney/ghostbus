// Top module for the 'bustree' codebase

`ifndef GHOSTBUS_LIVE
  `define GHOSTBUS_top
  `define GHOSTBUS_submod_foo_top
  `define GHOSTBUS_submod_foo_bottom
`endif

module top (
  input clk
);

localparam GB_AW = 24;
localparam GB_DW = 32;

(* ghostbus_port="clk"  *) wire gb_clk;
(* ghostbus_port="addr" *) wire [GB_AW-1:0] gb_addr;
(* ghostbus_port="wdata"*) wire [GB_DW-1:0] gb_wdata;
(* ghostbus_port="rdata"*) wire [GB_DW-1:0] gb_rdata;
(* ghostbus_port="wen, wstb"*)   wire gb_wen;
(* ghostbus_port="rstb"*)   wire gb_rstb;

(* ghostbus_ext="glue_top, clk"   *) wire gluetop_clk;
// This address width is fake! It will get its aw from "glue_bottom"
(* ghostbus_ext="glue_top, addr"  *) wire [GB_AW-1:0] gluetop_addr;
(* ghostbus_ext="glue_top, wdata" *) wire [GB_DW-1:0] gluetop_wdata;
(* ghostbus_ext="glue_top, rdata" *) wire [GB_DW-1:0] gluetop_rdata;
(* ghostbus_ext="glue_top, wstb"  *) wire gluetop_wstb;

(* ghostbus_port="clk",       ghostbus_name="glue_bottom", ghostbus_branch="glue_top" *) wire gluebottom_clk;
(* ghostbus_port="addr",      ghostbus_name="glue_bottom", ghostbus_branch="glue_top" *) wire [GB_AW-1:0] gluebottom_addr;
(* ghostbus_port="wdata",     ghostbus_name="glue_bottom", ghostbus_branch="glue_top" *) wire [GB_DW-1:0] gluebottom_wdata;
(* ghostbus_port="rdata",     ghostbus_name="glue_bottom", ghostbus_branch="glue_top" *) wire [GB_DW-1:0] gluebottom_rdata;
(* ghostbus_port="wstb, wen", ghostbus_name="glue_bottom", ghostbus_branch="glue_top" *) wire gluebottom_wstb;

bus_glue #(
  .AW(GB_AW),
  .DW(GB_DW)
) bus_glue_i (
  .i_clk(gluetop_clk), // input
  .i_addr(gluetop_addr), // input [AW-1:0]
  .i_wdata(gluetop_wdata), // input [DW-1:0]
  .i_rdata(gluetop_rdata), // output [DW-1:0]
  .i_wstb(gluetop_wstb), // input
  .o_clk(gluebottom_clk), // input
  .o_addr(gluebottom_addr_w), // output [AW-1:0]
  .o_wdata(gluebottom_wdata), // output [DW-1:0]
  .o_rdata(gluebottom_rdata), // input [DW-1:0]
  .o_wstb(gluebottom_wstb) // output
);

localparam FOO_GW = 8;
localparam FOO_RD_TOP = 8;
localparam FOO_RD_BOTTOM = 16;

// submod_foo_top lives in the default domain
submod_foo #(
  .AW(GB_AW),
  .DW(GB_DW),
  .GW(FOO_GW),
  .RD(FOO_RD_TOP)
) submod_foo_top (
  .clk(clk)
  `GHOSTBUS_submod_foo_top
);

// submod_foo_bottom lives in the "glue_bottom" domain
(* ghostbus_name="glue_bottom" *) submod_foo #(
  .AW(GB_AW-12),
  .DW(GB_DW),
  .GW(FOO_GW),
  .RD(FOO_RD_BOTTOM)
) submod_foo_bottom (
  .clk(clk)
  `GHOSTBUS_submod_foo_bottom
);

// A CSR in the default domain
(* ghostbus *) reg [7:0] top_ha_reg=8'h42;

// A CSR in the "glue_bottom" domain
(* ghostbus, ghostbus_name="glue_bottom" *) reg [7:0] bottom_ha_reg=8'h42;

`GHOSTBUS_top

endmodule
