`timescale 1ns/1ps

// An interposer

module baz #(
  parameter AW = 24,
  parameter DW = 32
) (
   input clk
  ,input demo_sig
`ifdef GHOSTBUS_LIVE
`GHOSTBUSPORTS
`else
  `ifdef MANUAL_TEST
  // Manual ports
  ,input  gb_clk
  ,input  [11:0] gb_addr
  ,input  [31:0] gb_dout
  ,output [31:0] gb_din
  ,input  gb_we
  `endif
`endif
);

// Interesting demo: Enabling this doubles the size of the memory map!
//(* ghostbus_ha *) reg [7:0] baz_reg=100;

`ifdef GHOSTBUS_LIVE
`GHOSTBUS_baz
`else
  `ifdef MANUAL_TEST
    // Manual decoding
    // submodule bar_0
    wire [31:0] gb_din_bar_0;
    wire en_bar_0 = gb_addr[11:9] == 3'b001; // 0x200-0x3ff
    wire [11:0] gb_addr_bar_0 = {3'b000, gb_addr[8:0]}; // address relative to own base (0x0)
    wire gb_we_bar_0=gb_we & en_bar_0;
    // submodule bar_1
    wire [31:0] gb_din_bar_1;
    wire en_bar_1 = gb_addr[11:9] == 3'b000; // 0x000-0x1ff
    wire [11:0] gb_addr_bar_1 = {3'b000, gb_addr[8:0]}; // address relative to own base (0x0)
    wire gb_we_bar_1=gb_we & en_bar_1;
    // din routing
    assign gb_din = en_bar_1 ? gb_din_bar_1 :
                    en_bar_0 ? gb_din_bar_0 :
                    32'h00000000;
  `endif
`endif

bar #(
  .AW(AW-1),
  .DW(DW)
) bar_0 (
   .clk(clk)
  ,.demo_sig(demo_sig)
`ifdef GHOSTBUS_LIVE
`GHOSTBUS_baz_bar_0
`else
  `ifdef MANUAL_TEST
  ,.gb_clk(gb_clk)    // input
  ,.gb_addr(gb_addr_bar_0)  // input [11:0]
  ,.gb_dout(gb_dout)  // input [31:0]
  ,.gb_din(gb_din_bar_0) // output [31:0]
  ,.gb_we(gb_we_bar_0) // input
  `endif
`endif
);

bar #(
  .AW(AW),
  .DW(DW)
) bar_1 (
   .clk(clk)
  ,.demo_sig(demo_sig)
`ifdef GHOSTBUS_LIVE
`GHOSTBUS_baz_bar_1
`else
  `ifdef MANUAL_TEST
  ,.gb_clk(gb_clk)    // input
  ,.gb_addr(gb_addr_bar_1)  // input [11:0]
  ,.gb_dout(gb_dout)  // input [31:0]
  ,.gb_din(gb_din_bar_1) // output [31:0]
  ,.gb_we(gb_we_bar_1) // input
  `endif
`endif
);

endmodule
