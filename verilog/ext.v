// An 'external' (non-ghostbus) module with manual decoding

module ext #(
   parameter aw = 2
  ,parameter dw = 8
) (
   input  clk
  ,input  [aw-1:0] addr
  ,input  [dw-1:0] din
  ,output [dw-1:0] dout
  ,input  we
);

localparam [dw-1:0] read_only_0 = 'haf;
reg [dw-1:0] rw_ext='h40;

reg [dw-1:0] dout_r=0;

always @(posedge clk) begin
  if (we) begin
    case (addr[1:0])
      2'h1: rw_ext <= din;
      default: rw_ext <= rw_ext;
    endcase
  end
  case (addr[1:0])
    2'h0: dout_r <= read_only_0;
    2'h1: dout_r <= rw_ext;
    default: dout_r <= {dw{1'b0}};
  endcase
end

endmodule
