![ghostbus chibi](doc/gb_icon_transparent.png)

# GhostBus Auto-Bus Decoder
An RDL-free automatic memory map handler and bus router.

_Imagine..._ When you're designing a codebase, you could create a `reg`, `wire`, etc
right where it's used and just point to it and say, _"I declare this to be a CSR!"_ and
you're done. __Ghostbus__ gets you as close to that magic reality as possible within the
constructs of the (System)Verilog language.

| Traditional Methods (RDLs)           | Ghostbus                             |
|--------------------------------------|--------------------------------------|
|* Define CSRs in a separate language (an RDL) | * Define CSRs in Verilog, right where they are used |
|* Address decoding logic at top level with CSRs routed as ports from top to destination | * Distributed address decoding. "Invisible" (ghost) bus automatically routed where it needs to go and CSR addresses decoded in local scope |
|* Memory map is top-level source code | * Memory map is a generated artifact |

I assert that Verilog (and to a much greater extent, SystemVerilog) is a sufficiently
expressive language to capture the entirety of your design intent in one place.

__The name__: the decoding happens via a bus that's instantiated but not routed
("invisible") until after preprocessing.

## Core Features
0. Define your memory map in your Verilog codebase using standard Verilog attributes.
1. Automatically manage address assignment, allowing easy, maintainable scaling of codebase.
2. Automatically decode bus transactions for register/memory reads/writes
3. Reduce boilerplate code, improving readability/maintainability.

## Design Philosophy
0. The Verilog code is the ONLY source (no information stored "elsewhere").
1. Stay in our lane. Ghostbus will only ever be about memory maps and bus routing. Nothing else.
2. Don't break code. Unprocessed Verilog is still valid/functional.
3. Be explicit; avoid heuristics. No guessing at functionality based on e.g. net names.
4. Use existing Verilog parser(s). Avoid hand-rolled parser/scanner.
5. Be obvious; attribute names all start with `ghostbus_` so that a reader immediately
   knows what tool the attribute targets. A few extra characters avoids a lot of confusion.

## Usage
See the [API documentation]("API.md") for usage.

## Design considerations

### Multiple Ghostbusses
#### Domain Rules
1. The domain 'None' refers to that of the implied bus that magically comes in via `` `GHOSTBUSPORTS``. All other domains are named.
   Note that this is instance-relative (i.e. your implied bus may be different from mine, but we still call ours both 'None').

2. If a module is 'top' (i.e. is marked as top from `ghostbusser.py --top` CLI arg, or using `(* ghostbus_top *)` attribute),
   there is no implied bus.  If no bus is declared in the module, no local resources can be routed.
   If one bus is declared in the module, it is the default bus (thus no `(* ghostbus_domain="foo" *)` attributes required).
   If more than one bus is declared in the module, EVERY CSR/RAM/extmod/submod needs to be disambiguated
   via the `(* ghostbus_domain="foo" *)` attribute (anything missing this should generate an error).

3. If a module is not 'top', the default domain is the implied bus.  If any additional busses are declared in this module,
   each needs to be assigned a distinct explicit domain via the `(* ghostbus_domain="foo" *)` attribute.

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

# About
*** Copyright Notice ***

ghostbus Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.

If you have questions about your rights to use or distribute this software,
please contact Berkeley Lab's Intellectual Property Office at
IPO@lbl.gov.

NOTICE.  This Software was developed under funding from the U.S. Department
of Energy and the U.S. Government consequently retains certain rights.  As
such, the U.S. Government has been granted for itself and others acting on
its behalf a paid-up, nonexclusive, irrevocable, worldwide license in the
Software to reproduce, distribute copies to the public, prepare derivative 
works, and perform publicly and display publicly, and to permit others to do so.
