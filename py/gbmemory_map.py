"""Ghostbus-specific elements of the tree representing the memory map of a Verilog design."""

from yoparse import getUnparsedWidthAndDepthRange, getUnparsedWidthRangeType, NetTypes
from memory_map import MemoryRegionStager, MemoryRegion, Register, Memory
from gbexception import GhostbusException

class GBRegister(Register):
    """This class expands on the Register class by including not just its
    resolved aw/dw, but also the unresolved strings used to declare aw/dw
    in the source code."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #self._rangeStr = None
        #self._depthstr = None
        self.range = (None, None)
        self.depth = ('0', '0')
        self.initval = 0
        self.strobe = False
        self.write_strobes = []
        self.read_strobes = []
        self.alias = None
        self.signed = None
        self.manually_assigned = False
        self.net_type = None
        self.busname = None

    def copy(self):
        ref = super().copy()
        ref.range = self.range
        ref.depth = self.depth
        ref.initval = self.initval
        ref.strobe = self.strobe
        ref.write_strobes = self.write_strobes
        ref.read_strobes = self.read_strobes
        ref.alias = self.alias
        ref.signed = self.signed
        ref.manually_assigned = self.manually_assigned
        ref.net_type = self.net_type
        ref.busname = self.busname
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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #self._rangeStr = None
        self._depthStr = None
        self.range = (None, None)
        self.depth = (None, None)
        self.alias = None
        self.signed = None
        self.manually_assigned = False
        self.busname = None
        # TODO - Is there any reason why this wouldn't be so? Maybe ROM?
        self.access = self.RW

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

    def copy(self):
        ref = super().copy()
        ref.range = self.range
        ref.depth = self.depth
        ref.alias = self.alias
        ref.signed = self.signed
        ref.manually_assigned = self.manually_assigned
        ref.busname = self.busname
        ref.access = self.access
        return ref


# I don't think this is needed anymore
class GBMemoryRegion(MemoryRegion):
    def __init__(self, addr_range=(0, (1<<24)), label=None, hierarchy=None):
        super().__init__(addr_range=addr_range, label=label, hierarchy=hierarchy)
        self.bustop = False # FIXME DEPRECATED
        self.declared_busses = ()
        self.implicit_busses = ()
        self.named_bus_insts = ()
        self.busname = None

    def copy(self):
        cp = super().copy()
        cp.bustop = self.bustop
        cp.declared_busses = self.declared_busses
        cp.implicit_busses = self.implicit_busses
        cp.named_bus_insts = self.named_bus_insts
        cp.busname = self.busname
        return cp


class GBMemoryRegionStager(MemoryRegionStager):
    def __init__(self, addr_range=(0, (1<<24)), label=None, hierarchy=None, domain=None):
        super().__init__(addr_range=addr_range, label=label, hierarchy=hierarchy)
        self.bustop = False
        self.declared_busses = ()
        self.implicit_busses = ()
        self.busname = None
        self.domain = domain
        # A pseudo-domain is one that looks like a bus domain top, but is actually
        # a branch of another domain's tree.
        # If 'pseudo_domain' is not None, it should be the name of an ExternalModule
        # declared in the same scope
        self.pseudo_domain = None
        self.toptag = False

    def copy(self):
        cp = super().copy()
        cp.bustop = self.bustop
        cp.declared_busses = self.declared_busses
        cp.implicit_busses = self.implicit_busses
        cp.busname = self.busname
        cp.domain = self.domain
        cp.pseudo_domain = self.pseudo_domain
        cp.toptag = self.toptag
        return cp


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
        self.busname = None
        self.manually_assigned = False
        if self.base is None:
            print(f"New external module: {name}; size = 0x{size:x}")
        else:
            self.manually_assigned = True
            print(f"New external module: {name}; size = 0x{size:x}; base = 0x{self.base:x}")
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


