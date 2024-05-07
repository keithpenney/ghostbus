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

reg [3:0] foo_reg=0;                            // Non-host-accessible register

(* ghostbus_ha *) reg [31:0] foo_ha_reg=8'h42; // Host-accessible register (will be auto-decoded)

(* ghostbus_addr='h40 *)
reg [3:0] foo_ram [0:7];                    // Host-accessible RAM with pre-defined relative address (0x40)

`ifdef GHOSTBUS_LIVE
`GHOSTBUS_MAGIC
`endif

wire [DW-1:0] dout_baz, dout_bar; // Is this going to kill the whole concept dead?

baz #(
  .AW(AW),
  .DW(DW)
) baz_0 (
  .clk(clk),
  .addr(addr),
  .din(din),
  .dout(dout_baz),
  .we(we)
);

bar #(
  .AW(AW),
  .DW(DW)
) bar_0 (
  .clk(clk),
  .addr(addr),
  .din(din),
  .dout(dout_bar),
  .we(we)
);

endmodule
