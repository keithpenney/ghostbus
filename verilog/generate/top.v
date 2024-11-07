// Top module for the 'generate' codebase

`ifndef GHOSTBUS_LIVE
  `define GHOSTBUS_top
`endif

module top #(
  parameter FOO_COPIES = 4,
  parameter TOP_BAZ = 1
) (
  (* ghostbus_port="clk"  *) input  gb_clk,
  (* ghostbus_port="addr" *) input  [23:0] gb_addr,
  (* ghostbus_port="wdata"*) input  [31:0] gb_wdata,
  (* ghostbus_port="rdata"*) output [31:0] gb_rdata,
  (* ghostbus_port="wen, wstb"*) input gb_wen,
  (* ghostbus_port="rstb"*)  input gb_rstb
);

localparam FOO_AW = 24;
localparam FOO_DW = 32;
localparam FOO_GW = 8;
localparam FOO_RD = 8;

genvar N;
generate
  for (N=0; N<FOO_COPIES; N=N+1) begin: foo_generator
    submod_foo #(
      .AW(FOO_AW),
      .DW(FOO_DW),
      .GW(FOO_GW),
      .RD(FOO_RD)
    ) submod_foo_0 (
      .clk(gb_clk)
      `GHOSTBUS_submod_foo_0
    );
    (* ghostbus *) reg [3:0] top_foo_n = N[3:0];
  end
endgenerate

generate
  if (TOP_BAZ==1) begin: baz_generator
    submod_baz #(
      .AW(AW),
      .DW(DW)
    ) baz_0 (
      .clk(clk),
      .demo_sig(foo_reg[0])
      `GHOSTBUS_submod_foo_baz_0
    );
    (* ghostbus *) reg [3:0] top_baz = 4'hc;
  end
endgenerate

(* ghostbus *) reg [7:0] top_reg=8'h42;

`GHOSTBUS_top

endmodule
