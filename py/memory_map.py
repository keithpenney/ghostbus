#! python3

import math

ACCESS_R=1
ACCESS_W=2
ACCESS_RW=ACCESS_R+ACCESS_W

REGION_SCALAR=0
REGION_ARRAY=1
REGION_MIRROR=2

MEMORY_RANGE_SCALAR = (0,1024)
MEMORY_RANGE_MIRROR = ((1<<23), (1<<24))
MEMORY_RANGE_ARRAY  = (1024, (1<<23))

def bits(v):
    return int(math.ceil(math.log2(v+1)))

def is_aligned(base, aw):
    """Return True if address 'base' is aligned to an address width of 'aw'"""
    mask = (1<<aw)-1
    if (base & mask) == 0:
        return True
    return False

class Register():
    READ = 1
    WRITE = 2
    RW = READ | WRITE
    UNSPECIFIED = 4
    _accessMask = RW | UNSPECIFIED

    @classmethod
    def accessToStr(cls, access):
        sd = {
            cls.READ: "r",
            cls.WRITE: "w",
            cls.RW: "rw",
            cls.UNSPECIFIED: "unknown",
        }
        return sd[access]

    def __init__(self, name=None, dw=1, base=None, meta=None, access=RW, label=None, desc=None):
        self._name = name
        self._size = 1
        self._data_width = int(dw)
        self._addr_width = 0
        self._base_addr = base
        # And optional descriptor/docstring
        self.desc = desc
        # A helpful bit of optional metadata
        self.meta = meta
        #self.access = int(access) & self._accessMask
        self.access = access
        if label is None:
            self.label = name
        else:
            self.label = label

    def copy(self):
        return self.__class__(name=self._name, dw=self._data_width, base=self._base_addr,
                              meta=self.meta, access=self.access, label=self.label, desc=self.desc)

    @property
    def name(self):
        if self._name is None:
            return "Register_{}".format(size)
        return self._name

    @name.setter
    def name(self, ss):
        self._name = ss
        return

    @property
    def size(self):
        return self._size

    @property
    def width(self):
        return self._addr_width

    @property
    def aw(self):
        """Alias for width"""
        return self._addr_width

    @aw.setter
    def aw(self, _aw):
        self._addr_width = int(_aw)
        return

    @property
    def datawidth(self):
        return self._data_width

    @property
    def dw(self):
        """Alias for datawidth"""
        return self._data_width

    @property
    def base(self):
        return self._base_addr

    @base.setter
    def base(self, value):
        self._base_addr = value
        return


class Memory(Register):
    def __init__(self, name=None, dw=1, aw=0, base=None, meta=None, access=Register.RW, label=None, desc=None):
        super().__init__(name=name, dw=dw, base=base, meta=meta, access=access, label=label, desc=desc)
        self._size = 1 << int(aw)
        self._addr_width = int(aw)

    def copy(self):
        return self.__class__(name=self._name, dw=self._data_width, aw=self._addr_width,
                              base=self._base_addr, meta=self.meta, access=self.access,
                              label=self.label, desc=self.desc)


def hexlist(ll):
    if not hasattr(ll, "__len__"):
        return hex(ll)
    return [hexlist(x) for x in ll]


def _deepCopy(ll):
    copy = []
    for entry in ll:
        copy.append(entry.copy())
    return copy


class MemoryRegion():
    """A memory allocator.
    * De-allocation by address
    * Only allows memory segments to be added at addresses aligned to their width, meaning:
        assert(addr % (1<<width) == 0)
    * Optionally keeps track of references (i.e. pointers) for convenient ordered access
      of objects in the memory region.
    * Is Iterable.  Meaning you can simply iterate over all regions by:
        mr = MemoryRegion()
        for elem, type in mr:
            start, end = elem
            assert(type in (mr.TYPE_VACANT, mr.TYPE_MEM))
      The "type" indicates whether that region is occupied (TYPE_MEM) or free (TYPE_VACANT)
      Note that the memory map is sorted so looping like this guarantees you iterate from low
      to high addresses.  There is currently no way to iterate from high to low addresses.
    * Items can be added to a pre-defined address with:
        mr.add(width, addr=address)
      or to the first available address simply with:
        mr.add(width)
    * If you need to collect items, then assign by priority, use class MemoryRegionStager,
      which also provides the ability to de-allocate and re-allocate.
    """
    TYPE_VACANT = 0
    TYPE_MEM = 1
    TYPE_KEEPOUT = 2
    _nregion = 0
    @classmethod
    def _inc(cls):
        cls._nregion += 1
        return

    def __init__(self, addr_range=(0, (1<<24)), label=None, hierarchy=None):
        """addr_range is [low, high), where the 'high' address is
        not inclusive.  For example, an 8-bit address range starting
        at 0x100 should be listed as: addr_range=(0x100, 0x200), not
        (0x100, 0x1ff).
        To identify the memory region, there are two (non-conflicting) options:
            'label' can be used to identify the memory region per application
            'hierarchy' can be used to keep track of region hierarchy
        """
        self._init_addr_range = addr_range
        self._offset = addr_range[0]
        self._relative_offset = self._offset
        # -1 because the upper address is not inclusive
        self._aw = bits((addr_range[1]-addr_range[0])-1)
        # Its own memory map will be defined relative to the base (not absolute addresses)
        self._top = (1 << self._aw)
        # Each entry is (start, end+1, ref) where 'ref' is either None or a Python object reference
        self.map = []
        self.vacant = [list(addr_range)]
        self._keepout = []
        self._hierarchy = hierarchy
        if label is None:
            self.label = "MemoryRegion" + str(self._nregion)
            self._inc()
        else:
            self.label = label
        self._delta_indent = 0 # see self.print()

    def check_complete(self):
        """Verify that the memory map is complete (contiguous, non-overlapping regions of any type)."""
        last_entry = None
        for entry, _type in self: # Iterator magic
            if last_entry is None:
                if entry[0] != 0:
                    raise Exception(f"MemoryRegion({self.name}) does not begin at zero! ({entry[0]}, {entry[1]})")
            else:
                if last_entry[1] != entry[0]:
                    raise Exception(f"MemoryRegion({self.name}) entries are not contiguous ({last_entry[0]}, {last_entry[1]}), ({entry[0]}, {entry[1]})")
            last_entry = entry
        if (last_entry is not None) and (last_entry[1] != (1<<self.width)):
            raise Exception(f"{self.label} Memory map has broken. last_entry = {last_entry}, self.width = {self.width}")
        return

    # Custom decorator
    def completed(fn):
        def wrapper(self, *args, **kw):
            # Call the function
            output = fn(self, *args, **kw)
            self.check_complete()
            return output
        return wrapper

    def reset(self):
        """Empty the memory region (start fresh with no allocated items)."""
        addr_range = self._init_addr_range
        self._offset = addr_range[0]
        # -1 because the upper address is not inclusive
        self._aw = bits((addr_range[1]-addr_range[0])-1)
        # Its own memory map will be defined relative to the base (not absolute addresses)
        self._top = (1 << self._aw)
        # Each entry is (start, end+1, ref) where 'ref' is either None or a Python object reference
        self.map = []
        self.vacant = [list(addr_range)]
        self._keepout = []
        return

    def copy(self):
        addr_range = (self._offset, self._offset + self._top)
        #print(f"        Copying (0x{addr_range[0]:x}, 0x{addr_range[1]:x}) {self.label}")
        mr = self.__class__(addr_range=addr_range, label=self.label, hierarchy=self._hierarchy)
        mr.map = []
        # We need a SUPER deep copy here
        for start, stop, ref in self.map:
            if ref is not None and hasattr(ref, "copy"):
                copy_ref = ref.copy()
            else:
                copy_ref = ref
            mr.map.append((start, stop, copy_ref))
        mr.vacant = []
        for start, stop in self.vacant:
            mr.vacant.append([start, stop])
        mr._keepout = []
        for start, stop, ref in self._keepout:
            mr._keepout.append([start, stop, ref])
        return mr

    @completed
    def shrink(self):
        """Reduce address range to the minimum aligned range containing
        the occupied portions of the map.  Note that it only scales the
        upper bound.  The lower bound remains fixed.
        Note that this could cause problems if you try to add more items
        to the memory region after shrinking.  It should probably only
        be called after you're sure you're done adding entries."""
        #print(f"{self.label} shrinking from {self._top}", end="")
        hi_occupied = self.high_addr()
        if hi_occupied > 0:
            if hi_occupied == 1:
                min_aw = bits(hi_occupied)
            else:
                min_aw = bits(hi_occupied-1)
            self._top = (1 << min_aw)
            self._aw = min_aw
        else:
            self._top = 0
            self._aw = 0
        if len(self.vacant) > 0:
            # If the top vacant is > self._top, we also need to truncate the last entry
            # in the "vacant" map
            if self.vacant[-1][1] > self._top:
                vacant = [self.vacant[-1][0], self._top]
                if vacant[1] == vacant[0]:
                    self.vacant.pop()
                else:
                    self.vacant[-1] = vacant
        #print(f" to {self._top}")
        return

    @completed
    def grow(self, high, absolute=False):
        """If high is an address greater than the current max address,
        extend the memory range to the next aligned point including that
        address (relative to the base, unless absolute=True).
        An exception is raised if 'high' is less than the current upper
        address."""
        if not absolute:
            aw = bits(high)
            high = self.base + high
        else:
            aw = bits(high-self.base)
        if self.top > high:
            raise Exception(("Memory region currently spans [0x{:x}, 0x{:x})." \
                    + " Cannot grow to 0x{:x}.").format(self.base, self.top, high))
        self._top = (1 << aw)
        # Also need to extend the last entry in the "vacant" map
        self.vacant[-1] = (self.vacant[-1][0], self._top)
        return

    @property
    def aw(self):
        return self._aw

    @property
    def hierarchy(self):
        return self._hierarchy

    @hierarchy.setter
    def hierarchy(self, hier):
        #print(f"MemoryRegion.hierarchy = {self._hierarchy} -> {hier}")
        self._hierarchy = hier
        # Propagate to lower regions
        for entry, _type in self: # Iterator magic
            ref = entry[2]
            if ref is not None and isinstance(ref, MemoryRegion):
                ref_hier = ref.hierarchy
                if ref_hier is not None:
                    ref_name = ref_hier[-1]
                else:
                    ref_name = ref.label
                ref.hierarchy = (*hier, ref_name)
        return

    @property
    def size(self):
        if len(self.map) == 0:
            return 0
        return self.high_addr()

    @property
    def empty(self):
        return self.size == 0

    @property
    def top(self):
        return self._offset + self._top

    @property
    def base(self):
        return self._offset

    @base.setter
    def base(self, value):
        #print(f"***************** base => {self._offset} -> {value} ({self._top})")
        self._offset = value
        for n in range(len(self.map)):
            start, end, ref = self.map[n]
            if isinstance(ref, MemoryRegion):
                ref.base = value + start
        return

    @property
    def relative_base(self):
        return self._relative_offset

    @relative_base.setter
    def relative_base(self, value):
        self._relative_offset = value
        return

    @property
    def width(self):
        return bits(self._top-1)

    @property
    def name(self):
        if self.hierarchy is None:
            return self.label
        else:
            return ".".join([str(x) for x in self.hierarchy])

    @property
    def shortname(self):
        if self.hierarchy is None:
            return self.label
        else:
            return self.hierarchy[-1]

    def _vet_addr(self, addr, width=0):
        """Raise an exception if 'addr' is not aligned to 'width' or if an
        allocated region of size (1<<width) based at 'addr' would exceed
        the boundaries of the region."""
        size = 1<<int(width)
        addr = int(addr)
        if addr < 0:
            raise Exception("Address must be unsigned, not {}".format(addr))
        if addr % size:
            raise Exception("Address 0x{:x} is not aligned to width {}".format(addr, width))
        if addr + size > self.top:
            raise Exception("Adding element of size {} rooted at address 0x{:x} ".format(size, addr) \
                    + "would exceed bounds of memory region [0x{:x}->0x{:x})".format(self.base, self.top))
        return True

    def __iter__(self):
        # We're an iterator now
        self.sort()
        self._im = 0
        self._iv = 0
        self._ik = 0
        return self

    def __next__(self):
        mempty = False
        vempty = False
        kempty = False
        if self._im < len(self.map):
            mem = self.map[self._im]
        else:
            mempty = True
        if self._iv < len(self.vacant):
            vac = self.vacant[self._iv]
            vac = (vac[0], vac[1], None) # Same shape as 'mem'
        else:
            vempty = True
        if self._ik < len(self._keepout):
            ko = self._keepout[self._ik]
        else:
            kempty = True
        if mempty and vempty and kempty:
            #print(f"  mempty ({len(self.map)}) and vempty ({len(self.vacant)}) and kempty ({len(self._keepout)})!")
            raise StopIteration
        elif kempty:
            if vempty:
                self._im += 1
                return mem, self.TYPE_MEM
            elif mempty:
                self._iv += 1
                return vac, self.TYPE_VACANT
            elif mem[0] < vac[0]:
                self._im += 1
                return mem, self.TYPE_MEM
            else:
                self._iv += 1
                return vac, self.TYPE_VACANT
        elif mempty:
            if vempty or ko[0] < vac[0]:
                self._ik += 1
                return ko, self.TYPE_KEEPOUT
            else:
                self._iv += 1
                return vac, self.TYPE_VACANT
        elif vempty:
            if mempty or ko[0] < mem[0]:
                self._iv += 1
                return vac, self.TYPE_VACANT
            else:
                self._im += 1
                return mem, self.TYPE_MEM
        elif ko[0] < min(mem[0], vac[0]):
            self._ik += 1
            return ko, self.TYPE_KEEPOUT
        elif mem[0] < min(ko[0], vac[0]):
            self._im += 1
            return mem, self.TYPE_MEM
        else: # vac[0] < min(ko[0], mem[0]):
            self._iv += 1
            return vac, self.TYPE_VACANT

    def remove(self, addr):
        """Remove an entry rooted at 'addr' (and return it to vacant)"""
        #print(f"      #### MemoryRegion.remove(0x{addr:x}) ####")
        removed = False
        for n in range(len(self.map)):
            _start, _stop, _ref = self.map[n]
            if _start == addr:
                del self.map[n]
                removed = True
                break
        vacated = False
        if removed:
            vacated = self._vacate(_start, _stop)
            if not vacated:
                #print(f"WARNING! Failed to vacate 0x{addr:x}")
                pass
        return (removed and vacated)

    @completed
    def _vacate(self, start, stop):
        # Six cases:
        #   0: start is before (and not adjacent to) the first vacant region, insert new region
        #   1: start is before and adjacent to the first vacant region, merge with the first region
        #   2: start, stop is between (and not adjacent to) two regions, insert new region
        #   3: start is adjacent to the regions below and above (merge all three)
        #   4: start is adjacent to the region below (merge with below)
        #   5: stop is adjacent to the region above (merge with above)
        base = start
        end = stop
        new_entry = (base, end)
        success = False
        print(f"Trying to vacate (0x{start:x}, 0x{stop:x})")
        for n in range(len(self.vacant)):
            this_entry = self.vacant[n]
            if n == len(self.vacant) - 1:
                next_entry = (-1, -1)
            else:
                next_entry = self.vacant[n+1]
            this_base, this_end = this_entry
            next_base, next_end = next_entry
            #print(f"           this_entry = (0x{this_base:x}, 0x{this_end:x}); next_entry = (0x{next_base:x}, 0x{next_end:x})")
            if (n == 0):
                #   0: start is before (and not adjacent to) the first vacant region, insert new region
                if end < this_base:
                    print(f"this_entry = (0x{this_base:x}, 0x{this_end:x}); next_entry = (0x{next_base:x}, 0x{next_end:x})")
                    print(f"vacate 0: adding (0x{base:x}, 0x{end:x}) to the start")
                    self.vacant.insert(0, new_entry)
                    success = True
                    break
                #   1: start is before and adjacent to the first vacant region, merge with the first region
                elif end == this_base:
                    print(f"this_entry = (0x{this_base:x}, 0x{this_end:x}); next_entry = (0x{next_base:x}, 0x{next_end:x})")
                    print(f"vacate 1 replacing (0x{self.vacant[0][0]:x}, 0x{self.vacant[0][1]:x}) with (0x{base:x}, 0x{this_end:x})")
                    self.vacant[0] = (base, this_end)
                    success = True
                    break
            #   2: start, stop is between (and not adjacent to) two regions, insert new region
            if (base > this_end) and (end < next_base):
                print(f"this_entry = (0x{this_base:x}, 0x{this_end:x}); next_entry = (0x{next_base:x}, 0x{next_end:x})")
                print(f"vacate 2 inserting (0x{base:x}, 0x{end:x}) after (0x{self.vacant[n][0]:x}, 0x{self.vacant[n][1]:x})")
                self.vacant.insert(n+1, new_entry)
                success = True
                break
            #   3: start is adjacent to the regions below and above (merge all three)
            if (base == this_end) and (end == next_base):
                print(f"this_entry = (0x{this_base:x}, 0x{this_end:x}); next_entry = (0x{next_base:x}, 0x{next_end:x})")
                print(f"vacate 3 replacing (0x{self.vacant[n][0]:x}, 0x{self.vacant[n][1]:x}) with (0x{this_base:x}, 0x{next_end:x})" + \
                      f" and deleting (0x{self.vacant[n+1][0]:x}, 0x{self.vacant[n+1][1]:x})")
                self.vacant[n] = (this_base, next_end)
                del self.vacant[n+1]
                success = True
                break
            #   4: start is adjacent to the region below (merge with below)
            if (base == this_end):
                print(f"this_entry = (0x{this_base:x}, 0x{this_end:x}); next_entry = (0x{next_base:x}, 0x{next_end:x})")
                print(f"vacate 4 replacing (0x{self.vacant[n][0]:x}, 0x{self.vacant[n][1]:x}) with (0x{this_base:x}, 0x{end:x})")
                self.vacant[n] = (this_base, end)
                success = True
                break
            #   5: stop is adjacent to the region above (merge with above)
            if (end == next_base):
                print(f"this_entry = (0x{this_base:x}, 0x{this_end:x}); next_entry = (0x{next_base:x}, 0x{next_end:x})")
                print(f"vacate 5 replacing (0x{self.vacant[n+1][0]:x}, 0x{self.vacant[n+1][1]:x}) with (0x{base:x}, 0x{next_end:x})")
                self.vacant[n+1] = (base, next_end)
                success = True
                break
        return success

    def add_item(self, item, offset=None, keep_base=False):
        """Raises an exception if 'item' has no 'width' property.
        If self has a hierarchy, it gets propagated to the item."""
        if item == self:
            raise Exception("Attempting to add self to own memory map.")
        addr = None
        width = int(getattr(item, "width"))
        if keep_base and hasattr(item, "base"):
            addr = int(getattr(item, "base"))
        if offset is not None:
            if addr is None:
                addr = offset
            else:
                addr += offset
        return self.add(width=width, ref=item, addr=addr)

    def add(self, width=0, ref=None, addr=None):
        base = self._add(width, ref=ref, addr=addr, type=self.TYPE_MEM)
        # If the item referenced by 'ref' has a 'base' attribute, update it
        if ref is not None and hasattr(ref, "base"):
            ref.base = base
        if ref is not None and hasattr(ref, "relative_base"):
            ref.relative_base = base
        return base

    def keepout(self, addr, width=0):
        return self._add(width, ref=None, addr=addr, type=self.TYPE_KEEPOUT)

    @completed
    def _add(self, width=0, ref=None, addr=None, type=TYPE_MEM):
        """Add a memory element of address width 'width' that can optionally
        be referenced by 'ref' (e.g. a variable identifier (pointer))
        If 'addr' is None, the element will be added to the first available
        slot that is large enough and is aligned with its width.
        Otherwise ('addr' is unsigned int), it will attempt to add the element
        to the address supplied, raising an exception if the address is not
        aligned to the width, if it would overlap an existing entry, or if it
        is outside the bounds of the region."""
        if addr is None:
            base, end = self._push(width, ref=ref)
        else:
            base, end = self._insert(addr, width, type=type, ref=ref)
        refname = None
        if ref is not None and hasattr(ref, "name"):
            refname = ref.name
        if self.hierarchy is not None:
            if hasattr(ref, 'hierarchy'):
                ref.hierarchy = (*self.hierarchy, *ref.hierarchy)
            else:
                #print(f"    !!!! {ref.name} has no hierarchy?!?!?")
                pass
        else:
            #print(f"    !!!! {self.label} self.hierarchy is None!")
            pass
        return base

    def _insert(self, addr, width=0, type=TYPE_MEM, ref=None):
        """Add a memory element of address width 'width' to the memory map
        starting at address 'addr'.  Raises an exception if such an entry would
        overlap with existing elements or the bounds of the region."""
        self._vet_addr(addr, width)
        base = addr
        end = addr + (1<<width)
        fit_elem = None
        #print(f"  _insert: {self.label} I have a width of {self.width} and vacant[-1] = {self.vacant[-1]}")
        # First find whether 'addr' is within an occupied or vacant region
        for entry, _type in self: # Iterator magic
            e_base, e_end, e_ref = entry
            #print(f" _insert: walking 0x{e_base:x}:0x{e_end} ({e_ref}) ({_type})")
            if (base >= e_base) and (base < e_end):
                # 'addr' is in this element
                if _type != self.TYPE_VACANT:
                    raise Exception("Address 0x{:x} falls within occupied element spanning 0x{:x} to 0x{:x}".format(
                        addr, e_base, e_end))
                # Next we need to ensure 'end' also falls within this same vacant entry
                if end > e_end:
                    raise Exception("Element spanning addresses [0x{:x}->0x{:x}) overlaps with occupied address 0x{:x}".format(
                        addr, end, e_end))
                else:
                    # It fits!
                    fit_elem = entry[:2]
                    break
        if fit_elem is None:
            overlap_entries = self.get_overlap(addr, end)
            if len(overlap_entries) == 0:
                raise Exception(f"It appears [0x{addr:x}->0x{end:x}) is outside our boundaries?!")
            err = f"Could not fit [0x{addr:x}->0x{end:x}) into memory map. " + \
                  f"It overlaps with {len(overlap_entries)} entries, spanning [0x{overlap_entries[0][0]:x}->" + \
                  f"0x{overlap_entries[-1][1]:x})"
            start_ref = overlap_entries[0][2]
            stop_ref = overlap_entries[-1][2]
            if (start_ref is not None) or (stop_ref is not None):
                err += " ({start_ref}->{stop_ref})"
            raise Exception(err)
        # Unfortunately we need to loop through the vacancies again to get the index of this element
        # This is due to the custom iterator which manages two separate lists
        for n in range(len(self.vacant)):
            vmem = self.vacant[n]
            if (fit_elem[0] != vmem[0]) or (fit_elem[1] != vmem[1]):
                continue
            # We've found the correct entry.  Also, the second comparison is almost certainly redundant
            # Already vetted the location and size
            # Modify vmem[1] in-place
            old_end = self.vacant[n][1]
            if self.vacant[n][0] < base:
                # Truncate downward the existing vacant region
                #print(f"---{self.label} self.vacant[{n}][1] -> {base}")
                self.vacant[n][1] = base
                if old_end > end:
                    # Add a new vacancy region above the occupied section
                    #print(f"---{self.label} self.vacant.insert({n+1}, {[end, old_end]})")
                    self.vacant.insert(n+1, [end, old_end])
            else:
                # Truncate upward the existing vacant region
                if old_end > end:
                    # Still some vacancy above the occupied section
                    #print(f"---{self.label} self.vacant[{n}] = {[end, old_end]}")
                    self.vacant[n] = [end, old_end]
                else:
                    # We occupied the exact size of this vacant region
                    #print(f"---{self.label} del self.vacant[{n}]")
                    del self.vacant[n]
            # Add the memory region
            if type == self.TYPE_MEM:
                self.map.append((base, end, ref))
            elif type == self.TYPE_KEEPOUT:
                self._keepout.append((base, end, None))
            else:
                raise Exception("Invalid type {} to add to memory".format(type))
            break
        return base, end

    def get_available_base(self, width=0, start=0):
        """Get the next available base address that fits an entry of address
        width 'width' starting from (and including) address 'base'."""
        size = 1<<int(width)
        for n in range(len(self.vacant)):
            vmem = self.vacant[n]
            vmem_size = vmem[1]-vmem[0]
            if vmem[1] <= start:
                # This vacant region ends before 'start'
                continue
            _start = max(vmem[0], start)
            aligned_start = size*math.ceil(_start / size)
            aligned_size = vmem[1]-aligned_start
            if aligned_size >= size:
                # We can add it!
                return aligned_start
        return None

    def _push(self, width=0, ref=None):
        """Add a memory element of address width 'width' to the memory map
        at the first location which fits and is aligned to 'width'."""
        size = 1<<int(width)
        base = None
        end = None
        for n in range(len(self.vacant)):
            vmem = self.vacant[n]
            vmem_size = vmem[1]-vmem[0]
            aligned_start = size*math.ceil(vmem[0] / size)
            aligned_size = vmem[1]-aligned_start
            if aligned_size >= size:
                # We can add it!
                # Modify vmem[1] in-place
                old_end = self.vacant[n][1]
                mem_end = aligned_start + size
                if self.vacant[n][0] < aligned_start:
                    # Truncate downward the existing vacant region
                    self.vacant[n][1] = aligned_start
                    if old_end > mem_end:
                        # Add a new vacancy region above the occupied section
                        self.vacant.insert(n+1, [mem_end, old_end])
                else:
                    # Truncate upward the existing vacant region
                    if old_end > mem_end:
                        # Still some vacancy above the occupied section
                        self.vacant[n] = [mem_end, old_end]
                    else:
                        # We occupied the exact size of this vacant region
                        del self.vacant[n]
                # Add the memory region
                self.map.append((aligned_start, mem_end, ref))
                base = aligned_start
                end = mem_end
                break
        if base is None:
            raise Exception("{} has no room for memory of width {}".format(self.label, width))
        return base, end

    def get_by_address(self, address):
        """Get (start, stop, ref) for whatever the entry is that overlaps with address 'address'."""
        for entry, _type in self: # Iterator magic
            start, stop, ref = entry
            if (start <= address) and (stop > address):
                return entry
        return (None, None, None)

    def get_overlap(self, start, stop):
        """Get a list of entries [(start, stop, ref), ...] which overlap with addresses 'start'->'stop'"""
        entries = []
        for entry, _type in self: # Iterator magic
            that_start, that_stop, _ref = entry
            if (start >= that_start): # this starts at or after that starts
                if (start < that_stop): # this starts before that stops
                    entries.append(entry) # overlap
                else: # this starts after that stops
                    pass # no overlap
            else: # this starts before that starts
                if (stop > that_start): # this stops after that starts
                    entries.append(entry) # overlap
                else: # this stops before that starts
                    pass # no overlap
        return entries

    def sort(self):
        # TODO - Is this even needed? Maybe make a decorator that checks for map and vacant unsorted
        self.map.sort(key=lambda x: x[0])
        self.vacant.sort(key=lambda x: x[0])
        return

    def __str__(self):
        if self._hierarchy is not None:
            return f"MemoryRegion({self._hierarchy})"
        else:
            return f"MemoryRegion({self.label})"

    def __repr__(self):
        return self.__str__()

    def str(self, indent=0):
        ss = ["|{:^19s}|{:^19s}|".format("Used", "Free"),
              "|{0}|{0}|".format("-"*19)]
        empty = " "*19
        for entry, _type in self: # Iterator magic
            ref = entry[2]
            if ref is not None and isinstance(ref, MemoryRegion):
                #print(f"1020 ref {ref.name} is type {type(ref)}: {ref}")
                dn = indent+self._delta_indent
                ref._delta_indent = self._delta_indent
                rs = ref.str(dn)
                rslines = rs.split('\n')
                # Replace the top line
                title = "{}: {:x}-{:x}".format(ref.name, ref.base, ref.top)
                rslines[0] = " "*(dn) + "|{:^39s}|".format(title)
                # Add a delimiter to the top and bottom
                delim_top = " "*(self._delta_indent)+ "|{}|".format("-"*39)
                delim_bottom = " "*(indent) + delim_top
                rslines.insert(0, delim_top)
                rslines.append(delim_bottom)
                rs = '\n'.join(rslines)
                ss.append(rs)
            else:
                if ref is not None:
                    #print(f"1021 ref {ref.name} is type {type(ref)}: {ref}")
                    pass
                elemstr = " {:8x}-{:8x} ".format(self.base + entry[0], self.base + entry[1])
                if _type == self.TYPE_MEM:
                    ordered = (elemstr, empty)
                elif _type == self.TYPE_VACANT:
                    ordered = (empty, elemstr)
                else: # _type == self.TYPE_KEEPOUT
                    # Not printing keepouts for now
                    continue
                ss.append("|{}|{}|".format(*ordered))
        sindent = "\n" + " "*indent
        return " "*indent + sindent.join(ss)

    def print(self, indent=0):
        self._delta_indent = indent
        print(self.str())
        return

    def high_addr(self):
        """Return the highest occupied address + 1."""
        self.sort()
        if len(self.map) > 0:
            return self.map[-1][1]
        return 0

    def base_addr(self):
        """Return the base address of the memory region"""
        return self._offset

    def get_entries(self):
        """Return a list of entries. Each entry is (start, end+1, ref) where 'ref' is applications-specific
        (e.g. a Python object reference, a string, None, etc)."""
        return self.map.copy()

    def _collectCommon(self, common=None):
        hier = self.hierarchy
        # Pass 0: find out if there are any registers defined here
        hasregs = False
        for start, stop, item in self.map:
            if isinstance(item, Register):
                hasregs = True
                break
        if hasregs:
            if common is None:
                common = list(hier)
            else:
                common = self._getCommon(hier, common)
            # print(f"{self.name} has regs; common = {common}")
        else:
            # print(f"{self.name} has NO regs; common = {common}")
            pass
        # If not hasregs, common passes through
        # Pass 1
        for start, stop, item in self.map:
            if isinstance(item, MemoryRegion):
                common = item._collectCommon(common)
                #print(f"MemoryRegion: {item.hierarchy}")
        # print(f"{self.name} returning {common}")
        return common

    def _nullHierarchy(self, nempty):
        """Set the first 'nempty' entries of the hierarchy to the emptry string ''."""
        #if hasattr(self, 'domain'):
        #    name = f"{self.name}({self.domain})"
        #else:
        #    name = self.name
        #print(f"  567 {name} Nulling {nempty} entries. {self.hierarchy}")
        if self.hierarchy is None:
            return
        hier = list(self.hierarchy)
        for n in range(min(nempty, len(hier))):
            hier[n] = ""
        self.hierarchy = hier
        # print(f"  Done nulling. {self.hierarchy}")
        # Unfortunately, I can't rely on the self.hierarchy setter because
        # nempty could be > len(self.hierarchy)
        if nempty > len(self.hierarchy):
            for start, stop, item in self.map:
                if hasattr(item, "_nullHierarchy"):
                    item._nullHierarchy(nempty)
        return

    def trim_hierarchy(self):
        """This requires two passes.  Pass #0 identifies any common prefix to the
        hierarchy of all MemoryRegions.  If the common element is not the empty list,
        pass #1 sets the first len(common) items of each MemoryRegion's hierarchy to empty
        strings."""
        common = self._collectCommon()
        if common is None or len(common) == 0:
            # print("    No common root. Done")
            return
        else:
            # print(f"    Common root: {common}")
            pass
        self._nullHierarchy(len(common))
        return

    @staticmethod
    def _getCommon(l0, l1):
        """Get the common overlap between the two lists, starting from index 0.
        E.g. if l0 = [1,2,3,4,5] and l1=[1,2,9], returns [1,2].
        If l0[0] != l1[0], returns []"""
        common = []
        for n in range(min(len(l0), len(l1))):
            if l0[n] == l1[n]:
                common.append(l0[n])
            else:
                break
        return common


class MemoryRegionStager(MemoryRegion):
    """Uses a near-indentical API as class MemoryRegion, but doesn't actually compose
    the map until you call 'resolve()' which adds explicit-address entries first, then
    the implicit-address entries."""
    UNRESOLVED = False
    RESOLVED = True
    def __init__(self, addr_range=(0, (1<<24)), label=None, hierarchy=None):
        super().__init__(addr_range=addr_range, label=label, hierarchy=hierarchy)
        # Each entry = (item, addr, addr_width, type)
        self._entries = []
        self._keepouts = []
        self._explicits = []
        self._resolved = False
        self.init()

    def copy(self):
        cp = super().copy()
        cp._entries = self._entries.copy()
        cp._keepouts = self._keepouts.copy()
        cp._explicits = self._explicits.copy()
        return cp

    def _base_add_item(self, *args, **kwargs):
        # Weird hack to allow inheriting classes to bypass the overloaded methods
        return super().add_item(*args, **kwargs)

    def add_item(self, item, offset=None, keep_base=False):
        """Overloaded to Stage-only"""
        addr_width = None
        if hasattr(item, 'aw'):
            addr_width = item.aw
        if offset is not None:
            self._explicits.append((item, offset, addr_width, self.TYPE_MEM, self.UNRESOLVED))
        else:
            self._entries.append((item, offset, addr_width, self.TYPE_MEM, self.UNRESOLVED))
        self._resolved = False
        return

    def _base_add(self, *args, **kwargs):
        # Weird hack to allow inheriting classes to bypass the overloaded methods
        return super().add(*args, **kwargs)

    def add(self, width=0, ref=None, addr=None):
        """Overloaded to Stage-only"""
        if addr is not None:
            self._explicits.append((ref, addr, width, self.TYPE_MEM, self.UNRESOLVED))
        else:
            self._entries.append((ref, addr, width, self.TYPE_MEM, self.UNRESOLVED))
        self._resolved = False
        return

    def keepout(self, addr, width=0):
        """Overloaded to Stage-only"""
        self._keepouts.append((None, addr, width, self.TYPE_KEEPOUT, self.UNRESOLVED))
        self._resolved = False
        return

    def remove(self, addr):
        lists = (self._keepouts, self._explicits, self._entries)
        removed = False
        for _list in lists:
            for n in range(len(_list)):
                ref, base, aw, _type, resolved = _list[n]
                if base == addr:
                    del _list[n]
                    #print(f"                                    Deleting {ref}")
                    removed = True
                    break
            if removed:
                break
        if not removed:
            #print(f"                           Failed to remove {addr}")
            pass
        return super().remove(addr)

    @staticmethod
    def _resolve_ref(ref, aw):
        if hasattr(ref, "resolve"):
            ref.resolve()
        if hasattr(ref, 'shrink'):
            ref.shrink()
        if hasattr(ref, 'aw'):
            aw = ref.aw
        return aw

    def init(self):
        self._resolve_pass_methods = []
        self.add_resolve_pass(self._resolve_pass_keepouts)
        self.add_resolve_pass(self._resolve_pass_explicits)
        self.add_resolve_pass(self._resolve_pass_else)
        self._resolve_passes = len(self._resolve_pass_methods)
        return

    def add_resolve_pass(self, method):
        #TODO - Sanitize/check the 'method' input as callable
        self._resolve_pass_methods.append(method)
        return

    def set_resolve_pass(self, npass, method):
        #TODO - Sanitize/check the 'method' input as callable
        self._resolve_pass_methods[npass] = method
        return

    def _resolve_pass(self, npass):
        if npass > len(self._resolve_pass_methods):
            raise Exception(f"MemoryRegionStager has no resolve pass {npass} (only have {len(self._resolve_pass_methods)})")
        #method = getattr(self, self._resolve_pass_methods[npass])
        method = self._resolve_pass_methods[npass]
        return method()

    def resolve(self):
        """Allocate the staged items in an explicit memory map.  Items staged with
        explicit addresses get priority."""
        #print(f"RESOLVE: {len(self._keepouts)} {len(self._explicits)} {len(self._entries)} {self.width} {self.vacant}")
        if self._resolved:
            return True
        for n in range(self._resolve_passes):
            self._resolve_pass(n)
        self._resolved = True
        return True

    def _resolve_pass_keepouts(self):
        # First pass, keepouts
        for n in range(len(self._keepouts)):
            ref, base, aw, _type, resolved = self._keepouts[n]
            # This is probably not useful, but maybe I'll find a use for keepouts with 'ref's?
            aw = self._resolve_ref(ref, aw)
            if resolved != self.RESOLVED:
                super().keepout(base, aw)
                self._keepouts[n] = (ref, base, aw, _type, self.RESOLVED)
        return

    def _resolve_pass_explicits(self):
        # Second pass, add any with explicit addresses
        for n in range(len(self._explicits)):
            data = self._explicits[n]
            if data is None:
                continue
            ref, base, aw, _type, resolved = data
            aw = self._resolve_ref(ref, aw)
            name = None
            if ref is not None:
                name = ref.name
            if resolved != self.RESOLVED:
                #print(f"{self.label}: Adding {name} to addr 0x{base:x}")
                super().add(aw, ref=ref, addr=base)
                self._explicits[n] = (ref, base, aw, _type, self.RESOLVED)
        return

    def _resolve_pass_else(self):
        # Third pass, add everything else
        for n in range(len(self._entries)):
            data = self._entries[n]
            if data is None:
                continue
            ref, base, aw, _type, resolved = data
            aw = self._resolve_ref(ref, aw)
            name = None
            if ref is not None:
                name = ref.name
            if resolved != self.RESOLVED:
                #print(f"{self.label}: Adding {name} ({aw} bits) to anywhere ({base})")
                newbase = super().add(aw, ref=ref, addr=None)
                self._entries[n] = (ref, newbase, aw, _type, self.RESOLVED)
        return

    def unstage(self):
        """Unstage everything so you can resolve() again (presumably after
        the memory map has been modified in some way)."""
        #print(f"{self.name} unstaging", end="")
        #print(f"{self.name} unstaging: {len(self._keepouts)} {len(self._explicits)} {len(self._entries)}")
        self.reset()
        lists = (self._keepouts, self._explicits, self._entries)
        #print(f" len(_list) = {len(_list)}", end="")
        for m in range(len(lists)):
            for n in range(len(lists[m])):
                x = lists[m][n]
                lists[m][n] = (x[0], x[1], x[2], x[3], self.UNRESOLVED)
        self._resolved = False
        return

    def shrink(self):
        if not self._resolved:
            self.resolve()
        return super().shrink()

    def get_entries(self):
        """Return a list of entries. Each entry is (start, end+1, ref) where 'ref' is applications-specific
        (e.g. a Python object reference, a string, None, etc).
        Before resolving, our staged entries don't generally have addresses, so this will mostly return
        (None, None, ref) but it's nice to have the same format as what it returns once resolved."""
        if self._resolved:
            return super().get_entries()
        entries = []
        for ref, base, aw, _type, state in self._explicits:
            entries.append((base, None, ref))
        for ref, base, aw, _type, state in self._entries:
            entries.append((base, None, ref))
        return entries


def test_Register():
    reg = Register(name="foo", dw=8, base=0x100, meta="some additional info", access=Register.RW)
    copy = reg.copy()
    for attr in dir(reg):
        if attr.startswith('__'):
            continue
        ra = getattr(reg, attr)
        ca = getattr(copy, attr)
        if callable(ra):
            continue
            #rv = ra()
            #cv = ca()
            #assert rv==cv, f"reg.{attr}() = {rv} != copy.{attr}() = {cv}"
        else:
            assert ra==ca, f"reg.{attr} = {ra} != copy.{attr} = {ca}"
    return


def test_MemoryRegion():
    mr = MemoryRegion(hierarchy=("top",))
    # Set some keep-out regions
    mr.keepout(0x100, width=8)
    widths = [0, 0, 0, 2, 2, 8, 4, 8, 0, 0, 0, 0, 1, 2]
    for w in widths:
        base = mr.add(w)
        print("Adding {} to 0x{:x}".format(w, base))
    mr.sort()
    # Add a few to specific addresses
    addr_widths = [(0x110, 4), (0x40, 4), (0x300, 8), (0x1001, 2)]
    for addr, w in addr_widths:
        try:
            base = mr.add(w, addr=addr)
            print("Adding {} to 0x{:x}".format(w, base))
        except Exception as e:
            print("EXCEPTION: " + str(e))
    # Create a second memory map
    submr = MemoryRegion(label="foo", hierarchy=("foo",))
    submr.add(0)
    submr.add(0)
    submr.add(4)
    submr.add(4)
    submr.add(6)
    # Create a third memory map
    subsubmr = MemoryRegion(label="bar", hierarchy=("bar",))
    subsubmr.add(10)
    subsubmr.shrink() # Shrink now that we're done adding
    # Nest the structure
    submr.add_item(subsubmr)
    submr.shrink() # Shrink now that we're done adding
    mr.add_item(submr)
    #print(mr)
    #mr.print(4)
    copymr = mr.copy()
    #print("==================== Deleting ====================")
    mr.remove(submr.base)
    #mr.print(4)
    #print("==================== The Copy ====================")
    #copymr.print(4)
    return

def test_MemoryRegionStager():
    mr = MemoryRegionStager(hierarchy=("top",))
    # Set some keep-out regions
    mr.keepout(0x100, width=8)
    widths = [0, 0, 0, 2, 2, 8, 4, 8, 0, 0, 0, 0, 1, 2]
    for w in widths:
        mr.add(w)
        print("Adding {} to staging area".format(w))
    #mr.sort()
    # Add a few to specific addresses
    addr_widths = [(0x40, 4), (0x300, 8)]
    for addr, w in addr_widths:
        try:
            base = mr.add(w, addr=addr)
            print("Adding {} to 0x{:x}".format(w, base))
        except Exception as e:
            print("EXCEPTION: " + str(e))
    # Create a second memory map
    submr = MemoryRegionStager(label="foo", hierarchy=("foo",))
    submr.add(0)
    submr.add(0)
    submr.add(4)
    submr.add(4)
    submr.add(6)
    # Create a third memory map
    subsubmr = MemoryRegionStager(label="bar", hierarchy=("bar",))
    subsubmr.add(10)
    # Nest the structure
    submr.add_item(subsubmr)
    mr.add_item(submr)
    mr.resolve()
    #print(mr)
    #mr.print(4)
    copymr = mr.copy()
    #print("==================== Deleting ====================")
    mr.remove(submr.base)
    #mr.print(4)
    #print("==================== The Copy ====================")
    #copymr.print(4)
    return

def doTests():
    fails = 0
    tests = (
        test_Register,
        test_MemoryRegion,
        test_MemoryRegionStager,
    )

    for test in tests:
        try:
            test()
        except Exception as err:
            print(err)
            fails += 1
    if fails == 0:
        print("PASS")
    else:
        print(f"FAIL: count = {fails}")
    return fails

if __name__ == "__main__":
    import sys
    sys.exit(doTests())
