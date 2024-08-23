`timescale 1ns/1ps

module foo #(
  parameter AW = 24,
  parameter DW = 32,
  parameter GW = 8,
  parameter RD = 8
) (
  input clk
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

reg [3:0] foo_reg=0;                            // Non-host-accessible register

(* ghostbus, ghostbus_alias="holiday_pasta" *) reg [GW-1:0] foo_ha_reg=8'h42;  // Host-accessible register (will be auto-decoded)
(* ghostbus_ws="foo_ha_reg" *) reg foo_ha_reg_write_strobe=1'b0;  // Associated write-strobe; will strobe high when foo_ha_reg is written to
(* ghostbus_rs="foo_ha_reg" *) reg foo_ha_reg_read_strobe=1'b0;  // Associated read-strobe; will strobe high when foo_ha_reg is read
//(* ghostbus_strobe *) reg foo_strobe=1'b0;  // A strobe (write-only; value is ignored; pulse high for one clock cycle on write)

(* ghostbus_addr='h40 *)
reg [3:0] foo_ram [0:RD-1];                        // Host-accessible RAM with pre-defined relative address (0x40)
(* ghostbus *) wire [5:0] ima_wire;
reg  [5:0] ima_reg;

`ifdef GHOSTBUS_LIVE
`GHOSTBUS_foo
`else
  `ifdef MANUAL_TEST_ACTUALLY_MANUAL
    // Manual decoding
    wire en_local = gb_addr[11:9] == 3'b000; // 0x000-0x1ff
    reg  [31:0] local_din=0;
    // submodule bar_0
    wire [31:0] gb_din_bar_0;
    wire en_bar_0 = gb_addr[11:9] == 3'b001; // 0x200-0x3ff
    wire [11:0] gb_addr_bar_0 = {3'b000, gb_addr[8:0]}; // address relative to own base (0x0)
    wire gb_we_bar_0=gb_we & en_bar_0;
    // submodule baz_0
    wire [31:0] gb_din_baz_0;
    wire en_baz_0 = gb_addr[11:10] == 2'b01; // 0x400-0x7ff
    wire [11:0] gb_addr_baz_0 = {2'b00, gb_addr[9:0]}; // address relative to own base (0x0)
    wire gb_we_baz_0=gb_we & en_baz_0;
    // din routing
    assign gb_din = en_baz_0 ? gb_din_baz_0 :
                    en_bar_0 ? gb_din_bar_0 :
                    en_local ? local_din :
                    32'h00000000;
    // local rams
    localparam FOO_RAM_AW = $clog2(RD);
    wire en_foo_ram = gb_addr[8:3] == 6'b001000; // 0x40-0x47
    // bus decoding
    always @(posedge gb_clk) begin
      // local writes
      if (en_local & gb_we) begin
        // foo_ram writes
        if (en_foo_ram) begin
          foo_ram[gb_addr[FOO_RAM_AW-1:0]] <= gb_dout[3:0];
        end
        // CSR writes
        casez (gb_addr[8:0])
          9'h0: foo_ha_reg <= gb_dout[GW-1:0];
          default: foo_ha_reg <= foo_ha_reg;
        endcase
      end
      // local reads
      if (en_local & ~gb_we) begin
        // foo_ram reads
        if (en_foo_ram) begin
          local_din <= {{32-4{1'b0}}, foo_ram[gb_addr[FOO_RAM_AW-1:0]]};
        end else begin
          // CSR reads
          casez (gb_addr[8:0])
            9'h0: local_din <= {{32-GW{1'b0}}, foo_ha_reg};
            default: local_din <= local_din;
          endcase
        end
      end
    end
  `else
    `ifdef MANUAL_TEST
// local init
wire en_local = gb_addr[11:7] == 5'h0; // 0x0-0x80
reg  [31:0] local_din=0;
// local rams
localparam FOO_RAM_AW = $clog2(RD-1+1);
wire en_foo_ram = gb_addr[6:3] == 4'h8;
// submodule bar_0
wire [31:0] gb_din_bar_0;
wire en_bar_0 = gb_addr[11:9] == 3'h1; // 0x200-0x3ff
wire [11:0] gb_addr_bar_0 = {3'h0, gb_addr[8:0]}; // address relative to own base (0x0)
wire gb_we_bar_0=gb_we & en_bar_0;
// submodule baz_0
wire [31:0] gb_din_baz_0;
wire en_baz_0 = gb_addr[11:10] == 2'h1; // 0x400-0x7ff
wire [11:0] gb_addr_baz_0 = {2'h0, gb_addr[9:0]}; // address relative to own base (0x0)
wire gb_we_baz_0=gb_we & en_baz_0;
// din routing
assign gb_din = en_local ? local_din :
              en_bar_0 ? gb_din_bar_0 :
              en_baz_0 ? gb_din_baz_0 :
              32'h00000000;
// bus decoding
always @(posedge gb_clk) begin
  // local writes
  if (en_local & gb_we) begin
    // RAM writes
    if (en_foo_ram) begin
      foo_ram[gb_addr[FOO_RAM_AW-1:0]] <= gb_dout[3:0];
    end
    // CSR writes
    casez (gb_addr[6:0])
    7'h0: foo_ha_reg <= gb_dout[GW-1:0];
    endcase
  end // if (en_local & gb_we)
  // local reads
  if (en_local & ~gb_we) begin
    // RAM reads
    if (en_foo_ram) begin
      local_din <= {{32-3+1{1'b0}}, foo_ram[gb_addr[FOO_RAM_AW-1:0]]};
    end
    // CSR reads
    casez (gb_addr[6:0])
    7'h0: local_din <= {{32-GW-1+1{1'b0}}, foo_ha_reg};
    endcase

  end // if (en_local & ~gb_we)
end // always @(posedge gb_clk)
    `endif
  `endif
`endif

baz #(
  .AW(AW),
  .DW(DW)
) baz_0 (
  .clk(clk),
  .demo_sig(foo_reg[0])
`ifdef GHOSTBUS_LIVE
`GHOSTBUS_foo_baz_0
`else
  `ifdef MANUAL_TEST
  ,.gb_clk(gb_clk)    // input
  ,.gb_addr(gb_addr_baz_0)  // input [11:0]
  ,.gb_dout(gb_dout)  // input [31:0]
  ,.gb_din(gb_din_baz_0) // output [31:0]
  ,.gb_we(gb_we_baz_0) // input
  `endif
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

localparam GH_AW = 13;
localparam GH_DW = 32;
// Testing a third bus (routed nowhere right now)
(* ghostbus_port="clk", ghostbus_name="greyhound" *)       wire hound_clk=clk;
(* ghostbus_port="addr", ghostbus_name="greyhound" *)      reg [GH_AW-1:0] hound_addr=0;
(* ghostbus_port="wdata", ghostbus_name="greyhound" *)     reg [GH_DW-1:0] hound_dout=0;
(* ghostbus_port="rdata", ghostbus_name="greyhound" *)     wire [GH_DW-1:0] hound_din;
(* ghostbus_port="we, wstb", ghostbus_name="greyhound" *)  reg hound_we=1'b0;
(* ghostbus_port="rstb", ghostbus_name="greyhound" *)      reg hound_rstb=1'b0; // optional




endmodule
