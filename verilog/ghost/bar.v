`timescale 1ns/1ps

module bar #(
  parameter AW = 24,
  parameter DW = 32
) (
  input clk,
  input demo_sig
);

reg [3:0] bar_reg=1;                            // Non-host-accessible register

(* ghostbus_ha *) reg [7:0] bar_ha_reg=8'h42;      // Host-accessible register (will be auto-decoded)
(* ghostbus_ha *) reg [31:0] bar_ha_reg_two=1234;  // Another host-accessible register

(* ghostbus_ha, ghostbus_addr='h100 *)
reg [7:0] bar_ram [0:63];                       // Host-accessible RAM with pre-defined relative address (0x100)

`ifdef GHOSTBUS_LIVE
`GHOSTBUS_MAGIC
`endif

endmodule
