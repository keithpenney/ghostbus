// Wrap i2c_chunk.v as a ghostbus module
// as a usage demonstration

// This step can be eliminated if we define all the macros in "defs.vh" at
// synthesis-time via tcl
`ifdef GHOSTBUS_LIVE
  `include "defs.vh"
`endif

module i2c_chunk_gb #(
	parameter initial_file = "",
	parameter tick_scale = 6,
	// transparently passed to i2c_prog
	parameter q1 = 2,  // o_p1 ticks are 2^(q1+1) * bit_adv
	parameter q2 = 7   // o_p2 ticks are 2^(q2+1) * bit_adv
) (
	// Single clock domain, slave to the local bus
	// hard-coded read/write 4K address space,
	// subdivided into quarters as shown below
	input clk,  // Rising edge clock input; all logic is synchronous in this domain
	output [3:0] hw_config,  // Can be used to select between I2C busses
	// Hardware pins: TWI (almost I2C) bus
	output scl,  // Direct drive of SCL pin
	output sda_drive,  // Low value should operate pull-down of SDA pin
	input  sda_sense,  // SDA pin
	input  scl_sense,  // SCL pin
	input  rst,  // not yet used
	input  intp  // not yet used
`ifdef GHOSTBUS_LIVE
`GHOSTBUS_ports
`endif
);

// ============= Host-Accessible Registers ==============
// Module is controlled via two registers (with names selected
// to be compatible with "projects/test_marble_family")
(* ghostbus *)      reg  [3:0] ctl=0;
(* ghostbus="ro" *) wire [4:0] status;

// ====== Hang an explicit bus on the ghostbus here ======
//(* ghostbus_ext="i2c, clk"  *)  wire lb_clk; // optional
(* ghostbus_ext="i2c, addr"  *) wire [11:0] lb_addr;
(* ghostbus_ext="i2c, wdata" *) wire [7:0] lb_din;
(* ghostbus_ext="i2c, wen"   *) wire lb_write; // TODO wstb?
(* ghostbus_ext="i2c, rdata" *) wire [7:0] lb_dout;

// Bit assignments compatible with "projects/test_marble_family"
wire freeze = ctl[0];
wire run_cmd = ctl[1];
wire trig_mode = ctl[2];
wire trace_cmd = ctl[3];
wire run_stat;  // Reports if sequencer is running
wire analyze_armed;
wire analyze_run;  // reports if logic analyzer is tracing
wire updated;   // New data is available in wire buffer
wire err_flag;  // Error condition detected

assign status = {analyze_run, analyze_armed, run_stat, err_flag, updated};

// The auto-generated bus decoding logic
`ifdef GHOSTBUS_LIVE
`GHOSTBUS_i2c_chunk_gb
`endif

// Instantiate and hookup the standard i2c_chunk.v
i2c_chunk #(
  .initial_file(initial_file),
  .q1(q1),
  .q2(q2),
  .tick_scale(tick_scale)
) i2c_chunk_i (
  .clk(clk), // input
  .lb_addr(lb_addr), // input [11:0]
  .lb_din(lb_din), // input [7:0]
  .lb_write(lb_write), // input
  .lb_dout(lb_dout), // output [7:0]
  .run_cmd(run_cmd), // input
  .trace_cmd(trace_cmd), // input
  .freeze(freeze), // input
  .run_stat(run_stat), // output
  .analyze_armed(analyze_armed), // output
  .analyze_run(analyze_run), // output
  .updated(updated), // output
  .err_flag(err_flag), // output
  .hw_config(hw_config), // output [3:0]
  .scl(scl), // output
  .sda_drive(sda_drive), // output
  .sda_sense(sda_sense), // input
  .scl_sense(scl_sense), // input
  .trig_mode(trig_mode), // input
  .rst(rst), // input
  .intp(intp) // input
);

endmodule
