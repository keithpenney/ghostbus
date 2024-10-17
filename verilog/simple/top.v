// Top module for the 'simple' codebase

`ifndef GHOSTBUS_LIVE
  `define GHOSTBUS_top
  `define GHOSTBUS_submod_foo_0
  `define GHOSTBUS_submod_foo_1
`endif

module top (
  input clk
);

localparam FOO_AW = 24;
localparam FOO_DW = 32;
localparam FOO_GW = 8;
localparam FOO_RD = 8;

(* ghostbus_port="clk"  *) wire gb_clk;
(* ghostbus_port="addr" *) wire [23:0] gb_addr;
(* ghostbus_port="wdata"*) wire [31:0] gb_wdata;
(* ghostbus_port="rdata"*) wire [31:0] gb_rdata;
(* ghostbus_port="wen"*)   wire gb_wen;

submod_foo #(
  .AW(FOO_AW),
  .DW(FOO_DW),
  .GW(FOO_GW),
  .RD(FOO_RD)
) submod_foo_0 (
  .clk(clk)
  `GHOSTBUS_submod_foo_0
);

submod_foo #(
  .AW(FOO_AW),
  .DW(FOO_DW),
  .GW(FOO_GW),
  .RD(FOO_RD)
) submod_foo_1 (
  .clk(clk)
  `GHOSTBUS_submod_foo_1
);

`GHOSTBUS_top

endmodule
