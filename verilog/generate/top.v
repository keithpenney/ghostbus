// Top module for the 'generate' codebase

`ifndef GHOSTBUS_LIVE
  `define GHOSTBUS_top
  `define GHOSTBUS_baz
  `define GHOSTBUS_foo
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

(* ghostbus *) reg [7:0] top_reg=8'h42;

genvar N;
generate
  for (N=0; N<FOO_COPIES; N=N+1) begin: foo_generator
    submod_foo #(
      .AW(FOO_AW),
      .DW(FOO_DW),
      .GW(FOO_GW),
      .RD(FOO_RD)
    ) foo (
      .clk(gb_clk)
      `GHOSTBUS_foo
    );
    (* ghostbus *) reg [3:0] top_foo_n = N[3:0];
    (* ghostbus *) reg [7:0] foo_ram [0:7];
  end
endgenerate

genvar M;
generate
  for (M=0; M<4; M=M+1) begin
    (* ghostbus *) reg [3:0] anon_for = M[3:0];
  end
endgenerate

generate
  if (TOP_BAZ==1) begin: baz_generator
    submod_baz #(
      .AW(12),
      .DW(8)
    ) baz (
      .clk(gb_clk),
      .demo_sig(top_reg[0])
      `GHOSTBUS_baz
    );
    (* ghostbus *) reg [3:0] top_baz = 4'hc;
    (* ghostbus *) reg [7:0] baz_ram [0:7];
  end
endgenerate

`GHOSTBUS_top

endmodule
