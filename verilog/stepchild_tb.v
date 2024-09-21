// A scratch pad to ponder this stepchild feature

module stepchild_tb;

localparam AW = 24;
localparam DW = 32;

/* TODO:
    1. parent_bus needs to be conjured (to explicitly hang a module on the ghostbus)
    2. child_bus needs to be used to determine the size of parent_bus
    3. parent_bus should only have the lowest N bits of addr driven
*/

(* ghostbus_port="clk" *)   reg gb_clk=1'b1;
(* ghostbus_port="addr" *)  wire [AW-1:0] gb_addr;
(* ghostbus_port="wdata" *) wire [DW-1:0] gb_wdata;
(* ghostbus_port="rdata" *) wire [DW-1:0] gb_rdata;
(* ghostbus_port="wen" *)   wire gb_wstb;

always #5 gb_clk <= ~gb_clk;

// See actual usage in: uspas_llrf/llrf_dsp/llrf_shell.v

// Conjured bus (but special...). It needs to officially be "MAGIC_AW" in width according to the memory map
// But that "MAGIC_AW" value is magically divined by Ghostbus, not known to the author
// TODO - How to I tell it that this ext mod is to be trimmed?
`ifdef LETS_EXT
(* ghostbus_ext="parent" *) wire parent_clk;
(* ghostbus_ext="parent" *) wire [AW-1:0] parent_addr;
(* ghostbus_ext="parent" *) wire [DW-1:0] parent_wdata;
(* ghostbus_ext="parent" *) wire [DW-1:0] parent_rdata;
(* ghostbus_ext="parent" *) wire parent_wstb;
`else
wire parent_clk;
wire [AW-1:0] parent_addr;
wire [DW-1:0] parent_wdata;
wire [DW-1:0] parent_rdata;
wire parent_wstb;
`endif


// Ghostbus
// HACK ALERT! Testing a new API 'ghostbus_sub'! I'd love to avoid this.
//   Syntax: ghostbus_sub="bus_name" (where "bus_name" can be omitted if there's only one other ghostbus)
//           Indicates that this bus is a sub-bus of the named (or implied) parent bus
(* ghostbus_port="clk",       ghostbus_name="child", ghostbus_alias="parent" *) wire child_clk;
(* ghostbus_port="addr",      ghostbus_name="child", ghostbus_alias="parent" *) wire [AW-1:0] child_addr;
(* ghostbus_port="wdata",     ghostbus_name="child", ghostbus_alias="parent" *) wire [DW-1:0] child_wdata;
(* ghostbus_port="rdata",     ghostbus_name="child", ghostbus_alias="parent" *) wire [DW-1:0] child_rdata;
(* ghostbus_port="wstb, wen", ghostbus_name="child", ghostbus_alias="parent" *) wire child_wstb;

/*
// Transfer p_bus to c_clk domain
data_xdomain #(
  .size(AW+DW)
) lb_to_1x (
  .clk_in(parent_clk),
  .gate_in(parent_wstb),
  .data_in({parent_addr,parent_wdata}),
  .clk_out(child_clk),
  .gate_out(child_wstb),
  .data_out({child_addr,child_wdata})
);
*/

// I need to somehow communicate that child_bus is part of parent_bus's tree
// even though they're AFAIK completely unrelated nets.  How do I communicate
// this relationship to the tool?
bus_glue #(
  .AW(AW),
  .DW(DW)
) bus_glue_i (
  .i_clk(parent_clk), // input
  .i_addr(parent_addr), // input [AW-1:0]
  .i_wdata(parent_wdata), // input [DW-1:0]
  .i_rdata(parent_rdata), // output [DW-1:0]
  .i_wstb(parent_wstb), // input
  .o_clk(child_clk), // input
  .o_addr(child_addr), // output [AW-1:0]
  .o_wdata(child_wdata), // output [DW-1:0]
  .o_rdata(child_rdata), // input [DW-1:0]
  .o_wstb(child_wstb) // output
);

// Populate the 'gb' memory map a bit
(* ghostbus *)     reg [7:0]  p_reg_0=0;
(* ghostbus="r" *) reg [31:0] p_reg_1=32'hfacef00d;
(* ghostbus *)     reg [15:0] p_ram_0 [0:7];

// Populate the 'child' memory map a bit
(* ghostbus,     ghostbus_name="child" *) reg [7:0]  c_reg_0=0;
(* ghostbus="r", ghostbus_name="child" *) reg [31:0] c_reg_1=32'hbeefca5e;
(* ghostbus,     ghostbus_name="child" *) reg [15:0] c_ram_0 [0:63];

`ifdef HAND_ROLLED_LOGIC
localparam MAGIC_AW = 8; // Magically derived from the tree of c_bus
wire en_parent = gb_addr[AW-1:MAGIC_AW] == {AW-MAGIC_AW{1'b0}}; // 0x000 to 0x0ff
assign parent_addr = {{AW-MAGIC_AW{1'b0}}, gb_addr[MAGIC_AW-1:0]};
assign parent_wdata = gb_wdata;
assign parent_wstb = gb_wstb & en_parent;

localparam C_RAM_0_AW = 6;
wire en_child_local = child_addr[AW-1:MAGIC_AW] == {AW-MAGIC_AW{1'b0}}; // 0x000 to 0x0ff
reg [DW-1:0] child_local_rdata=0;
assign child_rdata = en_child_local ? child_local_rdata : {DW{1'b0}};
always @(posedge child_clk) begin
  // local writes
  if (en_child_local & child_wstb) begin
    // c_ram_0 writes
    if (en_c_ram_0) begin
      c_ram_0[child_addr[C_RAM_0_AW-1:0]] <= child_wdata[3:0];
    end
    // CSR writes
    casez (child_addr[7:0])
      8'h0: c_reg_0 <= child_wdata[7:0];
      default: c_reg_0 <= c_reg_0;
    endcase
  end
  // local reads
  if (en_child_local & ~child_wstb) begin
    // c_ram_0 reads
    if (en_c_ram_0) begin
      child_local_rdata <= {{32-16{1'b0}}, c_ram_0[child_addr[C_RAM_0_AW-1:0]]};
    end else begin
      // CSR reads
      casez (child_addr[7:0])
        8'h0: child_local_rdata <= {{32-8{1'b0}}, c_reg_0};
        8'h1: child_local_rdata <= c_reg_1;
        default: child_local_rdata <= child_local_rdata;
      endcase
    end
  end
end

// It's like I need to think of "bus_glue_i" as a ghostmod and compute its size... though in this
// case its branch extends outside of itself, which violates the current hierarchical model (ghostbusses
// aren't allowed to route "up"

`else
  `ifdef GHOSTBUS_LIVE
    `GHOSTBUS_stepchild_tb
  `endif
`endif

`ifndef YOSYS
  initial begin
    $finish(0);
  end
`endif

endmodule
