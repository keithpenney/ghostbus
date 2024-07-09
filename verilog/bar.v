`timescale 1ns/1ps

module bar #(
  parameter AW = 24,
  parameter DW = 32
) (
   input clk
  ,input demo_sig
`ifdef GHOSTBUS_LIVE
`GHOSTBUS_ports
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

reg [3:0] bar_reg=1;                            // Non-host-accessible register

(* ghostbus_ha *) reg [7:0] bar_ha_reg=8'hcc;      // Host-accessible register (will be auto-decoded)
(* ghostbus_ha *) reg [31:0] bar_ha_reg_two=32'hceceface;  // Another host-accessible register

(* ghostbus_ha, ghostbus_addr='h100 *)
reg [7:0] bar_ram [0:63];                       // Host-accessible RAM with pre-defined relative address (0x100)

`ifdef GHOSTBUS_LIVE
`GHOSTBUS_bar
`else
  `ifdef MANUAL_TEST
    // Manual decoding
    wire en_local = gb_addr[11:9] == 3'b000; // 0x000-0x1ff
    reg  [31:0] local_din=0;
    // din routing
    assign gb_din = en_local ? local_din :
                    32'h00000000;
    // local rams
    localparam BAR_RAM_AW = $clog2(64);
    wire en_bar_ram = gb_addr[11:6] == 6'b000100; // 0x100-0x13f
    // bus decoding
    always @(posedge gb_clk) begin
      // local writes
      if (en_local & gb_we) begin
        // bar_ram writes
        if (en_bar_ram) begin
          bar_ram[gb_addr[BAR_RAM_AW-1:0]] <= gb_dout[7:0];
        end
        // CSR writes
        casez (gb_addr[8:0])
          9'h0: bar_ha_reg <= gb_dout[7:0];
          9'h1: bar_ha_reg_two <= gb_dout[31:0];
          default: bar_ha_reg <= bar_ha_reg; // just to prevent incomplete case warning
        endcase
      end
      // local reads
      if (en_local & ~gb_we) begin
        // bar_ram reads
        if (en_bar_ram) begin
          local_din <= {{32-8{1'b0}}, bar_ram[gb_addr[BAR_RAM_AW-1:0]]};
        end else begin
          // CSR reads
          casez (gb_addr[8:0])
            9'h0: local_din <= {{32-8{1'b0}}, bar_ha_reg};
            9'h1: local_din <= {{32-32{1'b0}}, bar_ha_reg_two};
            default: local_din <= local_din;
          endcase
        end
      end
    end
  `endif
`endif

bif #(
  .AW(12),
  .DW(8)
) bif_0 (
  .clk(clk)
);

bif #(
  .AW(1),
  .DW(4)
) bif_1 (
  .clk(clk)
);

endmodule
