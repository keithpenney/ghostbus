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

reg [23:0] gb_addr=0;
reg [31:0] gb_wdata=0;
wire [31:0] gb_rdata;
reg gb_wen=1'b0;
reg gb_rstb=1'b0;
top top_i (
  .gb_clk(gb_clk), // input
  .gb_addr(gb_addr), // input [23:0]
  .gb_wdata(gb_wdata), // input [31:0]
  .gb_rdata(gb_rdata), // output [31:0]
  .gb_wen(gb_wen), // input
  .gb_rstb(gb_rstb) // input
);

// =========== Stimulus =============
`define GHOSTBUS_TEST_CSRS
//`define DEBUG_READS
//`define DEBUG_WRITES
`include "gb_testbench.vh"

initial begin
  @(posedge gb_clk) test_pass=1'b1;
  $display("Reading CSR init values.");
  CSR_READ_CHECK_ALL();
  if (test_pass) $display("PASS");
  else begin
    $display("FAIL");
    $stop(0);
  end

  @(posedge gb_clk);
  $display("CSR Write+Read All");
  CSR_WRITE_READ_CHECK_ALL();
  if (test_pass) $display("PASS");
  else begin
    $display("FAIL");
    $stop(0);
  end

  @(posedge gb_clk);
  $display("RAM Write+Read All");
  RAM_WRITE_READ_CHECK_ALL();
  if (test_pass) $display("PASS");
  else begin
    $display("FAIL");
    $stop(0);
  end

  /*
  $display("Reading ROMs.");
  // This necessarily needs to be hand-written (Ghostbus does not know the contents of ROMs)
  //TOP_SUBMOD_FOO_0_FOO_RAM_BASE
  GB_READ_CHECK(TOP_SUBMOD_FOO_0_FOO_RAM_BASE, 32'h00000001);
  GB_READ_CHECK(TOP_SUBMOD_FOO_0_FOO_RAM_BASE+1, 32'h00000002);
  */

  $display("Reading Extmod init values.");
  // This necessarily needs to be hand-written (Ghostbus does not know the contents of External Modules)
  //TOP_SUBMOD_FOO_0_BAR_0_EXT_I_BASE
  GB_READ_CHECK(TOP_SUBMOD_FOO_0_BAR_0_EXT_I_BASE, 32'h000000C0);
  GB_READ_CHECK(TOP_SUBMOD_FOO_0_BAR_0_EXT_I_BASE+1, 32'h000000C1);

  //TOP_SUBMOD_FOO_0_BAZ_0_BAR_0_EXT_I_BASE
  GB_READ_CHECK(TOP_SUBMOD_FOO_0_BAZ_0_BAR_0_EXT_I_BASE, 32'h000000C0);
  GB_READ_CHECK(TOP_SUBMOD_FOO_0_BAZ_0_BAR_0_EXT_I_BASE+1, 32'h000000C1);

  //TOP_SUBMOD_FOO_0_BAZ_0_BAR_1_EXT_I_BASE
  GB_READ_CHECK(TOP_SUBMOD_FOO_0_BAZ_0_BAR_1_EXT_I_BASE, 32'h000000C0);
  GB_READ_CHECK(TOP_SUBMOD_FOO_0_BAZ_0_BAR_1_EXT_I_BASE+1, 32'h000000C1);

  //TOP_SUBMOD_FOO_1_BAR_0_EXT_I_BASE
  GB_READ_CHECK(TOP_SUBMOD_FOO_1_BAR_0_EXT_I_BASE, 32'h000000C0);
  GB_READ_CHECK(TOP_SUBMOD_FOO_1_BAR_0_EXT_I_BASE+1, 32'h000000C1);

  //TOP_SUBMOD_FOO_1_BAZ_0_BAR_0_EXT_I_BASE
  GB_READ_CHECK(TOP_SUBMOD_FOO_1_BAZ_0_BAR_0_EXT_I_BASE, 32'h000000C0);
  GB_READ_CHECK(TOP_SUBMOD_FOO_1_BAZ_0_BAR_0_EXT_I_BASE+1, 32'h000000C1);

  //TOP_SUBMOD_FOO_1_BAZ_0_BAR_1_EXT_I_BASE
  GB_READ_CHECK(TOP_SUBMOD_FOO_1_BAZ_0_BAR_1_EXT_I_BASE, 32'h000000C0);
  GB_READ_CHECK(TOP_SUBMOD_FOO_1_BAZ_0_BAR_1_EXT_I_BASE+1, 32'h000000C1);
  if (test_pass) $display("PASS");
  else begin
    $display("FAIL");
    $stop(0);
  end

  if (test_pass) begin
    $finish(0);
  end else begin
    $stop(0);
  end
end

endmodule
