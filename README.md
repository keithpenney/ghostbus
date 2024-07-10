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
4. (TODO) Write out a complete memory map in a hierarchical JSON.
5. Generate a `.vh` file for every module which contains the bus decoding with the
   local addresses computed in step 3.
6. (TODO) Also generate a top-level "mirror memory" decoder for readback of R/W (memory-like)
   registers.

## Comparison with Newad

|__GhostBus__                        |__Newad__                               |
|------------------------------------|----------------------------------------|
|Decoding at top level               |Distributed decoder (in each module)    |
|"Magic" (auto-generated) ports      |...sadly, magic ports for the bus       |
|Flat memory map; all registers in the same scope; name mangling|Hierarchical memory map; name mangling if needed for EPICS|
|Preprocessing required              |Valid Verilog without preprocessing; host-accessible registers retain initial values|
|Manual (global) address via static JSON |Manual (module-relative) address via Verilog attribute|

## Usage Example

```verilog
// TODO
```

## Status
__TODO__:
  1. Work out how to manually hook up to the ghostbus

__240709__: Knocked some stuff off the TODO list
  DONE: Develop a testbench that will automatically check the memory map (i.e. write and readback)
  DONE: Handle strobes
  DONE: Handle associated (write) strobes
  DONE: Handle read-only registers
  DONE: Support associated _read_ strobes (pulse high on read of a register)

__240705__: Eliminated some hard-coding in the working demo.
  * Parsing of `(* ghostbus_port=... *)` attributes implemented (not mandated until `getBusDict()`)

__240702__: I have a working demo which still uses some hard-coded values.  I still need the following:
  1. Parse the testbench to grab the `(* ghostbus_port=... *)` attributes so we can auto-infer those port
     names and widths.
  2. Should the testbench be part of the memory map?  Or is that scanned separately?
  3. Find a better way to populate the preprocessor definitions instead of mandating an `include "defs.vh"` line
     The only alternative I can think of is to pass them directly to the tool.  Can I just make the tool process the
     file as if it's source?  Verilog preprocessor macros are (for better or worse) global afterall.

## Design considerations

### Decoding

I'd like the decoding rules to be parameterized in the future.  For now, they're fixed.  These are the
current decoding rules:
1. Each module only sees its own address space on the bus.  Addresses passed to submodules always mask out the upper bits
   to ensure this remains true.  This is the only portable solution (i.e. two instances at different parts of the memory
   map must have the same decoding logic, so they must not be aware of the memory map beyond their own range).
   The alignment of the memory map makes this trivial and resource-efficient.

2. Local registers (CSRs and RAMs instantiated directly in a given module) are decoded with sequential (clocked) logic.
   Bus decoding to submodules passes through with combinational logic (so that the transaction delay does not depend on
   the hierarchy).

3. Local registers should be packed as tightly as possible (i.e. try to avoid setting explicit addresses) to reduce the
   LUT usage for address decoding.

### Limitations of the Verilog Preprocessor
Mayday. The verilog preprocessor is trying to sink this concept.  The notion that all macros are global in
scope is one of the core issues.  I think I have a workaround, but it will require careful code generation
and unfortunately a bit of an implementation gotcha.

__hand-written__
```verilog
module foo #(
  parameter AW
) (
  input d
);

`ifdef GHOSTBUS_LIVE
`GHOSTBUS_foo
// Could also just use `include "_ghostbus_foo.vh" instead
`endif

endmodule
```

__auto-generated__
```verilog
/* file "_gb_auto.vh" */
`define GHOSTBUS_foo `include "_ghostbus_foo.vh"
```

```verilog
/* file "_ghostbus_foo.vh" */
// bus decoding logic implemented here
```

The other major issue is that the module-local memory map can be parameterized (i.e. depend on the value
of parameters) and thus the decoding for each instance could differ.  Thus, if we had only one `_ghostbus_foo.vh`
file and two different instances off `module foo` with different parameters, the bus decoding could be wrong
in one or both instances.  So instead of resolving the parameter to a constant, we'll need to preseve parameter
names in the decoding (much trickier, especially since the Yosys abstract model resolves parameters already).

### Magic ports
I can't figure out a way to avoid magic ports in Verilog.  That was a big goal here, but I can't figure out
a way to generically wire up a bus without pre-defining the memory map within the constraints of the language
(and without abusing the preprocessor to the point of complete obfuscation).

So I sadly yield to the concept of magic ports, but ONLY for the bus itself (hence the "ghost").  But this
brings up several important issues to resolve:

* How do the magic ports appear?

Do we mandate preprocessor macros galore (ugh), or do we invoke a custom preprocessor (yikes)?  The latter
would probably just be a custom Python script; developing the script is not the hard part - it's integrating
it with an existing build system that's a pain.  So I think the macro method is still somehow favorable.

* How do we allow a user to manually hook up to the ghost bus?

This use case would appear pretty quickly, i.e. putting a dual-port RAM on the bus.  Remember, the raison
d'etre of this whole thing is to allow the source to be valid Verilog outside of the ghostbus toolchain
(making code more obvious/self-documenting, and simplifying testbench coverage).  So the only halfway decent
solution that comes to mind is declaring nets and labeling them as part of the ghost bus with attributes.

```Verilog
// Example of manually hooking up to the ghost bus

(* ghostbus_port=clk *)  wire gb_clk;
(* ghostbus_port=addr *) wire [DW-1:0] gb_addr;
(* ghostbus_port=din *)  wire [DW-1:0] gb_din;
(* ghostbus_port=dout *) wire [DW-1:0] gb_dout;
(* ghostbus_port=wen *)  wire gb_we;

// Optionally drive with actual signals in a non-ghostbus context
`ifndef GHOSTBUS_LIVE
assign gb_clk  = clk;
assign gb_addr = test_addr;
assign gb_din  = test_din;
assign gb_dout = test_dout;
assign gb_we   = test_we;
`endif

// And here we manually wire up the dpram. Note that we'll need to communicate its
// size (address width 'AW') to the ghostbus memory map
(* ghostbus_aw=AW *) dpram #(.AW(AW)) dpram_i (
  .clk_a(clk_a), .addr_a(addr_a), .din_a(din_a), .dout_a(dout_a), .wen_a(wen_a),
  .clk_b(gb_clk), .addr_b(gb_addr), .din_b(gb_din), .dout_b(gb_dout), .wen_b(gb_we)
);
```

### Pipeline and fanout
(slightly out-dated by the __Decoding__ section above, but still contains important consideration)

The behavior of the decoder should be parameterized.  In the simplest case, we can route the whole bus with
combinational logic (pipeline depth of 0).  This should be sufficient for small designs, but will create
high fanout and resource usage as the project grows.

As the HDL design itself is structured hierarchically and the whole _ghostbus_ memory management concept is
similarly structured, it would make sense to use module boundaries as natural pipeline delimiters (i.e. the
bus decoding in a child module will be one cycle delayed from the decoding in the parent).  Blindly applying
this rule would create unnatural and buggy dependence of the bus timing on the hierarchy.  Instead, I propose
a configurable parameter for pipeline length.

Consider an example design as a tree of modules with the longest branch being 5 modules deep.  If we choose
a decoder pipeline length of 2 for this design, the longest branch would behave like this:
  cycle num     branch level
  --------------------------
  0             0           // The top level is not delayed wrt the bus controller
  1             1           // The first level down is one cycle delayed
  2             2, 3, 4     // The remainder of the branch is two cycles delayed

If it is determined to be important, extra logic could be added to ensure the delay between the bus controller
asserting a write strobe and module receiving it is consistent across the entire design, regardless of hierarchy.

### Read cycles

The above consideration has implications for read cycle delays as well.  For a read operation, the bus controller
would need to wait at least twice the pipeline depth for the result to be valid (assuming both the `din` and `dout`
paths are pipelined in the same way).  Additional logic should be spent to ensure that the local read cycle delay
is consistent across the entire design.  That is to say, every module should see the same number of cycles between
the time a read is asserted and when the value is latched by the read pipeline.

### Hierarchy and Mirror Memory

The flat memory map (no hierarchy) of Newad-enabled projects makes the mirror memory concept easier.  With hierarchy,
it becomes necessary to alias addresses in the mirror memory region.  So for any host-accessible register placed in
the mirror memory address space, there would be two addresses associated with it: a write address and a read address.
The write address would be used for the write decoding and would propagate to the local decoding within its module.
The read address would be the arbitrarily-assigned index into the mirror memory which would be used for both writes
(need to store the data if you want to read it back) and reads.

Unless the system-wide memory map is very carefully constructed, the extra logic required for the memory aliasing
probably eliminates any savings that the mirror memory concept provides.  This is a tough nut to crack in a generic
way.  If CSR addresses are assigned automatically, they will be packed as densely as possible and the aliasing logic
could be simple bit-shifting.  But if manual address assignment is used, it could easily create a sparsely-packed
memory map which would require either an excessively large mirror RAM or expensive address offsetting.

The final question would be where the simple mirror memory RAM decoding logic goes. A natural place for this to live
is either at the top level or at the same level as the bus controller since it functions purely as RAM attached to
the bus.  As of writing, these two are sort of required to be the same place (there's currently no provision for
auto-routing the bus "upwards" from a submodule bus controller to the top-level.

### Passthrough modules

A conceivable hierarchy could be the following:

```
| bus controller |
        \
         | module A |
              \
               | module B |
                    \
                     | module C (HA regs) |
```

In this example, there are no host-accessible registers ("HA regs") in modules `A` or `B` but the auto-generated bus
needs to route through these two modules to reach the HA regs in module `C`.

To solve this problem, two options come to mind:

1. Only require routing the bus ports inside module A and module B, as in:
```verilog
module mod_a (
  input bus_clk,
  input [AW-1:0] bus_addr,
  input [DW-1:0] bus_din,
  output [DW-1:0] bus_dout,
  input bus_we
);

mod_b mod_b_i (
  .bus_clk(bus_clk),
  .bus_addr(bus_addr),
  .bus_din(bus_din),
  .bus_dout(bus_dout)
);
endmodule
```
And similarly for `mod_c` within `mod_b`.

2. Insert auto-generated decoding even though there are no HA regs in this module, as in:
```verilog
module mod_a (
  input bus_clk,
  input [AW-1:0] bus_addr,
  input [DW-1:0] bus_din,
  output [DW-1:0] bus_dout,
  input bus_we
);

mod_b mod_b_i (
  .bus_clk(bus_clk),
  .bus_addr(bus_addr),
  .bus_din(bus_din),
  .bus_dout(bus_dout)
);

`ifdef GHOSTBUS_LIVE
`include "gb_mod_a.vh"
`endif

endmodule
```

In case __1__ above, module `A` and `B` function as transparent passthrough and do not count as pipeline boundaries
(because decoding logic is not included).  In the second option, if the pipeline depth is >1, module `A` will include
decoding pipeline logic (i.e. `gb_mod_a.vh` will be non-empty).  Similarly, if pipeline depth is >2, module `B` will
include such logic as well.

