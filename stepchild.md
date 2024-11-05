## Feature Branch `stepchild`
I need a new construct that creates a relationship between a conjured bus (`ghostbus_ext`) and
a ghostbus (`ghostbus_port`).  This relationship functions the same as a ghostmod, and would
add one ghostbus to the memory map of a parent, but requires an alternate pathway to specify
that.

Issues to consider:
-------------------
1. Multiple ghostbusses need to be of the same width (see "Multiple Ghostbusses" below) but
   a conjured bus occupies space in the memory map in accordance with its width (`2**AW`).
   Thus an object that were simultaneously a ghostbus and a conjured bus would take up the
   whole memory map.  We need to instead communicate somehow that this is a special bus
   that belongs on the memory map, but only the lowest `N` bits of address should be driven,
   with `N` calculated based on the total size of its portion of the tree.
2. Can this special design case be communicated with the existing API (attributes)?  I would
   hate to add to the API unless absolutely necessary.
3. Remember to stick to the design philosophy and avoid heuristics or implied design intent.
   The API should be explicit and as simple as possible while maintaining perfectly valid
   Verilog (PVV).

Implementation:
---------------
__In source (verilog)__:
1. Declare the required nets (1 extmod and 1 named ghostbus)
2. Specify the relationship between the extmod and the bus (see syntax options below)
3. Declare the extmod with a DW/AW identical to that of the ghostbus (bits will be masked out as needed)

__In the tool (ghostbusser.py)__:
1. Associate the extmod with the ghostbus
2. Build the memory maps in order (child bus memory map completed first, then tacked onto the parent
   bus memory map as an extmod).
3. Generate proper decoding logic. Note that all the decoding logic will be included in `` `GHOSTBUS_modname``
   so no additional macros needed.

Syntax options:
---------------
  Example:
    extmod "papa" is branch of top-level bus and is connected (in verilog, not by ghostbus)
    to bus "bebe".
  I) Tell the bus it belongs to the extmod
    Pros:
      * We can use `ghostbus_alias` attribute (which currently is not defined for bus ports)
    Cons:
      * Seems a little backwards.  The bus needs no information from the extmod, but the extmod
        needs the size of the bus to properly decode.
    Ia)  Use two existing attributes
      ```verilog
      // Conjure the extmod as usual
      (* ghostbus_ext="papa, addr" *) wire [AW-1:0] papa_addr;
      // Create a named bus and reuse the "ghostbus_alias" to point to the extmod that owns it
      (* ghostbus_port="addr", ghostbus_name="bebe", ghostbus_alias="papa" *) wire [AW-1:0] bebe_addr;
      ```
      Pros:
        * existing aliases avoids increasing API complexity
        * adding the relationship info to the "child" object allows us to reuse `ghostbus_alias`
      Cons:
        * could muddle the formerly clear definition of an attribute usage
    Ib)  Extend syntax of existing attribute value
      ```verilog
      // Conjure the extmod as usual
      (* ghostbus_ext="papa, addr" *) wire [AW-1:0] papa_addr;
      // Create a named bus and extend the syntax of "ghostbus_name" attribute value to point to the extmod that owns it
      (* ghostbus_port="addr", ghostbus_name="papa->bebe" *) wire [AW-1:0] bebe_addr;
      ```
      Pros:
        * Minimize aliases
      Cons:
        * Kinda tortures the "name" part of `ghostbus_name`
        * Can't extend the `ghostbus_port` attribute value since that can already be a comma-separated list
    Ic)  Create a new attribute
      ```verilog
      // Conjure the extmod as usual
      (* ghostbus_ext="papa, addr" *) wire [AW-1:0] papa_addr;
      // Create a named bus create a new attribute "ghostbus_branch" to point to the extmod that owns it
      (* ghostbus_port="addr", ghostbus_name="bebe", ghostbus_branch="papa" *) wire [AW-1:0] bebe_addr;
      ```
      Pros:
        * Keeps usage of each attribute simple
      Cons:
        * Creating a new attribute adds complexity for specific/rare use case.
  II)  Tell the extmod that it owns the bus
    Pros:
      * Seems like the proper logical order; the extmod needs to know the size of the bus
        before it knows how many address bits it actually gets.
    Cons:
      * Can't use `ghostbus_alias` as that's already reserved for changing the name in the
        json file.
      * No natural existing attribute to convey this relationship
    IIb) Extend syntax of existing attribute value
      ```verilog
      // Conjure the extmod and reference some bus that it should get its size from
      (* ghostbus_ext="papa->bebe, addr" *) wire [AW-1:0] papa_addr;
      // Create a named bus as usual
      (* ghostbus_port="addr", ghostbus_name="bebe" *) wire [AW-1:0] bebe_addr;
      ```
      Pros:
        * Pretty simple
      Cons:
        * It's a lot of information in one attribute:
          - This is an extmod
          - Its name is "papa"
          - It gets its AW/DW from bus "bebe"
    IIc) Create a new attribute
      ```verilog
      // Conjure the extmod and reference some bus that it should get its size from
      (* ghostbus_ext="papa, addr", ghostbus_branch="bebe" *) wire [AW-1:0] papa_addr;
      // Create a named bus as usual
      (* ghostbus_port="addr", ghostbus_name="bebe" *) wire [AW-1:0] bebe_addr;
      ```
      Pros:
        * Makes each attribute simple and clear
      Cons:
        * Creating a new attribute adds complexity for specific/rare use case.

Dead ideas (been weeded out):
    IIa) Use two existing attributes
      ```verilog
      // Conjure the extmod and reference some bus that it should get its size from
      (* ghostbus_ext="papa, addr", ghostbus_name="bebe" *) wire [AW-1:0] papa_addr;
      // Create a named bus as usual
      (* ghostbus_port="addr", ghostbus_name="bebe" *) wire [AW-1:0] bebe_addr;
      ```
      Pros:
        * existing aliases avoids increasing API complexity
      Cons:
        * Can't use `ghostbus_name` since that already has meaning in this context
        * Could muddle the formerly clear definition of an attribute usage
        * Weird how similar the two declarations are.

