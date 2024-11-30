// A pointless loopback for testing a particular ghostbus feature

module bus_glue #(
  parameter AW=24,
  parameter DW=32
) (
  // in bus (from host)
  input  i_clk,
  input  [AW-1:0] i_addr,
  input  [DW-1:0] i_wdata,
  output [DW-1:0] i_rdata,
  input  i_wstb,
  // out bus (to periph)
  output  o_clk,
  output [AW-1:0] o_addr,
  output [DW-1:0] o_wdata,
  input  [DW-1:0] o_rdata,
  output o_wstb
);

assign o_clk = i_clk;
assign o_addr = i_addr;
assign o_wdata = i_wdata;
assign i_rdata = o_rdata;
assign o_wstb = i_wstb;

endmodule
