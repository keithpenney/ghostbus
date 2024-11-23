// Top module for the 'generate' codebase

`ifndef GHOSTBUS_LIVE
  `define GHOSTBUS_top
  `define GHOSTBUS_top_baz
  `define GHOSTBUS_top_foo
  `define GHOSTBUS_top_foo_generator
  `define GHOSTBUS_top_baz_generator
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

reg [3:0] baz_generator_top_baz_w;
reg [3:0] baz_generator_top_baz_r;

wire [FOO_COPIES-1:0] addrhit_foo_ram;
localparam FOO_RAM_AW = $clog2(7+1);
wire [(FOO_COPIES*8)-1:0] foo_generator_foo_ram_r;

wire [7:0] baz_generator_baz_ram_r;
localparam BAZ_RAM_AW = $clog2(7+1);
wire addrhit_baz_ram = gb_addr[23:3] == 21'h000001; // 0x8-0xf

// din routing
assign gb_rdata = en_local ? local_din :
                32'h00000000;

localparam FOO_GENERATOR_TOP_FOO_N_BASE = 'h04;

integer AUTOGEN_INDEX=0;
always @(posedge gb_clk) begin
  // local writes
  if (en_local & gb_wen) begin
    // RAM writes
    // Generate-For RAM writes are handled within their generate block
    // CSR writes
    casez (gb_addr[5:0])
      6'h00: top_reg <= gb_wdata[7:0];
      6'h01: baz_generator_top_baz_w <= gb_wdata[3:0];
    endcase
    // Generate-For CSRs
    // foo_generator.top_foo_n
    for (AUTOGEN_INDEX=0; AUTOGEN_INDEX<FOO_COPIES; AUTOGEN_INDEX=AUTOGEN_INDEX+1) begin
      if (gb_addr[5:0] == (FOO_GENERATOR_TOP_FOO_N_BASE[5:0] | AUTOGEN_INDEX[5:0])) begin
        foo_generator_top_foo_n_w[AUTOGEN_INDEX] <= gb_wdata[3:0];
      end
    end
  end // if (en_local & gb_wen)
  // local reads
  if (en_local & ~gb_wen) begin
    local_din <= 0;
    // RAM reads
    // Generate RAMs
    // foo_generator.foo_ram
    for (AUTOGEN_INDEX=0; AUTOGEN_INDEX<FOO_COPIES; AUTOGEN_INDEX=AUTOGEN_INDEX+1) begin
      if (addrhit_foo_ram[AUTOGEN_INDEX]) begin
        local_din <= {{32-(3+1){1'b0}}, foo_generator_foo_ram_r[((AUTOGEN_INDEX+1)*8)-1-:8]};
      end
    end

    // baz_generator.baz_ram
    // (same as non-generate RAM, except with baz_generator_baz_ram_r)
    if (addrhit_baz_ram) begin
      local_din <= {{32-(7+1){1'b0}}, baz_generator_baz_ram_r};
    end

    // CSR reads
    casez (gb_addr[5:0])
      6'h00: local_din <= {{32-(7+1){1'b0}}, top_reg};
      6'h01: local_din <= {{32-(3+1){1'b0}}, baz_generator_top_baz_r};
      //default: local_din <= 32'h00000000;
    endcase
    // Generate-For CSRs
    // foo_generator.top_foo_n
    for (AUTOGEN_INDEX=0; AUTOGEN_INDEX<FOO_COPIES; AUTOGEN_INDEX=AUTOGEN_INDEX+1) begin
      if (gb_addr[5:0] == (FOO_GENERATOR_TOP_FOO_N_BASE[5:0] | AUTOGEN_INDEX[5:0])) begin
        local_din <= {{32-(3+1){1'b0}}, foo_generator_top_foo_n_r[AUTOGEN_INDEX]};
      end
    end

  end // if (en_local & ~gb_wen)
end

// Submodule foo
wire [FOO_COPIES-1:0] addrhit_foo;
wire GBPORT_clk_foo = gb_clk;
wire [23:0] GBPORT_addr_foo = {{24-8{1'b0}}, gb_addr[7:0]};
wire [31:0] GBPORT_dout_foo = gb_wdata;
wire [(FOO_COPIES*32)-1:0] GBPORT_din_foo;
wire [FOO_COPIES-1:0] GBPORT_we_foo = {FOO_COPIES{gb_wen}} & addrhit_foo;
wire [FOO_COPIES-1:0] GBPORT_wstb_foo = {FOO_COPIES{gb_wen}} & addrhit_foo;
wire [FOO_COPIES-1:0] GBPORT_rstb_foo = {FOO_COPIES{gb_rstb}} & addrhit_foo;

// Submodule baz (0x0080 <-> 0x00ff baz)
// (same as non-generate submodule)
wire addrhit_baz = gb_addr[23:7] == 17'h0001;
wire GBPORT_clk_baz = gb_clk;
wire [23:0] GBPORT_addr_baz = {{24-7{1'b0}}, gb_addr[6:0]}; // address relative to own base (0x0)
wire [31:0] GBPORT_dout_baz = gb_wdata;
wire [31:0] GBPORT_din_baz;
wire GBPORT_we_baz = gb_wen & addrhit_baz;
wire GBPORT_wstb_baz = gb_wen & addrhit_baz;
wire GBPORT_rstb_baz = gb_rstb & addrhit_baz;

`else
`GHOSTBUS_top
`endif
// ===========================================================================

integer RAM_N=0;
genvar N;
generate
  for (N=0; N<FOO_COPIES; N=N+1) begin: foo_generator
    (* ghostbus *) reg [3:0] top_foo_n = 4'hc;// N[3:0];
    (* ghostbus *) reg [7:0] foo_ram [0:7];
    // Preload some content in foo_ram so we know if we're reading it
    initial begin
      for (RAM_N=0; RAM_N<8; RAM_N=RAM_N+1) begin
        foo_ram[RAM_N] = (N[3:0]<<4) | RAM_N[3:0];
      end
    end
`ifdef HAND_ROLLED
    // Submodule foo
    assign addrhit_foo[N] = gb_addr[23:8] == 16'h0001 + N[15:0];
    /*
    assign GBPORT_we_foo[N] = gb_wen & addrhit_foo[N];
    assign GBPORT_wstb_foo[N] = gb_wen & addrhit_foo[N];
    assign GBPORT_rstb_foo[N] = gb_rstb & addrhit_foo[N];
    */

    // RAM foo_ram
    assign addrhit_foo_ram[N] = gb_addr[23:3] == 21'h0004 + N[20:0];
    assign foo_generator_foo_ram_r[((N+1)*8)-1-:8] = foo_ram[gb_addr[FOO_RAM_AW-1:0]];
    always @(posedge gb_clk) begin
      if (addrhit_foo_ram[N] & gb_wen) begin
        foo_ram[gb_addr[FOO_RAM_AW-1:0]] <= gb_wdata[7:0];
      end
    end

    // CSR top_foo_n
    initial begin
      foo_generator_top_foo_n_w[N] = top_foo_n;
    end
    always @(top_foo_n or foo_generator_top_foo_n_w[N]) begin
      foo_generator_top_foo_n_r[N] <= top_foo_n;
      top_foo_n <= foo_generator_top_foo_n_w[N];
    end
`else
    `GHOSTBUS_top_foo_generator
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
      ,.GBPORT_din(GBPORT_din_foo[((N+1)*32)-1-:32]) // output [31:0]
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
      ,.GBPORT_clk(GBPORT_clk_baz) // input
      ,.GBPORT_addr(GBPORT_addr_baz) // input [23:0]
      ,.GBPORT_dout(GBPORT_dout_baz) // input [31:0]
      ,.GBPORT_din(GBPORT_din_baz) // output [31:0]
      ,.GBPORT_we(GBPORT_we_baz) // input
      ,.GBPORT_wstb(GBPORT_wstb_baz) // input
      ,.GBPORT_rstb(GBPORT_rstb_baz) // input
`else
      `GHOSTBUS_top_baz
`endif
    );
    (* ghostbus *) reg [3:0] top_baz = 4'he;
    (* ghostbus *) reg [7:0] baz_ram [0:7];
    // Preload some content in foo_ram so we know if we're reading it
    initial begin
      for (RAM_N=0; RAM_N<8; RAM_N=RAM_N+1) begin
        baz_ram[RAM_N] = (RAM_N[3:0] << 4) | 4'hb;
      end
    end
`ifdef HAND_ROLLED
    // CSR top_baz
    initial begin
      baz_generator_top_baz_w = top_baz;
    end
    always @(top_baz or baz_generator_top_baz_w) begin
      top_baz <= baz_generator_top_baz_w;
      baz_generator_top_baz_r <= top_baz;
    end

    // RAM baz_ram
    assign baz_generator_baz_ram_r = baz_ram[gb_addr[BAZ_RAM_AW-1:0]];
    always @(posedge gb_clk) begin
      if (addrhit_baz_ram & gb_wen) begin
        baz_ram[gb_addr[BAZ_RAM_AW-1:0]] <= gb_wdata[7:0];
      end
    end
`else
    `GHOSTBUS_top_baz_generator
`endif
  end
endgenerate


endmodule
