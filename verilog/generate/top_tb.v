`timescale 1ns/1ns

module top_tb;

localparam GB_CLK_HALFPERIOD = 5;
localparam TICK = 2*GB_CLK_HALFPERIOD;
reg gb_clk=1'b1;
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

localparam FOO_COPIES = 4;
localparam TOP_BAZ = 1;

wire [31:0] gb_rdata;
`ifdef HAND_ROLLED
wire [23:0] gb_addr;
wire [31:0] gb_wdata;
wire gb_wen;
wire gb_rstb;
`else
reg [23:0] gb_addr=0;
reg [31:0] gb_wdata=0;
reg gb_wen=1'b0;
reg gb_rstb=1'b0;
`endif
top #(
  .FOO_COPIES(FOO_COPIES),
  .TOP_BAZ(TOP_BAZ)
) top_i (
  .gb_clk(gb_clk), // input
  .gb_addr(gb_addr), // input [23:0]
  .gb_wdata(gb_wdata), // input [31:0]
  .gb_rdata(gb_rdata), // output [31:0]
  .gb_wen(gb_wen), // input
  .gb_rstb(gb_rstb) // input
);

localparam LB_ADW = 24;
localparam LB_READ_DELAY = 3;

`ifdef HAND_ROLLED
wire lb_clk = gb_clk;
`include "localbus.vh"
assign gb_addr = lb_addr;
assign gb_wdata = lb_wdata;
assign lb_rdata = gb_rdata;
assign gb_wen = lb_write;
assign gb_rstb = lb_rstb;
`endif

// =========== Stimulus =============
`ifdef HAND_ROLLED
reg [LB_ADW-1:0] xact_addr=0;
localparam N_ADDRS = 46;
wire [N_ADDRS*LB_ADW-1:0] xact_addrs = {
  24'h3f, 24'h3e, 24'h3d, 24'h3c, 24'h3b, 24'h3a, 24'h39, 24'h38, // foo_ram[3]
  24'h37, 24'h36, 24'h35, 24'h34, 24'h33, 24'h32, 24'h31, 24'h30, // foo_ram[2]
  24'h2f, 24'h2e, 24'h2d, 24'h2c, 24'h2b, 24'h2a, 24'h29, 24'h28, // foo_ram[1]
  24'h27, 24'h26, 24'h25, 24'h24, 24'h23, 24'h22, 24'h21, 24'h20, // foo_ram[0]
  24'h0f, 24'h0e, 24'h0d, 24'h0c, 24'h0b, 24'h0a, 24'h09, 24'h08, // baz_ram
  24'h07, // top_foo_n[3]
  24'h06, // top_foo_n[2]
  24'h05, // top_foo_n[1]
  24'h04, // top_foo_n[0]
  24'h01, // top_baz
  24'h00  // top_reg
};
wire [N_ADDRS*32-1:0] xact_wvals = {
  32'haf, 32'hae, 32'had, 32'hac, 32'hab, 32'haa, 32'ha9, 32'ha8, // foo_ram[3] (DW = 8)
  32'hb7, 32'hb6, 32'hb5, 32'hb4, 32'hb3, 32'hb2, 32'hb1, 32'hb0, // foo_ram[2] (DW = 8)
  32'hcf, 32'hce, 32'hcd, 32'hcc, 32'hcb, 32'hca, 32'hc9, 32'hc8, // foo_ram[1] (DW = 8)
  32'hd7, 32'hd6, 32'hd5, 32'hd4, 32'hd3, 32'hd2, 32'hd1, 32'hd0, // foo_ram[0] (DW = 8)
  32'hef, 32'hee, 32'hed, 32'hec, 32'heb, 32'hea, 32'he9, 32'he8, // baz_ram (DW = 8)
  32'h07, // top_foo_n[3] (DW = 4)
  32'h06, // top_foo_n[2] (DW = 4)
  32'h05, // top_foo_n[1] (DW = 4)
  32'h04, // top_foo_n[0] (DW = 4)
  32'h01, // top_baz (DW = 4)
  32'hcc  // top_reg (DW = 8)
};
reg [31:0] xact_rvals [0:N_ADDRS-1];

reg [31:0] read_result=0, expected_val=0;
integer N_XACT=0;
reg PASS=1'b1;
initial begin
  #(4*TICK) $display("First Read Loop: Read initial values");
  for (N_XACT=0; N_XACT<N_ADDRS; N_XACT=N_XACT+1) begin
    xact_addr = xact_addrs[(N_XACT+1)*LB_ADW-1-:LB_ADW];
    #(4*TICK) lb_read_task(xact_addr, read_result);
    //$display("  addr = 0x%x; read_result = 0x%x", xact_addr, read_result);
    #(2*TICK) xact_rvals[N_XACT] = read_result;
  end

  #(4*TICK) $display("Second Read Loop: Ensure reads are repeatable");
  for (N_XACT=0; N_XACT<N_ADDRS; N_XACT=N_XACT+1) begin
    xact_addr = xact_addrs[(N_XACT+1)*LB_ADW-1-:LB_ADW];
    #(4*TICK) lb_read_task(xact_addr, read_result);
    //$display("  addr = 0x%x; read_result = 0x%x", xact_addr, read_result);
    if (read_result != xact_rvals[N_XACT]) begin
      $display("    ERROR: 0x%x != 0x%x", read_result, xact_rvals[N_XACT]);
      PASS <= 1'b0;
    end
  end

  #(4*TICK) $display("First Write Loop: Write new values to r/w memory");
  for (N_XACT=0; N_XACT<N_ADDRS; N_XACT=N_XACT+1) begin
    xact_addr = xact_addrs[(N_XACT+1)*LB_ADW-1-:LB_ADW];
    #(4*TICK) lb_write_task(xact_addr, xact_wvals[(N_XACT+1)*32-1-:32]);
  end

  #(4*TICK) $display("Third Read Loop: Ensure writes took");
  for (N_XACT=0; N_XACT<N_ADDRS; N_XACT=N_XACT+1) begin
    xact_addr = xact_addrs[(N_XACT+1)*LB_ADW-1-:LB_ADW];
    #(4*TICK) lb_read_task(xact_addr, read_result);
    //$display("  addr = 0x%x; read_result = 0x%x", xact_addr, read_result);
    if (read_result != xact_wvals[(N_XACT+1)*32-1-:32]) begin
      $display("    ERROR: 0x%x != 0x%x", read_result, xact_wvals[(N_XACT+1)*32-1-:32]);
      PASS <= 1'b0;
    end
  end

  #(4*TICK) $display("Read initial values from extmod_bar");
  for (N_XACT=0; N_XACT<4; N_XACT=N_XACT+1) begin
    xact_addr = 24'h000010 + N_XACT[23:0];
    #(4*TICK) lb_read_task(xact_addr, read_result);
    $display("  addr = 0x%x; read_result = 0x%x", xact_addr, read_result);
    if (read_result != 32'h00000080 + N_XACT) begin
      $display("    ERROR: 0x%x != 0x%x", read_result, 32'h00000080 + N_XACT);
      PASS <= 1'b0;
    end
  end

  #(4*TICK) $display("TODO Write random values to extmod_bar");

  #(4*TICK) $display("Read initial values from extmod_foo[0]");
  for (N_XACT=0; N_XACT<4; N_XACT=N_XACT+1) begin
    xact_addr = 24'h000040 + N_XACT[23:0];
    #(4*TICK) lb_read_task(xact_addr, read_result);
    $display("  addr = 0x%x; read_result = 0x%x", xact_addr, read_result);
    if (read_result != 32'h00000080 + N_XACT) begin
      $display("    ERROR: 0x%x != 0x%x", read_result, 32'h00000080 + N_XACT);
      PASS <= 1'b0;
    end
  end

  #(4*TICK) $display("Clobbering one value from extmod_foo[0]");
  xact_addr = 24'h000040;
  #(4*TICK) lb_write_task(xact_addr, 32'h12345678);
  #(4*TICK) lb_read_task(xact_addr, read_result);
  if (read_result !== 32'h00000078) begin
    $display("    ERROR: 0x%x != 0x%x", read_result, 32'h00000078);
    PASS <= 1'b0;
  end

  #(4*TICK) $display("Read initial values from extmod_foo[1]");
  for (N_XACT=0; N_XACT<4; N_XACT=N_XACT+1) begin
    xact_addr = 24'h000050 + N_XACT[23:0];
    #(4*TICK) lb_read_task(xact_addr, read_result);
    $display("  addr = 0x%x; read_result = 0x%x", xact_addr, read_result);
    if (read_result != 32'h00000080 + N_XACT) begin
      $display("    ERROR: 0x%x != 0x%x", read_result, 32'h00000080 + N_XACT);
      PASS <= 1'b0;
    end
  end

  #(4*TICK) $display("Clobbering one value from extmod_foo[1]");
  xact_addr = 24'h000051;
  #(4*TICK) lb_write_task(xact_addr, 32'h89abcdef);
  #(4*TICK) lb_read_task(xact_addr, read_result);
  if (read_result !== 32'h000000ef) begin
    $display("    ERROR: 0x%x != 0x%x", read_result, 32'h000000ef);
    PASS <= 1'b0;
  end

  #(4*TICK) $display("Read initial values from extmod_foo[2]");
  for (N_XACT=0; N_XACT<4; N_XACT=N_XACT+1) begin
    xact_addr = 24'h000060 + N_XACT[23:0];
    #(4*TICK) lb_read_task(xact_addr, read_result);
    $display("  addr = 0x%x; read_result = 0x%x", xact_addr, read_result);
    if (read_result != 32'h00000080 + N_XACT) begin
      $display("    ERROR: 0x%x != 0x%x", read_result, 32'h00000080 + N_XACT);
      PASS <= 1'b0;
    end
  end

  #(4*TICK) $display("Clobbering one value from extmod_foo[2]");
  xact_addr = 24'h000062;
  #(4*TICK) lb_write_task(xact_addr, 32'h72625242);
  #(4*TICK) lb_read_task(xact_addr, read_result);
  if (read_result !== 32'h00000042) begin
    $display("    ERROR: 0x%x != 0x%x", read_result, 32'h00000042);
    PASS <= 1'b0;
  end

  #(4*TICK) $display("Read initial values from extmod_foo[3]");
  for (N_XACT=0; N_XACT<4; N_XACT=N_XACT+1) begin
    xact_addr = 24'h000070 + N_XACT[23:0];
    #(4*TICK) lb_read_task(xact_addr, read_result);
    $display("  addr = 0x%x; read_result = 0x%x", xact_addr, read_result);
    if (read_result != 32'h00000080 + N_XACT) begin
      $display("    ERROR: 0x%x != 0x%x", read_result, 32'h00000080 + N_XACT);
      PASS <= 1'b0;
    end
  end

  #(4*TICK) $display("Clobbering one value from extmod_foo[3]");
  xact_addr = 24'h000073;
  #(4*TICK) lb_write_task(xact_addr, 32'haaaaaa55);
  #(4*TICK) lb_read_task(xact_addr, read_result);
  if (read_result !== 32'h00000055) begin
    $display("    ERROR: 0x%x != 0x%x", read_result, 32'h00000055);
    PASS <= 1'b0;
  end

  #(4*TICK) $display("Read current values from extmod_foo[0]");
  for (N_XACT=0; N_XACT<4; N_XACT=N_XACT+1) begin
    xact_addr = 24'h000040 + N_XACT[23:0];
    if (N_XACT == 0) expected_val = 32'h00000078;
    else expected_val = 32'h00000080 + N_XACT;
    #(4*TICK) lb_read_task(xact_addr, read_result);
    $display("  addr = 0x%x; read_result = 0x%x", xact_addr, read_result);
    if (read_result !== expected_val) begin
      $display("    ERROR: 0x%x != 0x%x", read_result, expected_val);
      PASS <= 1'b0;
    end
  end

  #(4*TICK) $display("Read current values from extmod_foo[1]");
  for (N_XACT=0; N_XACT<4; N_XACT=N_XACT+1) begin
    xact_addr = 24'h000050 + N_XACT[23:0];
    if (N_XACT == 1) expected_val = 32'h000000ef;
    else expected_val = 32'h00000080 + N_XACT;
    #(4*TICK) lb_read_task(xact_addr, read_result);
    $display("  addr = 0x%x; read_result = 0x%x", xact_addr, read_result);
    if (read_result !== expected_val) begin
      $display("    ERROR: 0x%x != 0x%x", read_result, expected_val);
      PASS <= 1'b0;
    end
  end

  #(4*TICK) $display("Read current values from extmod_foo[2]");
  for (N_XACT=0; N_XACT<4; N_XACT=N_XACT+1) begin
    xact_addr = 24'h000060 + N_XACT[23:0];
    if (N_XACT == 2) expected_val = 32'h00000042;
    else expected_val = 32'h00000080 + N_XACT;
    #(4*TICK) lb_read_task(xact_addr, read_result);
    $display("  addr = 0x%x; read_result = 0x%x", xact_addr, read_result);
    if (read_result !== expected_val) begin
      $display("    ERROR: 0x%x != 0x%x", read_result, expected_val);
      PASS <= 1'b0;
    end
  end

  #(4*TICK) $display("Read current values from extmod_foo[3]");
  for (N_XACT=0; N_XACT<4; N_XACT=N_XACT+1) begin
    xact_addr = 24'h000070 + N_XACT[23:0];
    if (N_XACT == 3) expected_val = 32'h00000055;
    else expected_val = 32'h00000080 + N_XACT;
    #(4*TICK) lb_read_task(xact_addr, read_result);
    $display("  addr = 0x%x; read_result = 0x%x", xact_addr, read_result);
    if (read_result !== expected_val) begin
      $display("    ERROR: 0x%x != 0x%x", read_result, expected_val);
      PASS <= 1'b0;
    end
  end

  if (PASS) begin
    $display("PASS");
    $finish(0);
  end else begin
    $display("FAIL");
    $stop(0);
  end
end
`else // ndef HAND_ROLLED
`define GHOSTBUS_TEST_CSRS
`define DEBUG_READS
`define DEBUG_WRITES
`include "gb_testbench.vh"

initial begin
  @(posedge gb_clk) test_pass=1'b1;
  $display("Reading init values.");
  CSR_READ_CHECK_ALL();
  if (test_pass) $display("PASS");
  else begin
    $display("FAIL");
    $stop(0);
  end
  /*
  @(posedge gb_clk);
  CSR_WRITE_ALL();
  $display("Writing CSRs with random values.");

  @(posedge gb_clk) test_pass=1'b1;
  $display("Reading back written values.");
  CSR_READ_CHECK_ALL();
  if (test_pass) $display("PASS");
  else $display("FAIL");
  */
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
  $display("Reading RAM init values.");
  //TOP_BAZ_BAR_0_BAR_RAM_BASE
  GB_READ_CHECK(TOP_BAZ_BAR_0_BAR_RAM_BASE, 32'h00000082);
  GB_READ_CHECK(TOP_BAZ_BAR_0_BAR_RAM_BASE+1, 32'h00000083);

  //TOP_BAZ_BAR_1_BAR_RAM_BASE
  GB_READ_CHECK(TOP_BAZ_BAR_1_BAR_RAM_BASE, 32'h00000082);
  GB_READ_CHECK(TOP_BAZ_BAR_1_BAR_RAM_BASE+1, 32'h00000083);
  if (test_pass) $display("PASS");
  else begin
    $display("FAIL");
    $stop(0);
  end
  */

  //TOP_BAZ_GENERATOR_EXTMOD_BAR_BASE
  $display("Reading extmod_bar init values.");
  GB_READ_CHECK(TOP_BAZ_GENERATOR_EXTMOD_BAR_BASE,   32'h00000080);
  GB_READ_CHECK(TOP_BAZ_GENERATOR_EXTMOD_BAR_BASE+1, 32'h00000081);
  GB_READ_CHECK(TOP_BAZ_GENERATOR_EXTMOD_BAR_BASE+2, 32'h00000082);
  GB_READ_CHECK(TOP_BAZ_GENERATOR_EXTMOD_BAR_BASE+3, 32'h00000083);

  $display("Writing new values to extmod_bar.");
  GB_WRITE(TOP_BAZ_GENERATOR_EXTMOD_BAR_BASE,   32'hbeef0099); // only the last 8 bits are used
  GB_WRITE(TOP_BAZ_GENERATOR_EXTMOD_BAR_BASE+1, 32'hcafe445a); // only the last 8 bits are used
  GB_WRITE(TOP_BAZ_GENERATOR_EXTMOD_BAR_BASE+2, 32'h00000011); // only the last 8 bits are used
  GB_WRITE(TOP_BAZ_GENERATOR_EXTMOD_BAR_BASE+3, 32'h000000bb); // only the last 8 bits are used

  $display("Reading back values written to extmod_bar.");
  GB_READ_CHECK(TOP_BAZ_GENERATOR_EXTMOD_BAR_BASE,   32'h00000099);
  GB_READ_CHECK(TOP_BAZ_GENERATOR_EXTMOD_BAR_BASE+1, 32'h0000005a);
  GB_READ_CHECK(TOP_BAZ_GENERATOR_EXTMOD_BAR_BASE+2, 32'h00000011);
  GB_READ_CHECK(TOP_BAZ_GENERATOR_EXTMOD_BAR_BASE+3, 32'h000000bb);

  //TOP_FOO_GENERATOR_EXTMOD_FOO_0_BASE
  $display("Reading extmod_foo[0] init values.");
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_0_BASE,   32'h00000080);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_0_BASE+1, 32'h00000081);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_0_BASE+2, 32'h00000082);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_0_BASE+3, 32'h00000083);

  $display("Writing new values to extmod_foo[0].");
  GB_WRITE(TOP_FOO_GENERATOR_EXTMOD_FOO_0_BASE,   32'hbeef0032); // only the last 8 bits are used
  GB_WRITE(TOP_FOO_GENERATOR_EXTMOD_FOO_0_BASE+1, 32'hcafe4409); // only the last 8 bits are used
  GB_WRITE(TOP_FOO_GENERATOR_EXTMOD_FOO_0_BASE+2, 32'h00000044); // only the last 8 bits are used
  GB_WRITE(TOP_FOO_GENERATOR_EXTMOD_FOO_0_BASE+3, 32'h000000de); // only the last 8 bits are used

  $display("Reading back values written to extmod_foo[0].");
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_0_BASE,   32'h00000032);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_0_BASE+1, 32'h00000009);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_0_BASE+2, 32'h00000044);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_0_BASE+3, 32'h000000de);

  //TOP_FOO_GENERATOR_EXTMOD_FOO_1_BASE
  $display("Reading extmod_foo[1] init values.");
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_1_BASE,   32'h00000080);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_1_BASE+1, 32'h00000081);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_1_BASE+2, 32'h00000082);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_1_BASE+3, 32'h00000083);

  $display("Writing new values to extmod_foo[1].");
  GB_WRITE(TOP_FOO_GENERATOR_EXTMOD_FOO_1_BASE,   32'hcedf4321); // only the last 8 bits are used
  GB_WRITE(TOP_FOO_GENERATOR_EXTMOD_FOO_1_BASE+1, 32'h99887766); // only the last 8 bits are used
  GB_WRITE(TOP_FOO_GENERATOR_EXTMOD_FOO_1_BASE+2, 32'h54657687); // only the last 8 bits are used
  GB_WRITE(TOP_FOO_GENERATOR_EXTMOD_FOO_1_BASE+3, 32'h98a9bacb); // only the last 8 bits are used

  $display("Reading back values written to extmod_foo[1].");
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_1_BASE,   32'h00000021);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_1_BASE+1, 32'h00000066);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_1_BASE+2, 32'h00000087);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_1_BASE+3, 32'h000000cb);

  //TOP_FOO_GENERATOR_EXTMOD_FOO_2_BASE
  $display("Reading extmod_foo[2] init values.");
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_2_BASE,   32'h00000080);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_2_BASE+1, 32'h00000081);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_2_BASE+2, 32'h00000082);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_2_BASE+3, 32'h00000083);

  $display("Writing new values to extmod_foo[2].");
  GB_WRITE(TOP_FOO_GENERATOR_EXTMOD_FOO_2_BASE,   32'hcedf0123); // only the last 8 bits are used
  GB_WRITE(TOP_FOO_GENERATOR_EXTMOD_FOO_2_BASE+1, 32'h9988d984); // only the last 8 bits are used
  GB_WRITE(TOP_FOO_GENERATOR_EXTMOD_FOO_2_BASE+2, 32'h5465ac30); // only the last 8 bits are used
  GB_WRITE(TOP_FOO_GENERATOR_EXTMOD_FOO_2_BASE+3, 32'h98a9f10a); // only the last 8 bits are used

  $display("Reading back values written to extmod_foo[2].");
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_2_BASE,   32'h00000023);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_2_BASE+1, 32'h00000084);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_2_BASE+2, 32'h00000030);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_2_BASE+3, 32'h0000000a);

  //TOP_FOO_GENERATOR_EXTMOD_FOO_3_BASE
  $display("Reading extmod_foo[3] init values.");
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_3_BASE,   32'h00000080);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_3_BASE+1, 32'h00000081);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_3_BASE+2, 32'h00000082);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_3_BASE+3, 32'h00000083);

  $display("Writing new values to extmod_foo[3].");
  GB_WRITE(TOP_FOO_GENERATOR_EXTMOD_FOO_3_BASE,   32'h55544433); // only the last 8 bits are used
  GB_WRITE(TOP_FOO_GENERATOR_EXTMOD_FOO_3_BASE+1, 32'h9988d901); // only the last 8 bits are used
  GB_WRITE(TOP_FOO_GENERATOR_EXTMOD_FOO_3_BASE+2, 32'h5465ac20); // only the last 8 bits are used
  GB_WRITE(TOP_FOO_GENERATOR_EXTMOD_FOO_3_BASE+3, 32'h98a9f105); // only the last 8 bits are used

  $display("Reading back values written to extmod_foo[3].");
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_3_BASE,   32'h00000033);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_3_BASE+1, 32'h00000001);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_3_BASE+2, 32'h00000020);
  GB_READ_CHECK(TOP_FOO_GENERATOR_EXTMOD_FOO_3_BASE+3, 32'h00000005);

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
`endif

endmodule
