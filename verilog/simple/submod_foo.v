`timescale 1ns/1ps

`ifndef GHOSTBUS_LIVE
  `define GHOSTBUSPORTS
  `define GHOSTBUS_submod_foo
  `define GHOSTBUS_submod_foo_bar_0
  `define GHOSTBUS_submod_foo_baz_0
`else
  `include "defs.vh"
`endif

module submod_foo #(
  parameter AW = 24,
  parameter DW = 32,
  parameter GW = 8,
  parameter RD = 8
) (
  input clk
  `GHOSTBUSPORTS
);

reg [3:0] foo_reg=0;                            // Non-host-accessible register

(* ghostbus *) reg [GW-1:0] foo_ha_reg=8'h42;  // Host-accessible register (will be auto-decoded)
(* ghostbus_ws="foo_ha_reg" *) reg foo_ha_reg_write_strobe=1'b0;  // Associated write-strobe; will strobe high when foo_ha_reg is written to
(* ghostbus_rs="foo_ha_reg" *) reg foo_ha_reg_read_strobe=1'b0;  // Associated read-strobe; will strobe high when foo_ha_reg is read
//(* ghostbus_strobe *) reg foo_strobe=1'b0;  // A strobe (write-only; value is ignored; pulse high for one clock cycle on write)

(* ghostbus_addr='h40 *) reg [3:0] foo_ram [0:RD-1]; // Host-accessible RAM with pre-defined relative address (0x40)
integer N=0;
initial begin
  for (N=0; N<RD; N=N+1) begin
    foo_ram[N] = 4'h1 + N[3:0];
  end
end
(* ghostbus *) wire [5:0] ima_wire = 6'h2c;
reg  [5:0] ima_reg;

`GHOSTBUS_submod_foo

submod_baz #(
  .AW(AW),
  .DW(DW)
) baz_0 (
  .clk(clk),
  .demo_sig(foo_reg[0])
  `GHOSTBUS_submod_foo_baz_0
);

submod_bar #(
  .AW(AW),
  .DW(DW)
) bar_0 (
  .clk(clk),
  .demo_sig(foo_reg[1])
  `GHOSTBUS_submod_foo_bar_0
);

endmodule
