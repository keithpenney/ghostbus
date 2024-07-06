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

`ifdef GHOSTBUS_LIVE
  `include "defs.vh"
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

task GB_WRITE (input [11:0] addr, input [31:0] data);
  begin
    gb_addr = addr;
    gb_dout = data;
    gb_we = 1'b1;
`ifndef YOSYS
    #TICK $display("Wrote to addr 0x%x: 0x%x", addr, data);
`else
    #TICK;
`endif
  end
endtask

localparam RDDELAY = 2;
task GB_READ (input [11:0] addr);
  begin
    gb_addr = addr;
    gb_dout = 32'h00000000;
    gb_we = 1'b0;
`ifndef YOSYS
    #(RDDELAY*TICK) $display("Read from addr 0x%x: 0x%x", addr, gb_din);
`else
    #(RDDELAY*TICK);
`endif
  end
endtask

localparam [11:0] BASE_foo        = 12'h000;
localparam [11:0] ADDR_foo_ha_reg = 12'h000;
localparam [11:0] BASE_foo_ram = 12'h040;
localparam [11:0] SIZE_foo_ram = 12'h008;

localparam [11:0] BASE_foo_bar_0  = 12'h200;
localparam [11:0] ADDR_bar_ha_reg = 12'h000; // relative to BASE
localparam [11:0] ADDR_bar_ha_reg_two = 12'h001; // relative to BASE
localparam [11:0] BASE_bar_ram = 12'h100; // relative to BASE
localparam [11:0] SIZE_bar_ram = 12'h040; // relative to BASE

localparam [11:0] BASE_foo_baz_0_bar_1  = 12'h400;
localparam [11:0] BASE_foo_baz_0_bar_0  = 12'h600;

`ifndef YOSYS
// =========== Stimulus =============
localparam [0:0] skip_ram=1'b1;
integer N;
initial begin
  $display("================ First Pass: Reads ===================");
  // Read from foo
  #TICK GB_READ(BASE_foo + ADDR_foo_ha_reg);
  if (~skip_ram) begin
    for (N=0; N<SIZE_foo_ram; N=N+1) begin
      #TICK GB_READ(BASE_foo + BASE_foo_ram + N);
    end
  end
  // Read from foo.bar_0
  #TICK GB_READ(BASE_foo_bar_0 + ADDR_bar_ha_reg);
  #TICK GB_READ(BASE_foo_bar_0 + ADDR_bar_ha_reg_two);
  if (~skip_ram) begin
    for (N=0; N<SIZE_bar_ram; N=N+1) begin
      #TICK GB_READ(BASE_foo_bar_0 + BASE_bar_ram + N);
    end
  end
  // Read from foo.baz_0.bar_1
  #TICK GB_READ(BASE_foo_baz_0_bar_1 + ADDR_bar_ha_reg);
  #TICK GB_READ(BASE_foo_baz_0_bar_1 + ADDR_bar_ha_reg_two);
  if (~skip_ram) begin
    for (N=0; N<SIZE_bar_ram; N=N+1) begin
      #TICK GB_READ(BASE_foo_baz_0_bar_1 + BASE_bar_ram + N);
    end
  end
  // Read from foo.baz_0.bar_0
  #TICK GB_READ(BASE_foo_baz_0_bar_0 + ADDR_bar_ha_reg);
  #TICK GB_READ(BASE_foo_baz_0_bar_0 + ADDR_bar_ha_reg_two);
  if (~skip_ram) begin
    for (N=0; N<SIZE_bar_ram; N=N+1) begin
      #TICK GB_READ(BASE_foo_baz_0_bar_0 + BASE_bar_ram + N);
    end
  end

  $display("=============== Second Pass: Writes ==================");
  // Write to foo
  #TICK GB_WRITE(BASE_foo + ADDR_foo_ha_reg, 32'h00000025);
  // Write to foo.bar_0
  #TICK GB_WRITE(BASE_foo_bar_0 + ADDR_bar_ha_reg, 32'h000000bb);
  #TICK GB_WRITE(BASE_foo_bar_0 + ADDR_bar_ha_reg_two, 32'hdadb00b5);
  // Write to foo.baz_0.bar_1
  #TICK GB_WRITE(BASE_foo_baz_0_bar_1 + ADDR_bar_ha_reg, 32'h000000dd);
  #TICK GB_WRITE(BASE_foo_baz_0_bar_1 + ADDR_bar_ha_reg_two, 32'h12345678);
  // Write to foo.baz_0.bar_0
  #TICK GB_WRITE(BASE_foo_baz_0_bar_0 + ADDR_bar_ha_reg, 32'h000000ee);
  #TICK GB_WRITE(BASE_foo_baz_0_bar_0 + ADDR_bar_ha_reg_two, 32'hfedcba98);

  $display("================ Third Pass: Reads ===================");
  // Read from foo
  #TICK GB_READ(BASE_foo + ADDR_foo_ha_reg);
  if (~skip_ram) begin
    for (N=0; N<SIZE_foo_ram; N=N+1) begin
      #TICK GB_READ(BASE_foo + BASE_foo_ram + N);
    end
  end
  // Read from foo.bar_0
  #TICK GB_READ(BASE_foo_bar_0 + ADDR_bar_ha_reg);
  #TICK GB_READ(BASE_foo_bar_0 + ADDR_bar_ha_reg_two);
  if (~skip_ram) begin
    for (N=0; N<SIZE_bar_ram; N=N+1) begin
      #TICK GB_READ(BASE_foo_bar_0 + BASE_bar_ram + N);
    end
  end
  // Read from foo.baz_0.bar_1
  #TICK GB_READ(BASE_foo_baz_0_bar_1 + ADDR_bar_ha_reg);
  #TICK GB_READ(BASE_foo_baz_0_bar_1 + ADDR_bar_ha_reg_two);
  if (~skip_ram) begin
    for (N=0; N<SIZE_bar_ram; N=N+1) begin
      #TICK GB_READ(BASE_foo_baz_0_bar_1 + BASE_bar_ram + N);
    end
  end
  // Read from foo.baz_0.bar_0
  #TICK GB_READ(BASE_foo_baz_0_bar_0 + ADDR_bar_ha_reg);
  #TICK GB_READ(BASE_foo_baz_0_bar_0 + ADDR_bar_ha_reg_two);
  if (~skip_ram) begin
    for (N=0; N<SIZE_bar_ram; N=N+1) begin
      #TICK GB_READ(BASE_foo_baz_0_bar_0 + BASE_bar_ram + N);
    end
  end
  $display("Done");
  $finish(0);
end
`endif // YOSYS

endmodule
