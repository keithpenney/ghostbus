`timescale 1ns/1ps

// An interposer

module baz #(
  parameter AW = 24,
  parameter DW = 32
) (
  input clk,
  input demo_sig
);

reg demo_sig_r=1'b0; // Some other local net
always @(posedge clk) demo_sig_r <= demo_sig;

`ifdef GHOSTBUS_LIVE
`GHOSTBUS_MAGIC
`endif

bar #(
  .AW(AW),
  .DW(DW)
) bar_0 (
  .clk(clk),
  .demo_sig(demo_sig)
`ifdef GHOSTBUS_LIVE
`GHOSTBUS_bar_0
`endif
);

bar #(
  .AW(AW),
  .DW(DW)
) bar_1 (
  .clk(clk),
  .demo_sig(demo_sig_r)
`ifdef GHOSTBUS_LIVE
`GHOSTBUS_bar_1
`endif
);

endmodule
