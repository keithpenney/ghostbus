`timescale 1ns/1ps

`ifndef GHOSTBUS_LIVE
  `define GHOSTBUSPORTS
  `define GHOSTBUS_submod_bar
`else
  `include "defs.vh"
`endif

module submod_bar #(
  parameter AW = 24,
  parameter DW = 32
) (
   input clk
  ,input demo_sig
  `GHOSTBUSPORTS
);

(* ghostbus_ha *) reg signed [7:0] bar_reg=8'hcc;      // Host-accessible register (will be auto-decoded)
(* ghostbus_ha *) reg [31:0] bar_reg_two=32'hceceface;  // Another host-accessible register

(* ghostbus_ha, ghostbus_addr='h100 *)
reg [7:0] bar_ram [0:63];                       // Host-accessible RAM with pre-defined relative address (0x100)
integer N=0;
initial begin
  for (N=0; N<64; N=N+1) begin
    bar_ram[N] = 8'h82 + N[7:0];
  end
end

`GHOSTBUS_submod_bar

endmodule
