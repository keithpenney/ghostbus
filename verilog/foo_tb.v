`timescale 1ns/1ns

module foo_tb;

localparam CLK_HALFPERIOD = 5;
localparam TICK = 2*CLK_HALFPERIOD;
reg clk=1'b0;
always #CLK_HALFPERIOD clk <= ~clk;

`ifndef YOSYS
// VCD dump file for gtkwave
initial begin
  if ($test$plusargs("vcd")) begin
    $dumpfile("foo.vcd");
    $dumpvars();
  end
end
`endif

localparam TOW = 12;
localparam TOSET = {TOW{1'b1}};
reg [TOW-1:0] r_timeout=0;
always @(posedge clk) begin
  if (r_timeout > 0) r_timeout <= r_timeout - 1;
end
wire to = ~(|r_timeout);
`define wait_timeout(sig) r_timeout = TOSET; #TICK wait ((to) || sig)

localparam AW = 24;
localparam DW = 32;
localparam GW = 8;
localparam RD = 8;

// Manually define the ghostbus
localparam GB_AW = 12;
localparam GB_DW = 32;
(* ghostbus_port="clk" *)  wire gb_clk=clk;
(* ghostbus_port="addr" *) reg [GB_AW-1:0] gb_addr=0;
(* ghostbus_port="dout" *) reg [GB_DW-1:0] gb_dout=0;
(* ghostbus_port="din" *)  wire [GB_DW-1:0] gb_din;
(* ghostbus_port="we" *)  reg gb_we=1'b0;

`define GHOSTBUS_TEST_CSRS
`define GHOSTBUS_TEST_RAMS
`ifdef GHOSTBUS_LIVE
  `include "defs.vh"
  `include "mmap.vh"
`endif

foo #(
  .AW(AW),
  .DW(DW),
  .GW(GW),
  .RD(RD)
) foo_i (
  .clk(clk) // input
`ifdef GHOSTBUS_LIVE
//`GHOSTBUS_foo_tb_foo_i
// TODO
  ,.gb_clk(gb_clk)    // input
  ,.gb_addr(gb_addr)  // input [11:0]
  ,.gb_dout(gb_dout)  // input [31:0]
  ,.gb_din(gb_din) // output [31:0]
  ,.gb_we(gb_we) // input
`else
  `ifdef MANUAL_TEST
  ,.gb_clk(gb_clk)    // input
  ,.gb_addr(gb_addr)  // input [11:0]
  ,.gb_dout(gb_dout)  // input [31:0]
  ,.gb_din(gb_din) // output [31:0]
  ,.gb_we(gb_we) // input
  `endif
`endif
);

endmodule
