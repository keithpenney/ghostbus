"""Ghostbus-specific elements of the tree representing the memory map of a Verilog design."""

import re

from yoparse import getUnparsedWidthAndDepthRange, getUnparsedWidthRangeType, NetTypes
from memory_map import MemoryRegionStager, MemoryRegion, Register, Memory, bits
from gbexception import GhostbusException
from policy import Policy
from util import check_consistent_offset

_DEBUG_PRINT=False
def printd(*args, **kwargs):
    if _DEBUG_PRINT:
        print(*args, **kwargs)

class GBRegister(Register):
    """This class expands on the Register class by including not just its
    resolved aw/dw, but also the unresolved strings used to declare aw/dw
    in the source code."""
    _attrs = {
        "range": (None, None),
        "depth": ('0', '0'),
        "initval": 0,
        "strobe": False,
        "write_strobes": [],
        "read_strobes": [],
        "alias": None,
        "signed": None,
        "manual_addr": None,
        "net_type": None,
        "domain": None,
        "genblock": None,
        "ref_list": [],
    }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #self._rangeStr = None
        #self._depthstr = None
        for name, default in self._attrs.items():
            if hasattr(default, "copy"):
                default = default.copy()
            setattr(self, name, default)
        # A bit weird, but helpful
        #self.ref_list.append(self)

    @property
    def busname(self):
        # TODO - elevate this to Exception and squash
        print("DEPRECATION WARNING! Stop using 'busname' in favor of 'domain'")
        return self.domain

    @busname.setter
    def busname(self, value):
        print("DEPRECATION WARNING! Stop using 'busname' in favor of 'domain'")
        self.domain = value
        return

    @property
    def base_list(self):
        ll = []
        for n in range(self.genblock.loop_len):
            ll.append(self.base + n*self.size)
        return ll

    def copy(self):
        ref = super().copy()
        for name, default in self._attrs.items():
            val = getattr(self, name)
            if hasattr(val, "copy"):
                val = val.copy()
            setattr(ref, name, val)
        if ref.access == ref.UNSPECIFIED:
            #raise Exception(f"copy of {self.name} with access {self.access} results in UNSPECIFIED ref!")
            print(f"copy of {self.name} with access {self.access} results in UNSPECIFIED ref!")
        return ref

    def _readRangeDepth(self):
        #if self._rangeStr is not None:
        #    return True
        if self.meta is None:
            return False
        _range, _net_type = getUnparsedWidthRangeType(self.meta)
        if _range is not None:
            # print(f"))))))))))))))))))))))) {self.name} self.range = {_range}")
            self.range = _range
            self.net_type = _net_type
            # Apply default access assumptions
            if self.access == self.UNSPECIFIED and _net_type is not None:
                if _net_type == NetTypes.reg:
                    self.access = self.RW
                elif _net_type in (NetTypes.wire, NetTypes.output, NetTypes.input):
                    self.access = self.READ
                else:
                    print(f"_net_type = {_net_type}")
            elif (self.access & self.WRITE):
                if _net_type == NetTypes.wire:
                    err = f"Cannot have write access to net {self.name} of 'wire' type." + \
                          f" See: {self.meta}"
                    # INVALID_ACCESS
                    raise GhostbusException(err)
            elif self.access == self.UNSPECIFIED:
                # Can't leave the access unspecified
                self.access = self.RW
                raise Exception(f"Can't leave the access unspecified: {self.name}")
            else:
                # print(f"What happened here? {self.accessToStr(self.access)} {ns}")
                pass
        else:
            raise Exception(f"Couldn't find _range of {self.name}")
            return False
        return True

    def _copyRangeDepth(self, register):
        """Copy the range, access, and net_type from GBRegister object 'register'"""
        self.range = register.range
        self.access = register.access
        self.net_type = register.net_type
        return

    @property
    def size_str(self):
        """Get the size of the register as an unpreprocessed string
        (preserving parameters and expressions in the source code).
        Also tries to make the result as friendly to read as possible."""
        r0, r1 = self.range
        if None in self.range:
            return "1"
        if r1 == "0":
            return f"({r0}+1)"
        return f"({r0}-{r1}+1)"

    def unroll(self):
        if self.genblock is None:
            return (self,)
        if not self.genblock.isFor():
            return (self,)
        copies = []
        base_list = self.base_list
        for n in range(len(base_list)):
            base = base_list[n]
            copy = self.copy()
            copy.base = base
            copy.name = f"{self.genblock.branch}_{self.name}_{n}"
            copies.append(copy)
        return copies


# TODO - Combine this class with GBRegister
class GBMemory(Memory):
    _attrs = {
        "_depthStr": None,
        "range": (None, None),
        "depth": (None, None),
        "alias": None,
        "signed": None,
        "manual_addr": None,
        "domain": None,
        "access": Memory.RW,
        "genblock": None,
        "ref_list": [],
        "block_aw": 0,
    }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #self._rangeStr = None
        for name, default in self._attrs.items():
            if hasattr(default, "copy"):
                default = default.copy()
            setattr(self, name, default)
        # A bit weird, but helpful
        #self.ref_list.append(self)

    @property
    def busname(self):
        # TODO - elevate this to Exception and squash
        print("DEPRECATION WARNING! Stop using 'busname' in favor of 'domain'")
        return self.domain

    @busname.setter
    def busname(self, value):
        print("DEPRECATION WARNING! Stop using 'busname' in favor of 'domain'")
        self.domain = value
        return

    @property
    def base_list(self):
        ll = []
        for n in range(self.genblock.loop_len):
            ll.append(self.base + n*self.size)
        return ll

    def copy(self):
        ref = super().copy()
        for name, default in self._attrs.items():
            val = getattr(self, name)
            if hasattr(val, "copy"):
                val = val.copy()
            setattr(ref, name, val)
        return ref

    def _readRangeDepth(self):
        #if self._rangeStr is not None:
        #    return True
        if self.meta is None:
            return False
        _pass = True
        _range, _depth = getUnparsedWidthAndDepthRange(self.meta)
        if _range is not None:
            self.range = _range
        else:
            _pass = False
        if _depth is not None:
            self.depth = _depth
        else:
            _pass = False
        return _pass

    def _copyRangeDepth(self, memory):
        """Copy the range, access, and net_type from GBMemory object 'memory'"""
        self.range = memory.range
        self.depth = memory.depth
        return

    @property
    def size_str(self):
        """Get the size of the register as an unpreprocessed string
        (preserving parameters and expressions in the source code).
        Also tries to make the result as friendly to read as possible."""
        r0, r1 = self.range
        if None in self.range:
            return "1"
        if r1 == "0":
            return f"({r0}+1)"
        return f"({r0}-{r1}+1)"

    @property
    def depth_str(self):
        """Get the depth of the register as an unpreprocessed string
        (preserving parameters and expressions in the source code).
        Also tries to make the result as friendly to read as possible."""
        d0, d1 = self.depth
        if None in self.depth:
            return "1"
        if d0 == "0":
            return f"({d1}+1)"
        return f"({d1}-{d0}+1)"

    # DELETEME - I'm trying to not use this anymore
    def unroll(self):
        if self.genblock is None:
            return (self,)
        if not self.genblock.isFor():
            return (self,)
        copies = []
        base_list = self.base_list
        for n in range(len(base_list)):
            base = base_list[n]
            copy = self.copy()
            copy.base = base
            copy.name = f"{self.genblock.branch}_{self.name}_{n}"
            copies.append(copy)
        return copies


class GBMemoryRegionStager(MemoryRegionStager):
    _attrs = {
        "bustop": False,
        "declared_busses": (),
        "implicit_busses": (),
        "_busname": None, # TODO Do I need this?
        "domain": None,
        # A pseudo-domain is one that looks like a bus domain top, but is actually
        # a branch of another domain's tree.
        # If 'pseudo_domain' is not None, it should be the name of an ExternalModule
        # declared in the same scope
        "pseudo_domain": None,
        "toptag": False,
        "genblock": None,
        # Keep track of anything instantiated within a generate block
        "_generates": [],
        "_explicit_generates": [],
    }
    def __init__(self, addr_range=(0, (1<<24)), label=None, hierarchy=None, domain=None):
        super().__init__(addr_range=addr_range, label=label, hierarchy=hierarchy)
        for name, default in self._attrs.items():
            if hasattr(default, "copy"):
                default = default.copy()
            setattr(self, name, default)
        self.domain = domain
        self.init()

    @property
    def busname(self):
        # TODO - elevate this to Exception and squash
        raise Exception("Aha! Caught you using GBMemoryRegionStager.busname!")
        return self._busname

    @busname.setter
    def busname(self, value):
        raise Exception("Aha! Caught you using GBMemoryRegionStager.busname!")
        self._busname = value
        return

    def copy(self):
        ref = super().copy()
        for name, default in self._attrs.items():
            val = getattr(self, name)
            if hasattr(val, "copy"):
                val = val.copy()
            setattr(ref, name, val)
        return ref

    def init(self):
        self._resolve_pass_methods = []
        self.add_resolve_pass(self._resolve_pass_keepouts)
        self.add_resolve_pass(self._resolve_pass_explicits)
        self.add_resolve_pass(self._resolve_pass_generates)
        self.add_resolve_pass(self._resolve_pass_else)
        self._resolve_passes = len(self._resolve_pass_methods)
        return

    def add(self, width=0, ref=None, addr=None):
        """Overloaded to stage Generate-For entries separately"""
        if hasattr(ref, "genblock") and isForLoop(ref.genblock):
            print(f"5550 adding {ref.name} which is in a for loop")
            if addr is not None:
                self._explicit_generates.append((ref, addr, width, self.TYPE_MEM, self.UNRESOLVED))
            else:
                self._generates.append((ref, addr, width, self.TYPE_MEM, self.UNRESOLVED))
            self._resolved = False
        else:
            print(f"5550 adding {ref.name} as usual")
            return super().add(width, ref, addr)
        return

    def _resolve_pass_generates(self):
        # Add generate instances in blocks of consistent offset
        todo = (self._explicit_generates, self._generates)
        if len(self._explicit_generates) + len(self._generates) > 0:
            print(f"555 _resolve_pass_generates {self.label}({self.domain}) {len(self._explicit_generates)} {len(self._generates)}")
        for genlist in todo:
            for m in range(len(genlist)):
                data = genlist[m]
                if data is None:
                    continue
                ref, base, aw, _type, resolved = data
                aw = self._resolve_ref(ref, aw)
                name = None
                if ref is not None:
                    name = ref.name
                unrolled_refs = ref.ref_list
                # Find N empty spaces with consistent offsets between them
                if ref.genblock.loop_len is None:
                    raise Exception(f"{ref.name} with {ref.genblock} has loop_len = None!")
                bases = self.get_base_list(ref.block_aw, ref.genblock.loop_len, start = base)
                print(f"    5551 {ref.name} aw = {ref.block_aw}; bases = {' '.join([hex(base) for base in bases])}, len(unrolled_refs) = {len(unrolled_refs)}")
                # Then add each entry as its own unrolled copy
                if resolved != self.RESOLVED:
                    for n in range(len(unrolled_refs)):
                        print(f"    5559 {self.label}: Adding {name} ({aw} bits) to (0x{bases[n]:x})")
                        #newbase = super(MemoryRegionStager, self).add(aw, ref=unrolled_refs[n], addr=bases[n])
                        newbase = self._base_add(ref.block_aw, ref=unrolled_refs[n], addr=bases[n])
                        if newbase != bases[n]:
                            raise GhostbusInternalException(f"Somehow failed to add ref to base 0x{base:x} and instead added it to 0x{newbase:x}")
                    genlist[m] = (ref, bases[0], aw, _type, self.RESOLVED)
                else:
                    print("    555a {self.label} {name}. why is this already resolved?")
        return

    def get_base_list(self, aw, num, start=0):
        """Get a list of available base addresses for 'num' entries of width 'aw'.
        The offset between adjacent base addresses is guaranteed consistent."""
        if start is None:
            start = 0
        size = 1<<aw
        if Policy.aligned_for_loops:
            full_aw = aw + bits(num-1)
            # Get the base address for a packed block of adjacent entries
            base = self.get_available_base(full_aw, start = start)
            ll = [base + n*size for n in range(num)]
            return ll
        else:
            # Start by finding the lowest address that fits one item of 'aw'
            found = False
            base = self.get_available_base(aw, start = start)
            nblocks_max = 10
            _ll = []
            while True:
                for nblocks in range(1, nblocks_max):
                    _ll = [base]
                    for n in range(num):
                        _ll.append(self.get_available_base(aw, start = _ll[-1] + nblocks*size))
                    if check_consistent_offset(_ll):
                        found = True
                        break
                if found:
                    break
            if found:
                return _ll
        return []


class ExternalModule():
    _attrs = {
        "signed": None,
        "name": None,
        "inst": None,
        "_ghostbus": None,
        "extbus": None,
        "_aw": None,
        "true_aw": None,
        "access": None,
        "READ": None,
        "WRITE": None,
        "RW": None,
        "domain": None,
        "_base": None,
        "sub_mr": None,
        "base_list": [],
        "_block_aw": None,
        "ref_list": [],
        "association": None,
    }
    def __init__(self, name, extbus, basename=None):
        for attr, default in self._attrs.items():
            if hasattr(default, "copy"):
                default = default.copy()
            setattr(self, attr, default)
        if basename is None:
            self.basename = name
        else:
            self.basename = basename
        size = 1<<extbus.aw
        self.name = name
        self.inst = name # alias
        self.extbus = extbus
        self._aw = self.extbus.aw # This is clobbered during resolution if the extmod is connected to a pseudo-domain
        self.true_aw = self.extbus.aw # This will always show the number of address bits as specified in the source
        self.access = self.extbus.access
        self.READ = self.extbus.READ
        self.WRITE = self.extbus.WRITE
        self.RW = self.extbus.RW
        if self.base is None:
            printd(f"New external module: {name}; size = 0x{size:x}")
        else:
            printd(f"New external module: {name}; size = 0x{size:x}; base = 0x{self.base:x}")
        self.base_list.append(self.base)
        # Clobber this for ExternalModule instances in generate loops so they have an easy reference
        # back to their rolled up parent instance (typically just the 0th instance)
        self.parent_ref = None

    def __str__(self):
        return f"ExternalModule: {self.name}"

    def copy(self):
        ref = self.__class__(name=self.name, extbus=self.extbus, basename=self.basename)
        for name, default in self._attrs.items():
            val = getattr(self, name)
            if hasattr(val, "copy"):
                val = val.copy()
            setattr(ref, name, val)
        # This one needs to be handled specially to avoid infinite recursion
        ref.parent_ref = self.parent_ref
        return ref

    @property
    def busname(self):
        # TODO - elevate this to Exception and squash
        print("DEPRECATION WARNING! Stop using 'busname' in favor of 'domain'")
        return self.domain

    @busname.setter
    def busname(self, value):
        print("DEPRECATION WARNING! Stop using 'busname' in favor of 'domain'")
        self.domain = value
        return

    @property
    def genblock(self):
        return self.extbus.genblock

    @property
    def ghostbus(self):
        return self._ghostbus

    @ghostbus.setter
    def ghostbus(self, ghostbus):
        self._ghostbus = ghostbus
        if self.extbus.aw > ghostbus.aw:
            serr = f"{self.name} external bus has greater address width {self.extbus['aw']}" + \
                   f" than the ghostbus {ghostbus['aw']}"
            # AW_CONFLICT
            raise GhostbusException(serr)
        if self.extbus.dw > ghostbus.dw:
            serr = f"{self.name} external bus has greater data width {self.extbus['dw']}" + \
                   f" than the ghostbus {ghostbus['dw']}"
            # DW_CONFLICT
            raise GhostbusException(serr)
        return

    def getDoutPort(self):
        return self.extbus['dout']

    def getDinPort(self):
        return self.extbus['din']

    @property
    def dw(self):
        return self.extbus.dw

    @property
    def aw(self):
        return self._aw

    @aw.setter
    def aw(self, val):
        self._aw = int(val)
        return

    @property
    def block_aw(self):
        if self._block_aw is None:
            return self.aw
        return self._block_aw

    @block_aw.setter
    def block_aw(self, val):
        self._block_aw = int(val)
        return

    @property
    def base(self):
        if self._base is None:
            return self.extbus.base
        return self._base

    @base.setter
    def base(self, val):
        self._base = val
        return

    def unroll(self):
        if self.genblock is None:
            return (self,)
        if not self.genblock.isFor():
            return (self,)
        copies = []
        base_list = self.base_list
        for n in range(len(base_list)):
            base = base_list[n]
            copy = self.copy()
            copy.base = base
            copy.name = f"{self.genblock.branch}_{self.name}_{n}"
            copies.append(copy)
        return copies


class GenerateBranch():
    TYPE_IF  = 0
    TYPE_FOR = 1
    def __init__(self, branch_name):
        self.branch = branch_name
        self._type = None

    def isFor(self):
        return self._type == self.TYPE_FOR

    def isIf(self):
        return self._type == self.TYPE_IF

class GenerateIf(GenerateBranch):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._type = self.TYPE_IF
        self.unrolled_size = "1"
        self.loop_range = "[0:0]"

    def __str__(self):
        return f"generate if (): {self.branch}"

class GenerateFor(GenerateBranch):
    OP_EQ = 0
    OP_NE = 1
    OP_GT = 2
    OP_GE = 3
    OP_LT = 4
    OP_LE = 5

    _op_dict = {
        '=':  OP_EQ,
        '!=': OP_NE,
        '>':  OP_GT,
        '>=': OP_GE,
        '<':  OP_LT,
        '<=': OP_LE,
    }

    INC_ADD = 0x10
    INC_SUB = 0x11
    INC_MUL = 0x12
    INC_DIV = 0x13

    _inc_dict = {
        '+': INC_ADD,
        '-': INC_SUB,
        '*': INC_MUL,
        '/': INC_DIV,
    }

    @classmethod
    def _parseOp(cls, ss):
        """Parse a '=', '!=', '<', '>', '<=', or '>=' into one of cls.OP_*"""
        op = cls._op_dict.get(ss.strip())
        if op is None:
            # UNPARSED_FOR_LOOP
            raise GhostbusException(f"Unknown boolean operator {ss}")
        return op

    @classmethod
    def _parseInc(cls, ss):
        """Parse '+val', '-val', '*val', or '/val' into (INC_*, val)"""
        ss = ss.strip()
        inc = cls._inc_dict.get(ss[0])
        if inc is None:
            # UNPARSED_FOR_LOOP
            raise GhostbusException(f"Unknown increment operator {ss}")
        val = ss[1:]
        return (inc, val)

    @staticmethod
    def _get_by_val(_dict, _val, default=None):
        for key, val in _dict.items():
            if val == _val:
                return key
        return default

    def __init__(self, branch_name, index, init, op, comp, inc):
        super().__init__(branch_name)
        self.index = index
        self.initial = init
        self.op = self._parseOp(op)
        self.comp = comp
        self.inc = self._parseInc(inc)
        self._type = self.TYPE_FOR
        self.unrolled_size = self._getUnrolledSizeStr()
        self.loop_range = f"[0:{self.unrolled_size}-1]"
        # This will get set by the resolution function Ghostbusser._resolveGenerates
        self.loop_len = None
        self._loop_index = 0

    def _getUnrolledSizeStr(self):
        """Try to divine the size of the unrolled loop using the strings parsed from the for loop
        (preserving parameters and expressions in the source code).
        Also tries to make the result as friendly to read as possible."""
        p1 = ""
        if self.op in (self.OP_GE, self.OP_LE):
            p1 = "+1"
        if self.inc[0] == self.INC_ADD:
            ss = f"{self.comp}"
            mm = f"-{self.initial}"
            if self.initial == "0":
                mm = ""
        elif self.inc[0] == self.INC_SUB:
            ss = f"{self.initial}"
            mm = f"-{self.comp}"
            if self.comp == "0":
                mm = ""
        if mm == "" and p1 == "":
            ss1 = ss
        else:
            ss1 = f"({ss}{mm}{p1})"
        ss2 = f"({ss1}/{self.inc[1]})"
        if self.inc[1] == "1":
            return ss1
        else:
            return ss2
        _inc_op_str = self._get_by_val(self._inc_dict, self.inc[0])
        # UNPARSED_FOR_LOOP
        raise GhostbusException("I don't know how to handle For-Loops with \"{_inc_op_str}\" in the loop eval.")

    def __str__(self):
        _op_str = self._get_by_val(self._op_dict, self.op)
        _inc_op_str = self._get_by_val(self._inc_dict, self.inc[0])
        _inc_val = self.inc[1]
        return f"for ({self.index}={self.initial}; {self.index}{_op_str}{self.comp}; {self.index}={self.index}{_inc_op_str}{_inc_val}): {self.branch}"

    def unrollRangeString(self, rangestr):
        #print(f"unrollRangeString: rangestr = {rangestr}")
        restr = "\[([^:]+):([^\]]+)\]"
        _match = re.match(restr, rangestr)
        loopsize = self.unrolled_size
        if _match:
            groups = _match.groups()
            #range = (groups[0], groups[1])
            rsize = f"({groups[0]}-{groups[1]}+1)"
            # [(FOO_COPIES*32)-1:0]
            unrolled = f"[({loopsize}*{rsize})-1:0]"
            #print(f"  returning: {unrolled}")
            return unrolled
        return rangestr

    def unrollRange(self, range):
        # TODO
        #print(f"unrollRange: range = {range}")
        return f"[range[0]:range[1]]"

def isForLoop(genblock):
    return (genblock is not None) and genblock.isFor()

def isIfBlock(genblock):
    return (genblock is not None) and genblock.isIf()

def test_GenerateFor():
    dd = (
        # ((branch_name, index, init, op, comp, inc), (unrolled_size, ...)
        (("branch", "N", "0", "<", "SIZE", "+1"),       ("SIZE",)),
        (("branch", "N", "0", "<=", "SIZE", "+1"),      ("(SIZE+1)",)),
        (("branch", "N", "SIZE", ">", "0", "-1"),       ("SIZE",)),
        (("branch", "N", "SIZE", ">=", "0", "-1"),      ("(SIZE+1)",)),
        (("branch", "N", "SIZE-1", ">=", "0", "-1"),    ("(SIZE-1+1)",)),
        (("branch", "N", "START", "<", "SIZE", "+1"),   ("(SIZE-START)",)),
        (("branch", "N", "START", "<=", "SIZE", "+1"),  ("(SIZE-START+1)",)),
        (("branch", "N", "START", "<", "SIZE", "+2"),   ("((SIZE-START)/2)",)),
        (("branch", "N", "START", "<=", "SIZE", "+2"),  ("((SIZE-START+1)/2)",)),
        (("branch", "N", "START", ">", "SIZE", "-1"),   ("(START-SIZE)",)),
        (("branch", "N", "START", ">=", "SIZE", "-1"),  ("(START-SIZE+1)",)),
        (("branch", "N", "START", ">", "SIZE", "-2"),   ("((START-SIZE)/2)",)),
        (("branch", "N", "START", ">=", "SIZE", "-2"),  ("((START-SIZE+1)/2)",)),
    )
    fail = False
    for params, results in dd:
        gf = GenerateFor(*params)
        unrolled_size = results[0]
        if gf.unrolled_size != unrolled_size:
            fail = True
            print(f"  {gf}: {gf.unrolled_size} != {unrolled_size}")
    if fail:
        return 1
    return 0

def doTests():
    tests = (
        test_GenerateFor,
    )
    fails = 0
    for test in tests:
        rval = test()
        if rval != 0:
            fails += 1
    if fails > 0:
        print(f"FAIL: {fails}/{len(tests)} failed.")
        return 1
    print("PASS")
    return 0

if __name__ == "__main__":
    exit(doTests())
