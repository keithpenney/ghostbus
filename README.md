# GhostBus Auto-Bus Decoder
A new auto-bus-decoder based on the successes of Newad and Gang Huang's SystemVerilog decoder scheme.

__The name__: the decoding happens via a bus that's instantiated but not routed
("invisible") until after preprocessing.

## Core Features
1. Automatically decode bus transactions for register/memory reads/writes
2. Automatically manage the memory map, allowing easy, maintainable scaling of codebase.
3. Avoid errors associated with hand-written bus decoders.
4. Reduces boilerplate code, improving readability/maintainability.

## Design Philosophy
1. The Verilog code is the ONLY source (no information stored "elsewhere").
2. Don't break code. Unprocessed Verilog is still valid/functional.
3. Be explicit; avoid heuristics. No guessing at functionality based on e.g. net names.
4. Use existing Verilog parser(s). Avoid hand-rolled parser/scanner.
5. Be obvious; attribute names all start with `ghostbus_` so that a reader immediately
   knows what tool the attribute targets. A few extra characters avoids a lot of confusion.

## Comparison with Newad

|__Newad__                           |__Ghostbus__                            |
|------------------------------------|----------------------------------------|
|Decoding at top level               |Distributed decoder (in each module)    |
|"Magic" (auto-generated) ports      |...sadly, magic ports for the bus       |
|Flat memory map; all registers in the same scope; name mangling|Hierarchical memory map; flattening with name mangling if needed|
|Preprocessing required              |Valid Verilog without preprocessing; host-accessible registers retain initial values|
|Manual (global) address via static JSON |Manual (module-relative) address via Verilog attribute|

## Status
__TODO:__
  * Mangle ghostbus port names to reduce potential for port/net name collisions
  * Configurable pipelining
  * Auto-pipelining for module-specific read delays
  * Support for multiple ghostbuses
  * Alternate bus architectures (AXI4/AXI4LITE, wishbone, etc)

## Usage
See the [API documentation]("API.md") for usage.

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
