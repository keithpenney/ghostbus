`timescale 1ns/1ps

module foo #(
  parameter AW = 24,
  parameter DW = 32
) (
  input clk,
  input [AW-1:0] addr,
  input [DW-1:0] din,
  output [DW-1:0] dout,
  input we
);

reg [3:0] foo=0;                            // Non-host-accessible register

(* ghostbus_ha *) reg [7:0] bar=8'h42;      // Host-accessible register (will be auto-decoded)

(* ghostbus_ha, ghostbus_addr='h100 *)
reg [7:0] baz [0:63];                       // Host-accessible RAM with pre-defined relative address (0x100)

endmodule
