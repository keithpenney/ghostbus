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

localparam AW = 24;
localparam DW = 32;
localparam GW = 8;
localparam RD = 8;

// Manually define the ghostbus
localparam GB_AW = 13;
localparam GB_DW = 32;
(* ghostbus_port="clk" *)  wire gb_clk=clk;
(* ghostbus_port="addr" *) reg [GB_AW-1:0] gb_addr=0;
(* ghostbus_port="dout" *) reg [GB_DW-1:0] gb_dout=0;
(* ghostbus_port="din" *)  wire [GB_DW-1:0] gb_din;
(* ghostbus_port="we" *)   reg gb_we=1'b0;

`define GHOSTBUS_TEST_CSRS
`define GHOSTBUS_TEST_RAMS
`ifdef GHOSTBUS_LIVE
  `include "defs.vh"
  `include "mmap.vh"
  `GHOSTBUS_foo_tb
`endif

foo #(
  .AW(AW),
  .DW(DW),
  .GW(GW),
  .RD(RD)
) foo_i (
  .clk(clk) // input
`ifdef GHOSTBUS_LIVE
`GHOSTBUS_foo_tb_foo_i
`endif
);

endmodule
