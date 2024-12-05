// A dummy external module

module extmod #(
  parameter aw = 4,
  parameter dw = 8
) (
  input  clk,
  input  [aw-1:0] addr,
  input  [dw-1:0] din,
  output reg [dw-1:0] dout,
  input  we
);

localparam RAM_SIZE=1<<aw;
reg [dw-1:0] ram [0:RAM_SIZE-1];

// Pre-load the RAM with some distinct values
integer N;
initial begin
  for (N=0; N<RAM_SIZE; N=N+1) begin
    ram[N] = 8'h80 | N[7:0];
  end
end

always @(posedge clk) begin
  dout <= ram[addr];
  if (we) begin
    ram[addr] <= din;
  end
end

endmodule
