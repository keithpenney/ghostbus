# GhostBus Auto-Bus Decoder

Ok, here's the concept for a new auto-bus-decoder based on the successes of
Newad and Gang Huang's SystemVerilog decoder scheme.

__The name__: the decoding happens via a bus that's routed but the decoding is "invisible"
until after preprocessing.  Also considering an option where the bus could be routed
automatically as well, though that competes with some of the goals below.

## Goals
### (Same as all the others)
1. Automatically decode bus transactions for register/memory reads/writes
2. Automatically manage the memory map, allowing easy, maintainable scaling of codebase.
3. Avoid errors associated with hand-written bus decoders.
4. Use existing Verilog parser(s). Avoid hand-rolled parser/scanner.

## Preprocessing steps
1. Scan each GhostBus-compliant module and compute its minimum size and access type.
2. Automatically generate each module's relative memory map.
3. Working from the lowest-level (leaf) modules upward to the top, automatically generate
   the module-level memory map.
4. Write out a complete memory map in a hierarchical JSON.
5. Generate a `.vh` file for every module which contains the bus decoding with the
   global addresses computed in step 3.
6. Also generate a top-level "mirror memory" decoder for readback of R/W (memory-like)
   registers.

## Comparison with Newad

|__GhostBus__                        |__Newad__                               |
|------------------------------------|----------------------------------------|
|Decoding at top level               |Distributed decoder (in each module)    |
|"Magic" (auto-generated) ports      |No magic ports                          |
|Flat memory map; all registers in the same scope; name mangling|Hierarchical memory map; name mangling if needed for EPICS|
|Preprocessing required              |Valid Verilog without preprocessing; host-accessible registers retain initial values|
|Manual (global) address via static JSON |Manual (module-relative) address via Verilog attribute|

## Usage Example

I'm just laying this out as a rough-sketch.

```verilog
module mod_foo #( 
  parameter AW = 24,
  parameter DW = 32
) (
  input clk,
  input [AW-1:0] addr,
  input [DW-1:0] din,
  output [DW-1:0] dout,
  input we
);

reg [3:0] foo=0;                            // Non-host-accessible register

(* ghostbus_ha *) reg [7:0] bar=8'h42;      // Host-accessible register (will be auto-decoded)

(* ghostbus_ha, ghostbus_addr='h100 *)
reg [7:0] baz [0:63];                       // Host-accessible RAM with pre-defined relative address (0x100)

endmodule
```
