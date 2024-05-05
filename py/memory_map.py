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


class Register():
    def __init__(self, name=None, dw=1, aw=0):
        self._name = name
        self._size = 1 << int(aw)
        self._width = int(dw)

    def name(self):
        if self._name is None:
            return "Register_{}".format(size)

    def size(self):
        return self._size

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

    def __init__(self, addr_range=(0, (1<<24)), label = None):
        self.range = addr_range
        # Each entry is (start, end+1)
        self.map = []
        self.vacant = [list(addr_range)]
        self._keepout = []
        self.refs = []
        if label is None:
            self.label = "MemoryRegion" + str(self._nregion)
            self._inc()
        else:
            self.label = label

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
        if addr + size > self.range[1]:
            raise Exception("Adding element of size {} rooted at address 0x{:x}".format(size, addr) \
                    + "would exceed bounds of memory region [0x{:x}->0x{:x})".format(*self.range))
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

    def add(self, width=0, ref=None, addr=None):
        return self._add(width, ref=ref, addr=addr, type=self.TYPE_MEM)

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
            base, end = self._push(width)
        else:
            base, end = self._insert(addr, width, type=type)
        if (type == self.TYPE_MEM) and (base is not None) and (end is not None):
            self.refs.append((base, end, ref))
        return base

    def _insert(self, addr, width=0, type=TYPE_MEM):
        """Add a memory element of address width 'width' to the memory map
        starting at address 'addr'.  Raises an exception if such an entry would
        overlap with existing elements or the bounds of the region."""
        self._vet_addr(addr, width)
        base = addr
        end = addr + (1<<width)
        fit_elem = None
        # First find whether 'addr' is within an occupied or vacant region
        for entry, _type in self: # Iterator magic
            e_base, e_end = entry
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
                    fit_elem = entry
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
                self.map.append((base, end))
            elif type == self.TYPE_KEEPOUT:
                self._keepout.append((base, end))
            else:
                raise Exception("Invalid type {} to add to memory".format(type))
            break
        return base, end

    def _push(self, width=0):
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
                self.map.append((aligned_start, mem_end))
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
        ss = ["|{:^19s}|{:^19s}|".format("Used", "Free"),
              "|{0}|{0}|".format("-"*19)]
        empty = " "*19
        for entry, _type in self: # Iterator magic
            elemstr = " {:8x}-{:8x} ".format(*entry)
            if _type == self.TYPE_MEM:
                ordered = (elemstr, empty)
            else: # _type == self.TYPE_VACANT
                ordered = (empty, elemstr)
            ss.append("|{}|{}|".format(*ordered))
        return "\n".join(ss)

    def __repr__(self):
        return self.__str__()

    def high_addr(self):
        """Return the highest occupied address + 1."""
        self.sort()
        return self.map[-1][1]

    def base_addr(self):
        """Return the base address of the memory region"""
        return self.range[0]


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

