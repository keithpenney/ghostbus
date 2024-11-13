// Top module for the 'generate' codebase

`ifndef GHOSTBUS_LIVE
  `define GHOSTBUS_top
  `define GHOSTBUS_top_baz
  `define GHOSTBUS_top_foo
`endif

module top #(
  parameter FOO_COPIES = 4,
  parameter TOP_BAZ = 1
) (
  (* ghostbus_port="clk"  *) input  gb_clk,
  (* ghostbus_port="addr" *) input  [23:0] gb_addr,
  (* ghostbus_port="wdata"*) input  [31:0] gb_wdata,
  (* ghostbus_port="rdata"*) output [31:0] gb_rdata,
  (* ghostbus_port="wen, wstb"*) input gb_wen,
  (* ghostbus_port="rstb"*)  input gb_rstb
);

localparam FOO_AW = 24;
localparam FOO_DW = 32;
localparam FOO_GW = 8;
localparam FOO_RD = 8;

(* ghostbus *) reg [7:0] top_reg=8'h42;

// ===========================================================================
`ifdef HAND_ROLLED
/* Memory Map

 * FOO_COPIES = 4
 * TOP_BAZ = 1
 * To add:
 CHECK * 1 copy of top_reg
 CHECK * 4 copies of top_foo_n
 CHECK * 4 copies of foo_ram
 CHECK * 4 copies of submod_foo
 CHECK * 1 copy of top_baz
 CHECK * 1 copy of baz_ram
 CHECK * 1 copy of submod_baz

 * foo_ram needs 3 bits AW
 * 4 copies of foo_ram need 5 bits AW
 * baz_ram needs 3 bits AW
 * submod_bar needs 6 bits AW
 * submod_baz needs 7 bits AW
 * submod_foo needs 8 bits AW

 * Start    Stop      Mod
 * ----------------------
 * 0x0000   0x0000    top_reg
 * 0x0001   0x0001    top_baz
 * 0x0004   0x0004    top_foo_n[0]
 * 0x0005   0x0005    top_foo_n[1]
 * 0x0006   0x0006    top_foo_n[2]
 * 0x0007   0x0007    top_foo_n[3]
 * 0x0008   0x000f    baz_ram
 * 0x0020   0x0027    foo_ram[0]
 * 0x0028   0x002f    foo_ram[1]
 * 0x0030   0x0037    foo_ram[2]
 * 0x0038   0x003f    foo_ram[3]  -- end of local
 * 0x0080   0x00ff    baz
 * 0x0100   0x01ff    foo[0]
 * 0x0200   0x02ff    foo[1]
 * 0x0300   0x03ff    foo[2]
 * 0x0400   0x04ff    foo[3]
 */

wire en_local = gb_addr[23:6] == 18'h00000; // 0x0-0x3f
reg  [31:0] local_din=0;

reg [3:0] foo_generator_top_foo_n_r [0:FOO_COPIES-1];
reg [3:0] foo_generator_top_foo_n_w [0:FOO_COPIES-1];

reg [3:0] baz_generator_top_baz_w=0;
reg [3:0] baz_generator_top_baz_r=0;

wire [FOO_COPIES-1:0] addrhit_foo_ram;
localparam FOO_RAM_AW = $clog2(7+1);
wire [(FOO_COPIES*8)-1:0] foo_generator_foo_ram_r;

always @(posedge gb_clk) begin
  // local writes
  if (en_local & gb_wen) begin
    // No rams
    // CSR writes
    casez (gb_addr[5:0])
      6'h00: top_reg <= gb_wdata[7:0];
      6'h01: baz_generator_top_baz_w <= gb_wdata[3:0];
      6'h04: foo_generator_top_foo_n_w[0] <= gb_wdata[3:0];
      6'h05: foo_generator_top_foo_n_w[1] <= gb_wdata[3:0];
      6'h06: foo_generator_top_foo_n_w[2] <= gb_wdata[3:0];
      6'h07: foo_generator_top_foo_n_w[3] <= gb_wdata[3:0];
    endcase
  end // if (en_local & gb_wen)
  // local reads
  if (en_local & ~gb_wen) begin
    // No rams
    // CSR reads
    casez (gb_addr[5:0])
      6'h00: local_din <= {{32-(7+1){1'b0}}, top_reg};
      6'h01: local_din <= {{32-(3+1){1'b0}}, baz_generator_top_baz_r};
      6'h04: local_din <= {{32-(3+1){1'b0}}, foo_generator_top_foo_n_r[0]};
      6'h05: local_din <= {{32-(3+1){1'b0}}, foo_generator_top_foo_n_r[1]};
      6'h06: local_din <= {{32-(3+1){1'b0}}, foo_generator_top_foo_n_r[2]};
      6'h07: local_din <= {{32-(3+1){1'b0}}, foo_generator_top_foo_n_r[3]};
      default: local_din <= 32'h00000000;
    endcase
  end // if (en_local & ~gb_wen)
end
wire GBPORT_clk_foo = gb_clk;
wire [23:0] GBPORT_addr_foo = {{24-8{1'b0}}, gb_addr[7:0]};
wire [31:0] GBPORT_dout_foo = gb_wdata;
wire [(FOO_COPIES*32)-1:0] GBPORT_din_foo;
wire [FOO_COPIES-1:0] GBPORT_we_foo;
wire [FOO_COPIES-1:0] GBPORT_wstb_foo;
wire [FOO_COPIES-1:0] GBPORT_rstb_foo;
wire [FOO_COPIES-1:0] addrhit_foo;
`else
`GHOSTBUS_top
`endif
// ===========================================================================

genvar N;
generate
  for (N=0; N<FOO_COPIES; N=N+1) begin: foo_generator
    (* ghostbus *) reg [3:0] top_foo_n = N[3:0];
    (* ghostbus *) reg [7:0] foo_ram [0:7];
`ifdef HAND_ROLLED
    // Submodule foo
    assign addrhit_foo[N] = gb_addr[23:8] = 16'h00001 + N[15:0];
    assign GBPORT_we_foo[N] = gb_wen & addrhit_foo[N];
    assign GBPORT_wstb_foo[N] = gb_wen & addrhit_foo[N];
    assign GBPORT_rstb_foo[N] = gb_rstb & addrhit_foo[N];

    // RAM foo_ram
    assign addrhit_foo_ram[N] = gb_addr[23:3] = 21'h000004 + N[20:0];
    assign foo_generator_foo_ram_r[(N*8)-1-:8] = foo_ram[gb_addr[FOO_RAM_AW-1:0]];
    always @(gb_clk) begin
      if (addrhit_foo_ram[N]) begin
        foo_ram[gb_addr[FOO_RAM_AW-1:0]] <= gb_wdata[7:0];
      end
    end

    // CSR top_foo_n
    always @(*) begin
      foo_generator_top_foo_n_r[N] <= top_foo_n;
      top_foo_n <= foo_generator_top_foo_n_w[N];
    end
`else
    `GHOSTBUS_foo_generator
`endif
    submod_foo #(
      .AW(FOO_AW),
      .DW(FOO_DW),
      .GW(FOO_GW),
      .RD(FOO_RD)
    ) foo (
      .clk(gb_clk)
`ifdef HAND_ROLLED
      ,.GBPORT_clk(GBPORT_clk_foo) // input
      ,.GBPORT_addr(GBPORT_addr_foo) // input [23:0]
      ,.GBPORT_dout(GBPORT_dout_foo) // input [31:0]
      ,.GBPORT_din(GBPORT_din_foo[(N*32)-1-:32]) // output [31:0]
      ,.GBPORT_we(GBPORT_we_foo[N]) // input
      ,.GBPORT_wstb(GBPORT_wstb_foo[N]) // input
      ,.GBPORT_rstb(GBPORT_rstb_foo[N]) // input
`else
      `GHOSTBUS_top_foo
`endif
    );
  end
endgenerate

generate
  if (TOP_BAZ==1) begin: baz_generator
    submod_baz #(
      .AW(12),
      .DW(8)
    ) baz (
      .clk(gb_clk),
      .demo_sig(top_reg[0])
`ifdef HAND_ROLLED
      // TODO
`else
      `GHOSTBUS_top_baz
`endif
    );
    (* ghostbus *) reg [3:0] top_baz = 4'hc;
    (* ghostbus *) reg [7:0] baz_ram [0:7];
`ifdef HAND_ROLLED
    always @(*) begin
      top_baz <= baz_generator_top_baz_w;
      baz_generator_top_baz_r <= top_baz;
    end
`else
    `GHOSTBUS_baz_generator
`endif
  end
endgenerate


endmodule
