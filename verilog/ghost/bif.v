`timescale 1ns/1ps

module bif #(
  parameter AW = 24,
  parameter DW = 32
) (
  input clk
);

reg [DW-1:0] bif_r=0;
always @(posedge clk) bif_r <= bif_r + 1;

endmodule
