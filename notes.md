## Generate-related bug
Discovered 250123
Symptom:
```
  File "/home/kpenney/repos/features/ghostbus/py/decoder_lb.py", line 1214, in _resolveBlockExts
    raise GhostbusInternalException(f"Inconsistent offsets between unrolled instances of {basename} in for loop {ext.genblock.branch}")
gbexception.GhostbusInternalException: **** Internal Ghostbus Error (broken tool) ****: Inconsistent offsets between unrolled instances of sig_buf in for loop gen_sig
```
So the issue is that the auto-generated decoding logic requires a consistent offset between unrolled instances of the same entries
(passenger, CSR, RAM, submod) so that the base address can be found via `base_addr_N = lowest_base_addr + N*offset`.  What are our
options for ensuring this happens?

Consider a simple generate branch with the following:
  CSR "csr" (aw=0)
  RAM "ram" (aw=4)
  Submod "mod" (aw=8)
Let's say the loop count is 4
A single branch of the loop requires 9-bits aw (512 addresses)

  ### Option 1: aligning the entire loop
    We could certainly tally up the entire memory space required for a single loop branch, as in:
    Loop index  Base    Entry
    -------------------------
    0           0x000   mod\_0
    0           0x100   ram\_0
    0           0x110   csr\_0
    1           0x200   mod\_0
    1           0x300   ram\_0
    1           0x310   csr\_0
    2           0x400   mod\_0
    2           0x500   ram\_0
    2           0x510   csr\_0
    3           0x600   mod\_0
    3           0x700   ram\_0
    3           0x710   csr\_0

    The entire unrolled loop occupies 0x000-0x710 = 11 bits = 9-bits + 2-bits of loop index (0-3)
    Pros:
      There's a single global loop offset (i.e. csr\_1 base - csr\2 base = mod\_3 base - mod\_2 base, etc...)
    Cons:
      Is it potentially over-inflated (sparser) than it could otherwise be?

  ### Option 2: aligning each entry in the loop
    Alternatively, we could align each entry as its own block.
    Loop index  Base    Entry
    -------------------------
    0           0x000   mod\_0
    1           0x100   mod\_1
    2           0x200   mod\_2
    3           0x300   mod\_3
    0           0x400   ram\_0
    1           0x410   ram\_1
    2           0x420   ram\_2
    3           0x430   ram\_3
    0           0x440   csr\_0
    1           0x441   csr\_1
    2           0x442   csr\_2
    3           0x443   csr\_3

    The entire unrolled loop occupies 0x000-0x443 = 11 bits = 9-bits + 2-bits of loop index (0-3)
    Pros:
      The address space is packed more tightly this way?  It doesn't actually matter... still occupies the same aw.
      Loop offset is simply the aw of the entry (as long as I pack the memory correctly like this).
    Cons:
      Need to keep track of individual loop offsets.

  Status:
    250124:
      I completely overhauled how extmods and ghostbusses are handled to try to unify them under the "driver/passenger"
      metaphor and to try to get some consistency in handling items in generate contexts.
      That allowed me to remove some generate-handling from `decoder_lb.py`, but I'm still in a broken state.
      Generate Policy:
        0. Net names are preserved as "branch[index].netname" until JSON creation or Verilog generation
        1. Loop instances are parsed from Yosys as separate objects; they are combined into a single meta-object
           with a `ref_list` and a simplified `netname` to be added to the memory map.
        2. Loop instances are unrolled during `GBMemoryMapStager.resolve()` using their `ref_list` and following the
           chosen memory alignment policy.
          2a. TODO - After they are resolved, all loop instances in `ref_list` should know their base address.  This
              should be communicated to the combined instance that is needed by `decoder_lb.py` so it doesn't have to
              build one itself.
        3. During JSON creation, net names are flattened using `Policy.flatten_hierarchy()` then shortened/mangled.
        4. TODO - FIXME! Before Verilog generation, instances need to be rolled up again.

TODO: Multi-ghostbus hierarchy parsing
  1. If nbusses > 1:
      All instantiated modules must be tagged with the `ghostbus_name` attribute.
      Raise Exception if any are not tagged or if the attribute value does not match
      any names in 'busnames'
  2. If nbusses > 1:
      Tag all instantiated modules with the particular ghostbus that is to be routed
      into them.
      This attribute must be inherited throughout the hiearchy
      2a. The auto-generated hookup code for these modules should reflect the net names
          of the named bus
  3. Break off branches of the MemoryTree including the "bustop" level and isolate the
      bus domains.
      3a. Also delete any CSRs that don't have the same bus domain.
  4. Each of these MemoryTree branches should make its own JSON relative to base 0.
  5. An external tool can combine the JSONs and ensure the resulting memory map reflects
      the hand-wired combination of the ghostbusses.

DONE: Permissive CSR access defaults
  If a detected CSR is of net `wire`, assume it's read-only.
  If a detected CSR is of net `reg`, assume it's read/write.

When Yosys generates a JSON, it follows this structure:
```json
  modules: {
    mod_inst : {},
  }
```
where `mod_inst` is a special identifier for not just every module present in the
design, but every unique instance (uniqueness determined by module type and
parameter values).
For any instantiated parameterized modules (when hierarchy set), their names are
listed as `$paramod$HASH\mod_name` where `HASH` is a 40-character hex string
which is probably just randomly generated as a hashmap key.

I'll need to keep these unique identifiers internally, but replace the hash stuff
with the hierarchy of the particular instance (which is also unique) before
generating the memory map.


