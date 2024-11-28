`timescale 1ns/1ns

module top_tb;

localparam GB_CLK_HALFPERIOD = 5;
localparam TICK = 2*GB_CLK_HALFPERIOD;
reg gb_clk=1'b0;
always #GB_CLK_HALFPERIOD gb_clk <= ~gb_clk;

// VCD dump file for gtkwave
initial begin
  if ($test$plusargs("vcd")) begin
    $dumpfile("top.vcd");
    $dumpvars();
  end
end

localparam TOW = 12;
localparam TOSET = {TOW{1'b1}};
reg [TOW-1:0] r_timeout=0;
always @(posedge gb_clk) begin
  if (r_timeout > 0) r_timeout <= r_timeout - 1;
end
wire to = ~(|r_timeout);
`define wait_timeout(sig) r_timeout = TOSET; #TICK wait ((to) || sig)

localparam GB_AW = 24;
localparam GB_DW = 32;

reg [GB_AW-1:0] gb_addr=0;
reg [GB_DW-1:0] gb_wdata=0;
wire [GB_DW-1:0] gb_rdata;
reg gb_wen=1'b0;
reg gb_rstb=1'b0;
top #(
  .GB_AW(GB_AW),
  .GB_DW(GB_DW)
) top_i (
  .gb_clk(gb_clk), // input
  .gb_addr(gb_addr), // input [GB_AW-1:0]
  .gb_wdata(gb_wdata), // input [GB_DW-1:0]
  .gb_rdata(gb_rdata), // output [GB_DW-1:0]
  .gb_wen(gb_wen), // input
  .gb_rstb(gb_rstb) // input
);

// =========== Stimulus =============
`define GHOSTBUS_TEST_CSRS
`define DEBUG_WRITES
//`define DEBUG_READS
`include "memory_map.vh"

endmodule
