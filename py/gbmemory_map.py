"""Ghostbus-specific elements of the tree representing the memory map of a Verilog design."""

from yoparse import getUnparsedWidthAndDepthRange, getUnparsedWidthRangeType, NetTypes
from memory_map import MemoryRegionStager, MemoryRegion, Register, Memory
from gbexception import GhostbusException

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
        # TODO - Can I get rid of "manually_assigned"?
        "manually_assigned": False,
        "manual_addr": None,
        "net_type": None,
        "busname": None,
        "genblock": None,
    }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #self._rangeStr = None
        #self._depthstr = None
        for name, default in self._attrs.items():
            if hasattr(default, "copy"):
                default = default.copy()
            setattr(self, name, default)

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


# TODO - Combine this class with GBRegister
class GBMemory(Memory):
    _attrs = {
        "_depthStr": None,
        "range": (None, None),
        "depth": (None, None),
        "alias": None,
        "signed": None,
        # TODO - Can I get rid of "manually_assigned"?
        "manually_assigned": False,
        "manual_addr": None,
        "busname": None,
        "access": Memory.RW,
        "genblock": None,
    }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #self._rangeStr = None
        for name, default in self._attrs.items():
            if hasattr(default, "copy"):
                default = default.copy()
            setattr(self, name, default)

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


class GBMemoryRegionStager(MemoryRegionStager):
    _attrs = {
        "bustop": False,
        "declared_busses": (),
        "implicit_busses": (),
        "busname": None,
        "domain": None,
        # A pseudo-domain is one that looks like a bus domain top, but is actually
        # a branch of another domain's tree.
        # If 'pseudo_domain' is not None, it should be the name of an ExternalModule
        # declared in the same scope
        "pseudo_domain": None,
        "toptag": False,
        "genblock": None,
    }
    def __init__(self, addr_range=(0, (1<<24)), label=None, hierarchy=None, domain=None):
        super().__init__(addr_range=addr_range, label=label, hierarchy=hierarchy)
        for name, default in self._attrs.items():
            if hasattr(default, "copy"):
                default = default.copy()
            setattr(self, name, default)
        self.domain = domain

    def copy(self):
        ref = super().copy()
        for name, default in self._attrs.items():
            val = getattr(self, name)
            if hasattr(val, "copy"):
                val = val.copy()
            setattr(ref, name, val)
        return ref


class ExternalModule():
    def __init__(self, name, ghostbus, extbus):
        size = 1<<extbus.aw
        if extbus.aw > ghostbus.aw:
            serr = f"{name} external bus has greater address width {extbus['aw']}" + \
                   f" than the ghostbus {ghostbus['aw']}"
            raise GhostbusException(serr)
        if extbus.dw > ghostbus.dw:
            serr = f"{name} external bus has greater data width {extbus['dw']}" + \
                   f" than the ghostbus {ghostbus['dw']}"
            raise GhostbusException(serr)
        self.signed = None
        self.name = name
        self.inst = name # alias
        self.ghostbus = ghostbus
        self.extbus = extbus
        self._aw = self.extbus.aw # This is clobbered during resolution if the extmod is connected to a pseudo-domain
        self.true_aw = self.extbus.aw # This will always show the number of address bits as specified in the source
        self.access = self.extbus.access
        self.READ = self.extbus.READ
        self.WRITE = self.extbus.WRITE
        self.RW = self.extbus.RW
        self.busname = None
        self.manually_assigned = False
        if self.base is None:
            printd(f"New external module: {name}; size = 0x{size:x}")
        else:
            self.manually_assigned = True
            printd(f"New external module: {name}; size = 0x{size:x}; base = 0x{self.base:x}")
        # New additions for the 'stepchild' feature
        self.sub_bus = None
        self.sub_mr = None

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
        self._aw = val
        return

    @property
    def base(self):
        return self.extbus.base

    @base.setter
    def base(self, ignore_val):
        # Ignoring this. Can only set via the bus
        # Need a setter here for reasons...
        return


class GenerateBranch():
    TYPE_IF  = 0
    TYPE_FOR = 1
    def __init__(self, branch_name):
        self.branch = branch_name
        self.type = None

class GenerateIf(GenerateBranch):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.type = self.TYPE_IF

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
            raise GhostbusException(f"Unknown boolean operator {ss}")
        return op

    @classmethod
    def _parseInc(cls, ss):
        """Parse '+val', '-val', '*val', or '/val' into (INC_*, val)"""
        ss = ss.strip()
        inc = cls._inc_dict.get(ss[0])
        if inc is None:
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
        self.type = self.TYPE_FOR

    def __str__(self):
        _op_str = self._get_by_val(self._op_dict, self.op)
        _inc_op_str = self._get_by_val(self._inc_dict, self.inc[0])
        _inc_val = self.inc[1]
        return f"for ({self.index}={self.initial}; {self.index}{_op_str}{self.comp}; {self.index}={self.index}{_inc_op_str}{_inc_val}): {self.branch}"
