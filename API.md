# Quick Links

[Attributes](#attributes)

* [Define the Ghostbus](#busdefine)

* [Define a CSR/RAM](#csr)

* [Place a CSR/RAM at an explicit global address](#address)

* [Add a simple strobe to the memory map](#simplestrobe)

* [Add an associated strobe to a particular CSR/RAM](#ascstrobe)

* [Conjuring: Add an external module to the Ghostbus](#conjure)

* [Assign a CSR/RAM a global alias for the JSON memory map](#alias)

[Routing Macros](#routing-macros)

* [Adding the "magic" ports to your module declaration (i.e. "let the ghostbus in")](#ghost_in)

* [Adding the "magic" ports to a module instantiation (i.e. "propogate the ghostbus")](#ghost_out)

* [Including the auto-generated decoding logic into the codebase](#decoder)

* [Including the macro definitions](#defs)

# API
All communication with the ghostbus Python tool is via Verilog attributes.
The attributes are documented below.  All attributes listed in the same code block are functional aliases
(no difference in functionality).  The different aliases are provided for personal choice or "grepability".

Recall that a major goal of the __ghostbus__ tool is that the Verilog remains valid as-is (before processing).
There are no "expanded" versions of the Verilog files, but instead we include auto-generated files inside
a conditional block ("guarded" includes) that ensures we only include them when they exist.

The auto-generated decoding and routing is placed into a series of files which are included by calling
specially-named macros.  While this is a bit painful, please blaim the limitations of the Verilog language,
not the author of this tool.  Complexity has been minimized as much as possible.

## Attributes

### Define the Ghostbus <a name="busdefine"></a>
```verilog
(* ghostbus_port="port_name" *)
```
The nets that make up the Ghostbus must be identified individually.  For a simple localbus-style bus,
we need at least a clock net, and address vector, and a write-data and/or read-data vector.  The tool
currently complains if it's not a R/W bus (both `rdata` and `wdata`) and if the `wen` signal is missing.
It's a __TODO__ to allow a read-only ghostbus.

For localbus-protocol, the following are valid values for the `ghostbus_port` attribute:
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
(* ghostbus_port="clk" *)   wire lb_clk;
(* ghostbus_port="addr" *)  wire [LB_AW-1:0] lb_addr;
(* ghostbus_port="rdata" *) wire [LB_AW-1:0] lb_rdata;
(* ghostbus_port="wdata" *) wire [LB_AW-1:0] lb_wdata;
(* ghostbus_port="wen" *)   wire [LB_AW-1:0] lb_wnr;

// Then just connect these nets to whatever is driving the bus (the bus controller) as usual
```

__NOTE__: The way the ghostbus declaration is done should bring to mind how the ghostbus can play nicely on a sub-region
(i.e. "page") of an complete memory map involving some hand-decoding or routed/decoded by a separate tool.

__NOTE__: I'd love some help supporting other bus protocols (e.g. AXI4(lite), wishbone, etc). See `py/decoder_lb.py`.

In addition to the above, a method is provided to tack on one or more weird signals to your bus which will become part
of the bus definition and will "ride along" with the bus and get routed into all the same places the bus goes.  Some
oddball use cases could include a "pre-read" signal that gives forewarning that a read is coming, or some additional
context lines like a status/response code.  The only way to use such signals is by _conjuring_ a "real bus" (see below)
and specifying the special net in question.

For the below attributes, the `N` is any positive integer.  There is no upper bound to the number of wacky signals that
can ride along with your very strange bus.
* `extra_inN`, `extra_inputN`: some special net that is an input into the host
* `extra_outN`, `extra_outputN`: some special net that is an output from the host

_Example_:
```verilog
// Declare the ghostbus as in the example above
(* ghostbus_port="clk" *)         wire lb_clk;
//... assume the rest of the ghostbus is declared

// Tack on an extra output (host-centric nomenclature) from the host
(* ghostbus_port="extra_out0" *)  wire odd_duck; // who knows what this does? Ghostbus doesn't care.

// Conjure a real bus sometime later.  Could be anywhere the ghostbus goes.
// See "Conjuring" discussion below
(* ghostbus_ext="foo_bus, clk" *)        wire foo_clk;
//... again assume we conjure as much of the bus as needed

// We'll also grab this special signal we defined earlier
(* ghostbus_ext="foo_bus, extra_out0" *) wire foo_odd_duck;

// Note that "foo_odd_duck" will assert whenever "odd_duck" asserts and the address specified is
// within the block allocated to the "foo_bus" external module (and "address hit")
```
---------------------------------------------------------------------------------------------------
### Define a CSR/RAM <a name="csr"></a>
```verilog
// Add a CSR/RAM with R/W access (default)
(* ghostbus *)
(* ghostbus_ha *)
(* ghostbus_csr *)
(* ghostbus_ram *)
(* ghostbus="rw" *) // Optional explicit access specifier

// Add a CSR/RAM with read-only access
(* ghostbus="r" *)
(* ghostbus="ro" *)

// Add a CSR/RAM with write-only access
(* ghostbus="w" *)
(* ghostbus="wo" *)
```
All the above attributes are aliases (function identically).
The various choices are provided for cases where you e.g. want to easily find your CSRs or your RAMs, or
perhaps find the simplified "ghostbus" attribute not "grepable" enough.

Add one of these attributes to a Verilog net to mark the net as host-accessible (i.e. a CSR/RAM).

__NOTE__: A writable register must be of net type `reg` while a read-only register can be of type `wire`
or `reg`.

---------------------------------------------------------------------------------------------------
### Place a CSR/RAM at an explicit global address <a name="address"></a>
```verilog
(* ghostbus_addr='h2000 *)
```
Forces the tool to place the marked CSR/RAM at an explicit address.
Explicit addresses get priority when assigning the memory map.
The tool will raise a Python exception if the address conflicts with any other explicit address or if
it requires more address bits than were allocated to the bus itself.

__NOTE__: The `ghostbus_addr` attribute implies `ghostbus_ha` so you don't need them both (though they will
not conflict if you add them both).

---------------------------------------------------------------------------------------------------
### Add a simple strobe to the memory map <a name="simplestrobe"></a>
```verilog
(* ghostbus_strobe *)
```
This adds a single-bit strobe to the memory map.  When you write to the resulting address, the net will strobe
high triggered by the `wstb` signal of the bus while the written value is ignored/discarded.

If you want both the written value and a strobe when it is written, you want an "associated strobe" (see below).

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
### Conjuring: Add an external module to the Ghostbus <a name="conjure"></a>
```verilog
(* ghostbus_ext="bus_name, port_name" *)
```
As nice as it would be to build an entire codebase using just ghostbus CSRs/RAMs, it's often necessary to attach an
existing module with a compatible bus interface to the ghostbus itself.  Since the ghostbus is auto-routed, you
can't just attach to it manually, you have to declare and tag nets with attributes much in the same way that we define
the ghostbus itself (see above).  The big difference is that the bus gets a name as well (since we can attach as many
modules to the bus as we want).  __NOTE__: we'll call this process _conjuring_ (going with the ghost metaphor).

The address width of the _conjured_ bus determines the size of the chunk of memory map is allocated to this external
module (so use the minimum address width possible and zero-extend as needed).  Similarly, the data width is determined
by the width of the `wdata` and/or `rdata` vectors.  Both the address width (aw) and data width (dw) of the external
module (i.e. the _conjured_ bus) must be less than or equal to the associated aw/dw of the ghostbus.

__NOTE__: Don't declare the `clk` net on a conjured bus.  So far the tool only supports a single clock domain.

_Example_: Instantiating the config romx and attaching it to the ghostbus at one of the LEEP-standard addresses
```verilog
// Conjure a bus to connect the romx
(* ghostbus_ext="rom, rdata" *) wire [15:0] romx_rdata;
// Note that I'm giving it an explicit address here
(* ghostbus_ext="rom, addr", ghostbus_addr='h4000 *) wire [10:0] romx_addr;

// Prevent recursive dependency
`ifdef YOSYS
// Configuration ROM
config_romx rom (
  .clk(clk), .address(romx_addr), .data(romx_rdata)
);
`endif
```

---------------------------------------------------------------------------------------------------
### Assign a CSR/RAM a global alias for the JSON memory map <a name="alias"></a>
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

## Routing Macros

For any module through with the __ghostbus__ routes, there are 3 places where you will need to add guarded macros.

The macro to guard the ghostbus macros is arbitrary (you decide).  All that is implied is that if you use it properly
you can build _with_ the auto-generated code included simply by defining the macro or do not define it to build
_without_ the auto-generated code (still remains valid, synthesizable, but the bus connects to nothing).

In these examples, I use the macro `GHOSTBUS_LIVE`, but again it's an arbitrary choice.  In any case, a properly
guarded ghostbus macro will look something like this:
```verilog
`ifdef GHOSTBUS_LIVE
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
`ifdef GHOSTBUS_LIVE
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
vince vaughn (
  .clk(clk)
`ifdef GHOSTBUS_LIVE
`GHOSTBUS_gerald_vaughn
`endif
);

// Thus, they have different macros associated with them
vince staples (
  .clk(clk)
`ifdef GHOSTBUS_LIVE
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

`ifdef GHOSTBUS_LIVE
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
`ifdef GHOSTBUS_LIVE
`include "defs.vh"
`endif

module foo (
  //...
);
endmodule
```
