// Top module for the 'simple' codebase

`ifndef GHOSTBUS_LIVE
  `define GHOSTBUS_top
  `define GHOSTBUS_top_submod_foo_0
  `define GHOSTBUS_top_submod_foo_1
`else
  `include "defs.vh"
`endif

module top (
  (* ghostbus_driver="clk"  *) input  gb_clk,
  (* ghostbus_driver="addr" *) input  [23:0] gb_addr,
  (* ghostbus_driver="wdata"*) input  [31:0] gb_wdata,
  (* ghostbus_driver="rdata"*) output [31:0] gb_rdata,
  (* ghostbus_driver="wen, wstb"*) input gb_wen,
  (* ghostbus_driver="rstb"*)  input gb_rstb
);

localparam FOO_AW = 24;
localparam FOO_DW = 32;
localparam FOO_GW = 8;
localparam FOO_RD = 8;

// Host-accessible register (will be auto-decoded)
// Global alias "holiday_pasta"
(* ghostbus, ghostbus_alias="holiday_pasta" *) reg [7:0] top_ha_reg=8'h42;
(* ghostbus_strobe *) reg simple_strobe=4'h0;
(* ghostbus_strobe *) reg [3:0] vector_strobe=4'h0;
(* ghostbus_ws="top_ha_reg" *) reg associated_strobe=1'b0;

`GHOSTBUS_top

(* ghostbus_pipeline *) submod_foo #(
  .AW(FOO_AW),
  .DW(FOO_DW),
  .GW(FOO_GW),
  .RD(FOO_RD)
) submod_foo_0 (
  .clk(gb_clk)
  `GHOSTBUS_top_submod_foo_0
);

submod_foo #(
  .AW(FOO_AW),
  .DW(FOO_DW),
  .GW(FOO_GW),
  .RD(FOO_RD)
) submod_foo_1 (
  .clk(gb_clk)
  `GHOSTBUS_top_submod_foo_1
);

endmodule
