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
