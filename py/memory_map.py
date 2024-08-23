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

    def __init__(self, name=None, dw=1, base=None, meta=None, access=RW):
        self._name = name
        self._size = 1
        self._data_width = int(dw)
        self._addr_width = 0
        self._base_addr = base
        # A helpful bit of optional metadata
        self.meta = meta
        #self.access = int(access) & self._accessMask
        self.access = access

    def copy(self):
        return self.__class__(name=self._name, dw=self._data_width, base=self._base_addr,
                              meta=self.meta, access=self.access)

    @property
    def name(self):
        if self._name is None:
            return "Register_{}".format(size)
        return self._name

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
    def __init__(self, name=None, dw=1, aw=0, base=None, meta=None, access=Register.RW):
        super().__init__(name=name, dw=dw, base=base, meta=meta, access=access)
        self._size = 1 << int(aw)
        self._addr_width = int(aw)

    def copy(self):
        return self.__class__(name=self._name, dw=self._data_width, aw=self._addr_width,
                              base=self._base_addr, meta=self.meta, access=self.access)


class MemoryRegion():
    """A memory allocator.
    * Has no de-allocation.
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
        self._offset = addr_range[0]
        # -1 because the upper address is not inclusive
        self._aw = bits((addr_range[1]-addr_range[0])-1)
        # Its own memory map will be defined relative to the base (not absolute addresses)
        self._top = (1 << self._aw)
        # Each entry is (start, end+1, ref) where 'ref' is either None or a Python object reference
        self.map = []
        self.vacant = [list(addr_range)]
        self._keepout = []
        self.refs = []
        self._hierarchy = hierarchy
        if label is None:
            self.label = "MemoryRegion" + str(self._nregion)
            self._inc()
        else:
            self.label = label
        self._delta_indent = 0 # see self.print()
        # NOTE: self.bustop is an annoying application-specific hook and I'm being lazy.
        # If I end up with more of these, I'll just subclass it.
        self.bustop = False

    def copy(self):
        addr_range = (self._offset, self._top)
        mr = MemoryRegion(addr_range=addr_range, label=self.label, hierarchy=self._hierarchy)
        mr.map = self.map.copy()
        mr.vacant = self.vacant.copy()
        mr._keepout = self._keepout.copy()
        mr.refs = self.refs.copy()
        mr.bustop = self.bustop
        return mr

    def shrink(self):
        """Reduce address range to the minimum aligned range containing
        the occupied portions of the map.  Note that it only scales the
        upper bound.  The lower bound remains fixed.
        Note that this could cause problems if you try to add more items
        to the memory region after shrinking.  It should probably only
        be called after you're sure you're done adding entries."""
        hi_occupied = self.high_addr()
        min_aw = bits(hi_occupied-1)
        self._top = (1 << min_aw)
        self._aw = min_aw
        # Also need to truncate the last entry in the "vacant" map
        if len(self.vacant) > 0:
            vacant = (self.vacant[-1][0], self._top)
            if vacant[1] == vacant[0]:
                self.vacant.pop()
            else:
                self.vacant[-1] = (self.vacant[-1][0], self._top)
        return

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
    def base(self):
        return self._offset

    @property
    def top(self):
        return self._offset + self._top

    @base.setter
    def base(self, value):
        self._offset = value
        for n in range(len(self.map)):
            start, end, ref = self.map[n]
            if isinstance(ref, MemoryRegion):
                ref.base = value + start
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
            raise Exception("Adding element of size {} rooted at address 0x{:x}".format(size, addr) \
                    + "would exceed bounds of memory region [0x{:x}->0x{:x})".format(self.base, self.top))
        return True

    def __iter__(self):
        # We're an iterator now
        self.sort()
        self._im = 0
        self._iv = 0
        return self

    def __next__(self):
        mempty = False
        vempty = False
        if self._im < len(self.map):
            mem = self.map[self._im]
        else:
            mempty = True
        if self._iv < len(self.vacant):
            vac = self.vacant[self._iv]
            vac = (vac[0], vac[1], None) # Same shape as 'mem'
        else:
            vempty = True
        if mempty and vempty:
            raise StopIteration
        elif vempty:
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
        if self.hierarchy is not None:
            if hasattr(item, 'hierarchy'):
                item.hierarchy = (*self.hierarchy, *item.hierarchy)
        return self.add(width=width, ref=item, addr=addr)

    def add(self, width=0, ref=None, addr=None):
        base = self._add(width, ref=ref, addr=addr, type=self.TYPE_MEM)
        # If the item referenced by 'ref' has a 'base' attribute, update it
        if ref is not None and hasattr(ref, "base"):
            ref.base = base
        return base

    def keepout(self, addr, width=0):
        return self._add(width, ref=None, addr=addr, type=self.TYPE_KEEPOUT)

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
        # TODO DELETEME
        if (type == self.TYPE_MEM) and (base is not None) and (end is not None):
            self.refs.append((base, end, ref))
        return base

    def _insert(self, addr, width=0, type=TYPE_MEM, ref=None):
        """Add a memory element of address width 'width' to the memory map
        starting at address 'addr'.  Raises an exception if such an entry would
        overlap with existing elements or the bounds of the region."""
        self._vet_addr(addr, width)
        base = addr
        end = addr + (1<<width)
        fit_elem = None
        # First find whether 'addr' is within an occupied or vacant region
        for entry, _type in self: # Iterator magic
            e_base, e_end, e_ref = entry
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
            raise Exception("Could not fit [0x{:x}->0x{:x}) into memory map.".format(addr, end) \
                + " It probably overlaps with a keepout region.")
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
                self.vacant[n][1] = base
                if old_end > end:
                    # Add a new vacancy region above the occupied section
                    self.vacant.insert(n+1, [end, old_end])
            else:
                # Truncate upward the existing vacant region
                if old_end > end:
                    # Still some vacancy above the occupied section
                    self.vacant[n] = [end, old_end]
                else:
                    # We occupied the exact size of this vacant region
                    del self.vacant[n]
            # Add the memory region
            if type == self.TYPE_MEM:
                self.map.append((base, end, ref))
            elif type == self.TYPE_KEEPOUT:
                self._keepout.append((base, end))
            else:
                raise Exception("Invalid type {} to add to memory".format(type))
            break
        return base, end

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

    def sort(self):
        self.map.sort(key=lambda x: x[0])
        self.vacant.sort(key=lambda x: x[0])
        self.refs.sort(key=lambda x: x[0])
        return

    def __str__(self):
        return self.str()

    def __repr__(self):
        return self.__str__()

    def str(self, indent=0):
        ss = ["|{:^19s}|{:^19s}|".format("Used", "Free"),
              "|{0}|{0}|".format("-"*19)]
        empty = " "*19
        for entry, _type in self: # Iterator magic
            ref = entry[2]
            if ref is not None and isinstance(ref, MemoryRegion):
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
                elemstr = " {:8x}-{:8x} ".format(self.base + entry[0], self.base + entry[1])
                if _type == self.TYPE_MEM:
                    ordered = (elemstr, empty)
                else: # _type == self.TYPE_VACANT
                    ordered = (empty, elemstr)
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
        return self.map[-1][1]

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
        # print(f"  Nulling {nempty} entries. {self.hierarchy}")
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
        if len(common) == 0:
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
    def __init__(self, addr_range=(0, (1<<24)), label=None, hierarchy=None):
        super().__init__(addr_range=addr_range, label=label, hierarchy=hierarchy)
        # Each entry = (item, addr, addr_width, type)
        self._staged_items = []

    def add_item(self, item, offset=None, keep_base=False):
        """Overloaded to Stage-only"""
        addr_width = None
        if hasattr(item, 'aw'):
            addr_width = item.aw
        self._staged_items.append((item, offset, addr_width, self.TYPE_MEM))
        return

    def add(self, width=0, ref=None, addr=None):
        """Overloaded to Stage-only"""
        self._staged_items.append((ref, addr, width, self.TYPE_MEM))
        return

    def keepout(self, addr, width=0):
        """Overloaded to Stage-only"""
        self._staged_items.append((None, addr, width, self.TYPE_KEEPOUT))
        return

    def resolve(self):
        """Allocate the staged items in an explicit memory map.  Items staged with
        explicit addresses get priority."""
        # First pass, keepouts
        for n in range(len(self._staged_items)):
            ref, base, aw, _type = self._staged_items[n]
            if _type == self.TYPE_KEEPOUT:
                super().keepout(base, aw)
                self._staged_items[n] = None
        # Second pass, add any with explicit addresses
        for n in range(len(self._staged_items)):
            data = self._staged_items[n]
            if data is None:
                continue
            ref, base, aw, _type = data
            if _type == self.TYPE_MEM and base is not None:
                name = None
                if ref is not None:
                    name = ref.name
                print(f"Adding {name} to addr 0x{base:x}")
                super().add(aw, ref=ref, addr=base)
                self._staged_items[n] = None
        # Third pass, add everything else
        for n in range(len(self._staged_items)):
            data = self._staged_items[n]
            if data is None:
                continue
            ref, base, aw, _type = data
            if _type == self.TYPE_MEM:
                name = None
                if ref is not None:
                    name = ref.name
                print(f"Adding {name} to anywhere ({base})")
                super().add(aw, ref=ref, addr=base)
        self._staged_items = []
        return

class Addrspace():
    @staticmethod
    def _vet_ranges(*ranges):
        """Enforce three rules for memory ranges:
            0. range[0] < range[1]
            1. All boundaries must be powers-of-two
            2. Ranges must not overlap
        """
        rl = len(ranges)
        for n in range(rl):
            rng = ranges[n]
            # Rule 0
            low, high = rng
            if low >= high:
                raise Exception("Inverted or identical boundaries: (low, high) = ({}, {})".format(low, high))
                return False
            # Rule 1
            for boundary in rng:
                if (boundary != 0) and (math.log2(boundary) % 1) > 0:
                    raise Exception("Memory address range boundary 0x{:x} is not a power of two".format(boundary))
                    return False
            # Rule 2
            overlap = False
            if n < rl-1:
                for m in range(n+1, rl):
                    rng_cmp = ranges[m]
                    low_cmp, high_cmp = rng_cmp
                    # Ensure non-overlap
                    # if r0_low < r1_low, then r0_high must also be <= r1_low
                    # else (ro_low > r1_low), then r0_high must also be >= r1_low
                    if (low < low_cmp) != (high <= low_cmp):
                        overlap = True
                    elif (low >= high_cmp) != (high > high_cmp):
                        overlap = True
                    elif (low >= low_cmp) and (high <= high_cmp) :
                        overlap = True
                    elif (low_cmp >= low) and (high_cmp <= high) :
                        overlap = True
                    if overlap:
                        raise Exception("Memory regions (0x{:x}, 0x{:x}) and (0x{:x}, 0x{:x}) overlap".format(
                            low, high, low_cmp, high_cmp))
        return True

    def __init__(self, scalar_range=MEMORY_RANGE_SCALAR, mirror_range=MEMORY_RANGE_MIRROR, array_range=MEMORY_RANGE_ARRAY):
        #self.addr = numpy.empty((0, 2), dtype=int)
        self._vet_ranges(scalar_range, mirror_range, array_range)
        self.scalar_range = scalar_range
        self.mirror_range = mirror_range
        self.array_range = array_range
        self.mem_regions = {
            REGION_SCALAR: MemoryRegion(scalar_range),
            REGION_MIRROR: MemoryRegion(mirror_range),
            REGION_ARRAY:  MemoryRegion(array_range),
        }
        return

    def __str__(self):
        l = []
        for region, mr in self.mem_regions.items():
            if region == REGION_SCALAR:
                rstr = "REGION_SCALAR"
            elif region == REGION_MIRROR:
                rstr = "REGION_MIRROR"
            else:
                rstr = "REGION_ARRAY"
            l.append(rstr)
            l.append(str(mr))
            l.append("")
        return "\n".join(l)

    def __repr__(self):
        return self.__str__()

    def _add(self, reg, region=REGION_SCALAR, addr=None):
        """Add a memory region 'reg' (class Reg) to region 'region'.
        Finds the first empty slot with enough space that is aligned to the
        address width for optimum decoding."""
        return self.mem_regions[region].add(reg.addr_width, ref=reg, addr=addr)

    def sort(self):
        for n in range(len(self.mem_regions)):
            self.mem_regions[n].sort()
        return

    def get_region_mirror_size(self):
        mr = self.mem_regions[REGION_MIRROR]
        return mr.high_addr()-mr.base_addr()

    def get_region_array_size(self):
        mr = self.mem_regions[REGION_ARRAY]
        return mr.high_addr()-mr.base_addr()

    def get_region_scalar_size(self):
        mr = self.mem_regions[REGION_SCALAR]
        return mr.high_addr()-mr.base_addr()

    def add(self, reg, keep=False):
        if reg.addr_width > 0:
            region = REGION_ARRAY
        elif reg.access == ACCESS_R:
            region = REGION_SCALAR
        else:
            region = REGION_MIRROR
        addr = None
        reg_keep = reg.propdict.get('keep', False)
        if (keep or reg_keep) and (reg.base_addr is None):
            raise Exception("Cannot keep base_addr of None for reg {}".format(reg))
            addr = reg.base_addr
        return self._add(reg, region, addr=addr)

    def lastaddr(self):
        high_addr = 0
        for region, mr in self.mem_regions.items():
            addr = mr.high_addr()
            if addr > high_addr:
                high_addr = addr
        return high_addr

    def avoid(self, reg):
        base = reg.base_addr
        end = base + (1 << reg.addr_width)
        for _x, mr in self.mem_regions.items():
            region_base, region_end = mr.range
            if (base >= region_base) and (base < region_end):
                # It starts in this region
                mr.keepout(base, math.ceil(math.log2(min(end, region_end)-base)))
                if (end <= region_end):
                    print(f"0x{end:x} <= 0x{region_end:x}, break")
                    break
                else:
                    # It overlaps into the next region, continue
                    print(f"0x{end:x} > 0x{region_end:x}, continue")
                    base = region_end
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
    submr = MemoryRegion(label="foo")
    submr.add(0)
    submr.add(0)
    submr.add(4)
    submr.add(4)
    submr.add(6)
    # Create a third memory map
    subsubmr = MemoryRegion(label="bar")
    subsubmr.add(10)
    subsubmr.shrink() # Shrink now that we're done adding
    # Nest the structure
    submr.add_item(subsubmr)
    submr.shrink() # Shrink now that we're done adding
    mr.add_item(submr)
    #print(mr)
    mr.print(4)
    return

if __name__ == "__main__":
    test_MemoryRegion()
