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

wire [23:0] gb_addr;
wire [31:0] gb_wdata;
wire [31:0] gb_rdata;
wire gb_wen;
wire gb_rstb;
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

wire lb_clk = gb_clk;
`include "localbus.vh"
assign gb_addr = lb_addr;
assign gb_wdata = lb_wdata;
assign lb_rdata = gb_rdata;
assign gb_wen = lb_write;
assign gb_rstb = lb_rstb;

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

reg [31:0] read_result=0;
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

  if (PASS) begin
    $display("PASS");
    $finish(0);
  end else begin
    $display("FAIL");
    $stop(0);
  end
end
`else
initial begin
  $display("TODO: ghostbus support testbench");
  $finish(0);
end

`endif

endmodule
