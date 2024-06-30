`timescale 1ns/1ps

module foo #(
  parameter AW = 24,
  parameter DW = 32,
  parameter GW = 8,
  parameter RD = 8
) (
  input clk
);

reg [3:0] foo_reg=0;                            // Non-host-accessible register

(* ghostbus_ha *) reg [GW-1:0] foo_ha_reg=8'h42;  // Host-accessible register (will be auto-decoded)

(* ghostbus_addr='h40 *)
reg [3:0] foo_ram [0:RD-1];                        // Host-accessible RAM with pre-defined relative address (0x40)

`ifdef GHOSTBUS_LIVE
`GHOSTBUS_foo
`endif

baz #(
  .AW(AW),
  .DW(DW)
) baz_0 (
  .clk(clk),
  .demo_sig(foo_reg[0])
`ifdef GHOSTBUS_LIVE
`GHOSTBUS_foo_baz_0
`endif
);

bar #(
  .AW(AW),
  .DW(DW)
) bar_0 (
  .clk(clk),
  .demo_sig(foo_reg[1])
`ifdef GHOSTBUS_LIVE
`GHOSTBUS_foo_bar_0
`endif
);

endmodule
