// I need deeper structure

module bof (
   input clk
  ,input [1:0] garbage
  ,output [1:0] trash
`ifdef GHOSTBUS_LIVE
`GHOSTBUSPORTS
`endif
);

`ifdef GHOSTBUS_LIVE
`GHOSTBUS_bof
`endif

(* ghostbus="ro" *) reg [1:0] garbage_ro=0;
(* ghostbus="wo" *) reg [1:0] trash_wo=0;
always @(posedge clk) begin
  garbage_ro <= garbage;
end
assign trash = trash_wo;

endmodule
