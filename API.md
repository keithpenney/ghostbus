# Ghostbus API Documentation

## Attribute Reference (Alphabetized)
* [ghostbus](#csr)
* [ghostbus\_addr](#address)
* [ghostbus\_alias](#alias)
* [ghostbus\_branch](#ghostbus_branch)
* [ghostbus\_controller](#busdefine) (alias for _ghostbus\_driver_)
* [ghostbus\_csr](#csr) (alias for _ghostbus_)
* [ghostbus\_desc](#docstring) (alias for _ghostbus\_doc_)
* [ghostbus\_doc](#docstring)
* [ghostbus\_domain](#domains)
* [ghostbus\_driver](#busdefine)
* [ghostbus\_passenger](#busattach)
* [ghostbus\_peripheral](#busattach) (alias for _ghostbus\_passenger_)
* [ghostbus\_pub](#busdefine) (alias for _ghostbus\_driver_)
* [ghostbus\_ram](#csr) (alias for _ghostbus_)
* [ghostbus\_read\_strobe](#ascstrobe)
* [ghostbus\_rs](#ascstrobe) (alias for _ghostbus\_read\_strobe_)
* [ghostbus\_strobe](#simplestrobe)
* [ghostbus\_sub](#busattach) (alias for _ghostbus\_passenger_)
* [ghostbus\_write\_strobe](#ascstrobe)
* [ghostbus\_ws](#ascstrobe) (alias for _ghostbus\_write\_strobe_)
* [ghostbus\_top](#ghostbus_top)

## Table of Contents
[The API](#api)

[Metaphors](#metaphors)

[Attributes](#attributes)

* [Define a Ghostbus](#busdefine)

* [ghostbus\_csr: Define a CSR/RAM](#csr)

* [Place a CSR/RAM at an explicit address](#address)

* [ghostbus\_strobe: Add a simple strobe to the memory map](#simplestrobe)

* [Add a strobe vector to the memory map](#vectorstrobe)

* [Add an associated strobe to a particular CSR/RAM](#ascstrobe)

* [Attach an explicit external module to the Ghostbus](#busattach)

* [Assign a CSR/RAM a global alias for the exported memory map file](#alias)

* [Create multiple independent ghostbusses](#ghostbus_top)

[Routing Macros](#macros)

* [Adding the "magic" ports to your module declaration (i.e. "let the ghostbus in")](#ghost_in)

* [Adding the "magic" ports to a module instantiation (i.e. "propogate the ghostbus")](#ghost_out)

* [Including the auto-generated decoding logic into the codebase](#decoder)

* [Including the macro definitions](#defs)

# API <a name="api"></a>
All communication with the ghostbus Python tool is via Verilog attributes.
The attributes are documented below.  All attributes listed in the same code block are functional aliases
(no difference in functionality).  The different aliases are provided for personal choice or "grepability".

Recall that a major goal of the __ghostbus__ tool is that the Verilog remains valid as-is (before processing).
There are no "expanded" versions of the Verilog files, but instead we include auto-generated files inside
a conditional block ("guarded" includes) that ensures we only include them when they exist.

The auto-generated decoding and routing is placed into a series of files which are included by calling
specially-named macros.  While this is a bit painful, please blame the limitations of the Verilog language,
not the author of this tool.  Complexity has been minimized as much as possible.

## Metaphors <a name="metaphors"></a>

In naming any abstract concept, invoking an appropriate metaphor is often used as a powerful mental shortcut.
Designing a codebase with __ghostbus__ involves three types of object, each of which deserves its own name
which should hopefully immediately bring to mind its function and usage.

### A bus _driver_
A given bus has a single _driver_ which initiates transactions on the bus (drives the `address`, `write_data`,
and control nets, and takes input data on the `read_data` nets).
Even if multiple hosts can control the bus, we declare the nets _after_ the mux to be the _driver_ in this context.
I like the term _driver_ because it's applicable to both busses in the EE sense, and those in the transportation
sense. Alternate terms could be _controller_, _publisher_, _broadcaster_, _central_, or _master_, though I
personally avoid the latter.

An example bus _driver_ implementing a `localBus` protocol in Verilog could look like this.
```verilog
wire          driver_clk = my_clk;
wire [aw-1:0] driver_addr = my_addr;
wire [dw-1:0] driver_wdata = my_write_data;
wire [dw-1:0] driver_rdata; // The driver doesn't control this net, the passengers do!
wire          driver_wen = my_write_enable;
wire          driver_ren = my_read_enable;
```

### A bus _passenger_
Ok, this might be hitting the _bus_ metaphor a bit too hard, but I like the symmetry with _driver_.  This
describes a set of nets which should be attached to a bus and respond to transactions (perform writes when
requested, and respond to reads in its address space with data).  Alternate terms could be _peripheral_,
_responder_, _subscriber_, _remote_, or _slave_, though I really don't like that last one.

```verilog
wire          passenger_clk;
wire [aw-1:0] passenger_addr;
wire [dw-1:0] passenger_wdata;
wire [dw-1:0] passenger_rdata = my_read_data; // The one net the passenger controls
wire          passenger_wen;
wire          passenger_ren;
```

### A bus _entry_ (CSR)
This one doesn't quite fit the metaphor, but it is simply a `reg` or `wire` to store write data or from which
read data is sourced.  The auto-generated local _passenger_ parses writes from the _driver_ and divvies them
out to their addressed _entry_.  Symmetrically, it responds to reads from the _driver_ by latching the current
value of the addressed _entry_ into the `read_data` register.  A 1-dimensional _entry_ is commonly called a
_Control/Status Register_ (CSR) and can be read-only, write-only, or read/write.  A 2-dimensional _entry_ is
a RAM which is most often just a convenient structure and is actually unrolled into an array of CSRs, though
it can be used in both contexts automatically by __ghostbus__.

### Summary
Using the above metaphors, designing with __ghostbus__ involves creating one or more bus _drivers_ and allowing
the resulting auto-routed bus nets into every module where they're needed.  Then in each of these modules,
_entries_ (CSRs/RAMs) can be declared as usual right where they are used.  For those times where you need the
explicit nets of a bus (i.e. to interface with an existing module with bus ports), a bus _passenger_ is created
which gets address space allocated according to the width of its `address` net.

Additional magic comes from associating a _driver_ with a _passenger_ such that busses can be transformed,
(e.g. for crossing clock domains) and auto-routing can continue across the boundary of custom code.

## Attributes <a name="attributes"></a>

### Define a Ghostbus <a name="busdefine"></a>
```verilog
(* ghostbus_driver="port_name" *)
```
The nets that make up the Ghostbus must be identified individually because Verilog (not SystemVerilog)
has no way of associating the individual nets of a bus.  For a simple `localBus`-style bus, we need
at least a _clock_ net, and _address_ vector, and a _write-data_ and/or _read-data_ vector.

For `localBus`-protocol (currently the only bus protocol supported), the following are valid values for the
`ghostbus_driver` attribute:
* `clk`: the clock signal
* `addr`: the address vector
* `rdata`, `din`: the vector carrying data from the bus into the host
* `wdata`, `dout`: the vector carrying data from the host out onto the bus
* `wen`, `we`: the write-enable signal
* `ren`, `re`: the (optional) read-enable signal
* `write_strobe`, `wstb`, `wstrb`: the (optional) write-strobe signal (required for associated write strobes, see below)
* `read_strobe`, `rstb`, `rstrb`: the (optional) read-strobe signal (required for associated read strobes, see below)

_Example_:
```verilog
(* ghostbus_driver="clk" *)   wire             lb_clk;
(* ghostbus_driver="addr" *)  wire [LB_AW-1:0] lb_addr;
(* ghostbus_driver="rdata" *) wire [LB_DW-1:0] lb_rdata;
(* ghostbus_driver="wdata" *) wire [LB_DW-1:0] lb_wdata;
(* ghostbus_driver="wen" *)   wire             lb_wnr;

// Then just connect these nets to whatever is driving the bus (the bus controller) as usual
```

Alternate attribute names (pick your metaphor; they all work identically):
```verilog
(* ghostbus_driver="portname" *)
(* ghostbus_controller="portname" *)
(* ghostbus_pub="portname" *)
(* ghostbus_dom="portname" *)
```

__NOTE__: The way the ghostbus declaration is done should bring to mind how the ghostbus can play nicely on a sub-region
(i.e. "page") of an complete memory map involving some hand-decoding or routed/decoded by a separate tool.

__NOTE__: I'd love some help supporting other bus protocols (e.g. AXI4(lite), wishbone, etc). See `py/decoder_lb.py`.

In addition to the above, a method is provided to tack on one or more weird signals to your bus which will become part
of the bus definition and will "ride along" with the bus and get routed into all the same places the bus goes.  Some
oddball use cases could include a "pre-read" signal that gives forewarning that a read is coming, or some additional
context lines like a status/response code.  Only bus _passengers_ can make use of such a signal (as they are ignored
by the auto-generated local _passenger_).

For the below attributes, the `N` is any positive integer.  There is no upper bound to the number of wacky signals that
can ride along with your very strange bus.
* `extra_inN`, `extra_inputN`: some special net that is an input into the host/driver
* `extra_outN`, `extra_outputN`: some special net that is an output from the host/driver

_Example_:
```verilog
// Declare the ghostbus as in the example above
(* ghostbus_driver="clk" *)         wire lb_clk;
//... assume the rest of the ghostbus is declared

// Tack on an extra output (host-centric nomenclature) from the host
(* ghostbus_driver="extra_out0" *)  wire odd_duck; // who knows what this does? Ghostbus doesn't care.

// Declare a bus passenger sometime later.  Could be anywhere the ghostbus goes.
(* ghostbus_passenger="foo_bus, clk" *)        wire foo_clk;
//... again assume we declare as many nets of the bus as needed

// We'll also grab this special signal we defined earlier
(* ghostbus_passenger="foo_bus, extra_out0" *) wire foo_odd_duck;

// Note that "foo_odd_duck" will be directly driven by "odd_duck"
```
---------------------------------------------------------------------------------------------------
### Define a CSR/RAM <a name="csr"></a>
```verilog
// Add a CSR/RAM with R/W access (default)
(* ghostbus *)      reg foo;
(* ghostbus_ha *)   reg foo;
(* ghostbus_csr *)  reg foo;
(* ghostbus_ram *)  reg foo;
(* ghostbus="rw" *) reg foo; // Optional explicit access specifier

// Add a CSR/RAM with read-only access
(* ghostbus *)      wire foo;
(* ghostbus="r" *)  wire foo;
(* ghostbus="ro" *) wire foo;

// Add a CSR/RAM with write-only access
(* ghostbus="w" *)  reg foo;
(* ghostbus="wo" *) reg foo;

// INVALID r/w access of 'wire' type
(* ghostbus="rw" *) wire foo;

// INVALID w/o access of 'wire' type
(* ghostbus="w" *)  wire foo;
```
All the above attributes are aliases (function identically).
The various choices are provided for cases where you e.g. want to easily find your CSRs or your RAMs, or
perhaps find the simplified "ghostbus" attribute not "grepable" enough.

Add one of these attributes to a Verilog net to mark the net as host-accessible (i.e. a CSR/RAM).

__NOTE__: A writable register must be of net type `reg` while a read-only register can be of type `wire`
or `reg`.

__NOTE__: In an effort to minimize headache, the default access type (assumed when there is no explicit
access specifier string given to attribute `(* ghostbus *)`) is dependent on the net type.  For a `reg`
type net, the assumed access is read/write (rw).  For a 'wire' type net, the assumed access is
read-only (ro).  These assumptions only apply when no explicit specifier is given.

---------------------------------------------------------------------------------------------------
### Place a CSR/RAM at an explicit address <a name="address"></a>
```verilog
// A simple CSR at 0x2000
(* ghostbus_addr='h2000 *) reg foo;

// A submodule starting from base 0x800
(* ghostbus_addr='h800 *) my_module my_inst (
  .clk(clk), 
  .some_nets(my_nets)
  `GHOSTBUSPORTS
);

// A portion of an 8-bit passenger bus at base 0x100
(* ghostbus_addr='h100, ghostbus_passenger="foo, addr" *) wire [7:0] foo_addr;
```
Forces the tool to place the marked CSR/RAM/submodule/passenger at an explicit bas offset address
relative to the base address of the containing module.  Thus, if you want to place the object at
an explicit _global_ address, either do this at the top level (the same level the bus is declared),
or be careful about your math and assign explicit addresses at every layer of the hierarchy up
to the target object.
Explicit addresses get priority when assigning the memory map.
The tool will raise a Python exception if:
* the address conflicts with any other explicit address
* it requires more address bits than were allocated to the bus itself.
* the specified address is not aligned with the address width of the CSR/RAM/submodule (i.e. for address
  width `aw`, the least-significant `aw` bits of the base address must be zero).

__NOTE__: When used on a CSR/RAM, the `ghostbus_addr` attribute implies `ghostbus_ha` so you don't need
them both (though they will not conflict if you add them both).

---------------------------------------------------------------------------------------------------
### Add a simple strobe to the memory map <a name="simplestrobe"></a>
```verilog
(* ghostbus_strobe *) reg my_strobe=0;
```
This adds a single-bit strobe to the memory map.  When you write to the resulting address, the net will strobe
high triggered by the `wstb` signal of the bus while the written value is ignored/discarded.
If you want both the written value and a strobe when it is written, you want an "associated strobe" (see below).

__NOTE__: The tool currently only supports `reg` type nets, but it could easily support `wire` type in the future.

---------------------------------------------------------------------------------------------------
### Add a strobe vector to the memory map <a name="vectorstrobe"></a>
```verilog
(* ghostbus_strobe *) reg [SW-1:0] my_strobe_vector=0;
```

Using the same syntax as the simple strobe with a vector (multi-bit `reg` data type), a strobe vector
is created.  The individual bits in the vector are all strobes and, unlike the simple strobe, they
each only strobe when the corresponding bit in the written value is asserted.  Note that the written value
is not stored.

__NOTE__: The tool currently only supports `reg` type nets, but it could easily support `wire` type in the future.

---------------------------------------------------------------------------------------------------
### Add an associated strobe to a particular CSR/RAM  <a name="ascstrobe"></a>
```verilog
(* ghostbus_write_strobe="reg_name" *)
(* ghostbus_ws="reg_name" *)
(* ghostbus_read_strobe="reg_name" *)
(* ghostbus_rs="reg_name" *)
```
An "associated strobe" is a read/write-strobe that signals that the given operation has occurred on the address of
a given CSR (it's possible to use on a RAM but the use case isn't obvious to me; maybe it is to you).

For an associated write strobe, the net will strobe high in response to the `wstb` signal while a write operation
occurs on the associated register.

For an associated read strobe, the net will strobe high in response to the `rstb` signal while a read operation
occurs on the associated register.

_Example_:
```verilog
// A random CSR that you want to monitor
(* ghostbus *) reg [3:0] myReg=0;

// Define an associated write-strobe which will indicate when the bus writes to the "myReg" register
(* ghostbus_ws="myReg" *) reg myRegWS=1'b0;

// Define an associated read-strobe which will indicate when the bus reads from the "myReg" register
(* ghostbus_rs="myReg" *) reg myRegRS=1'b0;
```

---------------------------------------------------------------------------------------------------
### Attach an explicit external module to the Ghostbus <a name="busattach"></a>
```verilog
(* ghostbus_passenger="bus_name, port_name" *)
```

Alternate attribute names (pick your metaphor; they all work identically):
```verilog
(* ghostbus_passenger="bus_name, port_name" *)
(* ghostbus_peripheral="bus_name, port_name" *)
(* ghostbus_sub="bus_name, port_name" *)
```

As nice as it would be to build an entire codebase using just __ghostbus__ CSRs/RAMs, it's often necessary to attach
an existing module with a compatible bus interface to an auto-routed ghostbus.  Since the ghostbus routed via magic
macros, you can't just attach to it manually, you have to declare and tag nets with attributes much in the same way
that we define the ghostbus itself (see above).  The major asymmetry is that the bus needs a name as well (since we
can attach as many modules to the bus as we want) and this is the name that is used in the resulting memory map.

The address width of the _passenger_ bus determines the size of the chunk of memory map is allocated to this external
module (so use the minimum address width possible and zero-extend as needed).  Similarly, the data width is determined
by the width of the `wdata` and/or `rdata` vectors.  Both the address width (aw) and data width (dw) of the _passenger_
bus must be less than or equal to the associated aw/dw of the _driver_ ghostbus.

__NOTE__: If you already have access to the clock signal, the `clk` net on a _passenger_ bus is entirely optional.

_Example_: Instantiating a config romx and attaching it to a ghostbus at one of the LEEP-standard addresses
```verilog
// Declare a bus to connect the ROM
(* ghostbus_passenger="rom, rdata" *) wire [15:0] romx_rdata;
// Note that I'm giving it an explicit address here
(* ghostbus_passenger="rom, addr", ghostbus_addr='h4000 *) wire [10:0] romx_addr;

// Prevent recursive dependency
`ifdef YOSYS
// Configuration ROM
config_romx rom (
  .clk(clk), .address(romx_addr), .data(romx_rdata)
);
`endif
```

---------------------------------------------------------------------------------------------------
### Assign a CSR/RAM a global alias for the exported memory map file <a name="alias"></a>
```verilog
(* ghostbus_alias="foo" *)
```
Auto-generated names in the JSON file guarantee uniqueness, but of course create a critical dependence between the
host's name-based interface and the structure of the Verilog codebase.  This attribute allows selectively clobbering
the auto-generated names with an alias of your choice but leaves it up to the developer to avoid name collisions.
The tool will error out if an alias collides with an auto-generated name or another alias.

__NOTE__: Aliases are global (i.e. not hierarchically mangled)

_Example_:
```verilog
(* ghostbus, ghostbus_alias="mark_twain" *) reg [7:0] sam_clemens=0;
```

---------------------------------------------------------------------------------------------------
### Handling multiple bus domains <a name="domains"></a>
```verilog
// Attach CSR 'foo_dsp' to the ghostbus controlling domain 'dsp'
(* ghostbus, ghostbus_domain="dsp" *)   reg foo_dsp;

// Attach CSR 'foo_comms' to the ghostbus controlling domain 'comms'
(* ghostbus, ghostbus_domain="comms" *) reg foo_comms;

// Attach bus passenger 'bar' to the ghostbus controlling domain 'dsp'
(* ghostbus_passenger="bar, addr", ghostbus_domain="dsp" *) wire [7:0] bar_addr;

// Auto-route the ghostbus controlling domain 'comms' into submodule 'wiz_inst'
(* ghostbus_domain="comms" *) module_wiz #(...) wiz_inst (...);
```

Multiple ghostbusses can be declared at the same level, in which case we need to have a way to
specify which one we want to attach to.  When used with `ghostbus_driver` on the nets of a ghostbus,
this attribute specifies the name of the domain that this ghostbus is driving.  When used with
`ghostbus` on a CSR/RAM or `ghostbus_passenger` on a _passenger_ bus, this attribute specifies the
domain of the ghostbus to which the marked item should attach.

When used on a _ghostmod_ (a module which lets in a ghostbus with the `` `GHOSTBUSPORTS`` macro),
this attribute specifies the particular ghostbus which should be auto-routed into the _ghostmod_.
__NOTE__: Only one ghostbus can be auto-routed into a module... sorry!

---------------------------------------------------------------------------------------------------
### Joining ghostbusses <a name="ghostbus_branch"></a>
Sometimes you need to attach a ghostbus as a passenger of another ghostbus. I know that sounds silly,
but I've actually seen one legitimate use for such a feature.  If you need your bus to cross clock
domains (from domain __X__ to domain __Y__), you need to provide that logic yourself - it is
thoroughly outside of the ghostbus lane (see rule #1).

So you can start by attaching a [ghostbus passenger](#busattach) in domain __X__ to get explicit nets
hanging on the ghostbus, then use your own logic to cross the bus to domain __Y__.  Then you declare
the bus clock domain __Y__ as a [ghostbus driver](#busdefine) to automatically handle CSRs in that
domain as well.

But that would leave you with two unrelated memory maps (recall, ghostbus does _not_ inspect how
your nets are connected).  But what we want is for the second bus to be a _branch_ of the first,
allocating the appropriate addresses and memory alignment for the portion of the memory map in
this second domain.

We communicate this association to the tool with the `ghostbus_branch` attribute.  It can either
be placed on the _passenger_ or _driver_ side.  If placed on the _passenger_ bus in domain __X__,
the attribute value should be the name given to the _driver_ bus in domain __Y__.  If placed on
the _driver_ bus in domain __Y__, the attribute value should be the name of the _passenger_ bus
in domain __X__.

Example using `ghostbus_branch` on the _driver_ bus in domain __Y__:
```verilog
// ====================== Bus passenger in domain X ===========================
// This address width is fake! It will get its aw from "bus_y"
(* ghostbus_passenger="bus_x, clk"   *) wire bus_x_clk;
(* ghostbus_passenger="bus_x, addr"  *) wire [AW-1:0] bus_x_addr;
// etc... the other nets of the bus

// ======================== Bus driver in domain Y ============================
// This address width must match that of bus_x. Ultimately, it will
// only use the address bits needed to span the CSRs in its domain.
(* ghostbus_driver="bus_y, clk", ghostbus_domain="domain_y", ghostbus_branch="bus_x" *) wire bus_y_clk;
(* ghostbus_driver="bus_y, addr", ghostbus_domain="domain_y", ghostbus_branch="bus_x" *) wire [AW-1:0] bus_y_addr;
// etc... the other nets of the bus

// ======================= Roll-your-own CDC logic ============================
my_bus_cdc my_bus_cdc_i (
  .clk_x(bus_x_clk),
  .clk_y(bus_y_clk),
  ... // etc... other nets of both busses
);
```
---------------------------------------------------------------------------------------------------
### Create multiple independent ghostbusses <a name="ghostbus_top"></a>
```verilog
(* ghostbus_top *) my_module my_module_inst (...);
```

We can already create independent ghostbusses using the `ghostbus_domain` attribute (as described above),
so why do we need yet another?  Consider the oddball case in which we have a submodule which is instantiated
within a module containing ghostbus stuff (busses, CSRs, etc).  And suppose this submodule declares a new
ghostbus and does some auto-routing magic with that new (possibly totally unrelated) ghostbus.  Without
some special way of letting the tool know these are unrelated ghostbusses, the tool will assume that the
submodule is supposed to be on the memory map of the default ghostbus in the parent module and will allocate
space in the memory map and auto-generate hookup logic.  We can suppress this behavior by tacking the
`ghostbus_top` attribute to the submodule instantiation within the parent module. This should be quite rare
in practice as it's easy to structure your codebase to avoid such wackiness.

## Routing Macros  <a name="macros"></a>

For any module through which the __ghostbus__ routes, there are 3 places where you will need to add guarded macros.

The method of guarding the ghostbus macros is arbitrary (you decide).  All that is implied is that if you use it properly
you can build _with_ the auto-generated code included simply by defining the macro, or do not define it to build
_without_ the auto-generated code (still remains valid and synthesizable, but the bus connects to nothing).

In these examples, I simply use the macro `GHOSTBUS` to include the auto-generated code, but again it's an arbitrary choice.
In any case, a properly guarded ghostbus macro will look something like this:
```verilog
`ifdef GHOSTBUS
`GHOSTBUS_auto_generated_macro_goes_here
`endif
```

### Adding the "magic" ports to your module declaration (i.e. "let the ghostbus in") <a name="ghost_in"></a>
The ghostbus routes through the hierarchy using nets of the same width (simply masking out un-needed addr/data bits)
so there's a single explicit macro to add those ports (which you should put at the bottom of your port list).

_Example_:
```verilog
module foo (
  input clk,
  input [1:0] some_input,
  output [7:0] some_output // Note no comma! See "valid verilog" discussion
`ifdef GHOSTBUS
`GHOSTBUSPORTS
`endif
);
```

### Adding the "magic" ports to a module instantiation (i.e. "propogate the ghostbus") <a name="ghost_out"></a>
The yang to the `` `GHOSTBUSPORTS`` yin is not universal.  It is specific to both the module its within (the
"parent module") and the instance (not the module) it connects to.

The naming convention of the auto-generated macros is `` `GHOSTBUS_parentmodname_instname`` where `instname` is
the name of the instance being connected to the __ghostbus__ and `parentmodname` is the name of the module in
which the instantiation occurs.  Such a naming convention is required to guarantee uniqueness.

_Example_:
```verilog
module gerald (
  input clk,
  //...
);

// Two instances of the same module necessarily have different instance names
vince guaraldi (
  .clk(clk)
`ifdef GHOSTBUS
`GHOSTBUS_gerald_guaraldi
`endif
);

// Thus, they have different macros associated with them
vince staples (
  .clk(clk)
`ifdef GHOSTBUS
`GHOSTBUS_gerald_staples
`endif
);

endmodule
```

### Including the auto-generated decoding logic into the codebase <a name="decoder"></a>
The bus decoding logic is generated specific to each module through which the ghostbus passes
(even if it's just passing through).  A macro is created for each of these modules, so logically
the naming convention simply depends only on the module name in which the logic is included.

The naming convention of the bus decoding macros is `` `GHOSTBUS_modname`` where `modname` is
the name of the module in which it is to be included.

__NOTE__: To avoid warnings about usage before declaration, you should put this macro at the end
of the file (just before `endmodule`).

_Example_:
```verilog
module foo (
  input clk,
  //...
);

/*
  Assume there's a bunch of stuff here, including at least one CSR/RAM or ghostbus module
 */

`ifdef GHOSTBUS
`GHOSTBUS_foo
`endif

endmodule
```

### Including the macro definitions <a name="defs"></a>
This cat can be... shaved... in many ways.  A good solution for a particular build system is to pass
all the macro definitions to the synthesis tool directly (recall Verilog macros are global by definition).
All the macros generated by the __ghostbus__ tool are collected in a special file called `defs.vh` which
gets created in the directory of your choosing.

A very simple, but tedious, way to provide access to the macros to any module that needs it is to put
a guarded include of the `defs.vh` file at the top of each such file.  This is crude, but works.

_Example_:
```verilog
`ifdef GHOSTBUS
`include "defs.vh"
`endif

module foo (
  //...
);
endmodule
```
