# Special issues with Generate-If and Generate-For

Using __ghostbus__ attributes within a _generate_ block requires different auto-decoding logic to be generated.
And the two cases considered (conditional _generate-if_ and loop-based _generate-for_) create different issues
to consider.

## Generate-If
I assert that the memory region occupied by everything inside the _generate-if_ block must always be allocated
for those contents, even if they are not present due to the condition of the block being false.  This is because
there is no way to write the auto-generated code to parameterically (conditionally) reserve the block of memory.

Thus, if the condition of the generate block is false, the memory map will have a "hole" in its place and the
addresses of everything else will remain the same.

## Generate-For
Similarly to the case of a _generate-if_ block, the size of the memory region occupied by the contents of the
_generate-for_ block can depend on a parameter (i.e. the size of the unrolled loop).  The value this parameter
will take at synthesis time is in general unknown to __ghostbus__.  And since Verilog loop indices are generally
integers (32-bit), the absolute maximum possible size of the unrolled loop could be incredibly large (easily
exceeding the avaiable memory).

So instead of supporting the theoretical maximum, __ghostbus__ makes the policy decision to use the size of the
unrolled loop as seen by the parser (Yosys).  This means that you need to be careful to provide a sufficiently
wide scope of the codebase to ghostbus so that parameter values checked by the loop conditions resolve to the
same values they will have at synthesis time (i.e. don't pass that parameter "all the way up" to a level outside
of the scope of the code you hand to ghostbus unless you carefully pass the same value when __ghostbus__ parses
the code).

Even considering the above, there remains the issue of multiple instances of a module with a parameterized for-loop
getting different parameter values when instantiated.  For example, module `foo`, which has a loop that unrolls to
size `NLOOPS`, gets instantiated twice with `foo_0` having `NLOOPS=8` and `foo_1` having `NLOOPS=16`.  The auto-
generated code inside module `foo` is identical in both cases, but it is not in general possible (I think) to create
code that is properly parameterized to use the minimum address space in both cases (see discussion of _generate-if_).
So the consequence for __ghostbus__ is that each instance will occupy the size of the largest instance.  In the
previous example that means, `foo_0` will occupy the same memory as `foo_1` though the portion of memory representing
loop iterations 8-15 would be unavailable (empty).

## Macros
By necessity, some of the auto-generated decoding code needs to be inside the generate block to reach the nets only
available within the block scope.  Thus, an additional macro is created for every block.

### Macro Naming
Because of the above need to put auto-generated code inside each generate block, we need every block to be named
(or risk not getting the code in the right place). I don't think that Verilog enforces the rule that a block scope
identifier cannot collide with the instance name of a submodule, but I want to respect this rule so we don't need
to create even more mangled macro names.

Thus, the macro name convention will be (until it proves an issue) the same as that for submodule instances:
`` `GHOSTBUS_parentmodname_blockname`` where `blockname` is the block scope identifier.

I also don't know if Verilog enforces the rule that instance names within a block can't collide with instance names
outside of the block, but I'm going to enforce that rule until it proves an issue (once again to avoid adding
complexity to the macro names).  Thus, instantiating a module within a generate block is the same as in top-level
scope.

```verilog
module foo;

// Top-level decoding logic
`GHOSTBUS_foo

generate
  for (N=0; N<NMAX; N=N+1) begin: my_block

    // Block-scope decoding logic
    `GHOSTBUS_foo_my_block

    // Instances inside the generate use the same macro name convention as those outside
    bar loopy_bar (
      .clk(clk)
      `GHOSTBUS_foo_loopy_bar
    );

  end
endgenerate

// Thus, we can have instances inside the blocks and outside as well
bar top_bar (
  .clk(clk)
  `GHOSTBUS_foo_top_bar
);

endmodule
```

### Inner Monologue
For a register "foo" instantiated inside a _generate-for_ block "loop" (which say unrolls to 4 iterations),
will show up after Yosys parsing as four registers with names:
  loop[0].foo
  loop[1].foo
  loop[2].foo
  loop[3].foo
In general, I can't assume that I'll always encounter these in order while iterating through the Yosys-generated
dict object.  So like a bus or extmod, I'll need to handle these separately.

I'll hand them to a `_handleGenerates()` method.  This should split the name into `(branch_name, index, csr_name)`
and keep dict:
```python
  {block_name: {
    "source": yosrc_string, # only keep the first "yosrc" string encountered for "for-loop" parsing
    "csrs": {
      csr_name: [index, index, index, ...],
      ...
    },
    "rams": {
      ram_name: [index, index, index, ...],
      ...
    },
    "exts": {
      ext_name: [index, index, index, ...],
      ...
    },
  }
```
Then after parsing all the nets, we can call a "resolve" method which should do the following:
  0. Ensure all indicies are numeric, sequential, and complete
  1. Ensure the length of the indicies for each csr in the branch is identical
  2. Use the yosrc to find the for-loop parameters
  3. Calculate the size of the resulting objects. `Unrolled_AW = element_AW + clog2(len(indicies))`
  4. TODO: find any other instances and use the greatest `Unrolled_AW` for each instance
  5. Add all items to the memory map

