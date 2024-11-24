# Ghostbus localbus-style decoder logic

import os

from memory_map import Register, MemoryRegion, bits
from gbexception import GhostbusException, GhostbusFeatureRequest
from gbmemory_map import GBMemoryRegionStager, GBRegister, GBMemory, ExternalModule, isForLoop
from util import strDict, check_complete_indices
from yoparse import block_inst


def vhex(num, width):
    """Verilog hex constant generator"""
    fmt = "{{:0{}x}}".format(width>>2)
    return "{}'h{}".format(width, fmt.format(num))


class BusLB():
    # Boolean aliases for clarity
    mandatory = True
    optional = False
    # Directions (host-centric)
    _input = 0
    _output = 1
    _inout = 2
    _clk = 3
    _bus_info = {
        # dict key: ((alternate names), mandatory?, port direction)
        "clk":      ((), mandatory, _clk),
        "addr":     ((), mandatory, _output),
        "din":      (("rdata",),  optional, _input),
        "dout":     (("wdata",), optional, _output),
        "we":       (("wen",), optional, _output),
        "re":       (("ren",), optional, _output),
        "wstb":     (("write_strobe", "wstrb"), optional, _output),
        "rstb":     (("read_strobe", "rstrb"), optional, _output),
    }
    _port_dict = {key: "GBPORT_{}".format(key) for key in _bus_info.keys()}
    # Make a map of alias-to-value
    _alias_map = {}
    for key, data in _bus_info.items():
        # Include the 'default' keys (non-alias)
        _alias_map[key] = key
        for alias in data[0]:
            # Add the alias keys as well
            _alias_map[alias] = key
    # A list of aliases for convenience
    _alias_keys = [key for key in _alias_map.keys()]
    # Derived parameters
    _derived = {
        # Parameter: ports that need to agree
        'aw': ("addr",),
        'dw': ("din", "dout"),
    }
    # Access encoding shared from Register
    READ = Register.READ
    WRITE = Register.WRITE
    RW = Register.RW

    @classmethod
    def allowed_portname(cls, name):
        if name in cls._alias_keys:
            return True
        if cls._matchExtra(name) is not None:
            return True
        return False

    @classmethod
    def direction_string_host(cls, dir):
        dd = {
            cls._input: "input",
            cls._output: "output",
            cls._inout: "inout",
            cls._clk: "input",
        }
        return dd.get(dir, "UNKNOWN")

    @classmethod
    def direction_string_periph(cls, dir):
        dd = {
            cls._input: "output",
            cls._output: "input",
            cls._inout: "inout",
            cls._clk: "input",
        }
        return dd.get(dir, "UNKNOWN")

    def __init__(self, name=None):
        self._name = name
        self._bus = {}
        for key, data in self._bus_info.items():
            self._bus[key] = None
        # Add derived parameters
        # FIXME - Can we stop storing things in self._bus that aren't actual ports?!
        for key in self._derived.keys():
            self._bus[key] = None
        # A few more bespoke parameters (see self._set_width)
        self._bus['aw_str'] = None
        self._bus['dw_str'] = None
        # Is this a fully-defined bus? See self.validate
        self._valid = False
        self._base = None
        self._sub = None
        self.alias = None # TODO Is this even used?
        # 'extmod_name' is used for pseudo-bus domains which are associated with an extmod
        # declared in the same module
        self.extmod_name = None
        self._port_list = None

    @property
    def sub(self):
        return self._sub

    @sub.setter
    def sub(self, val):
        self._sub = val
        return

    def __str__(self):
        return strDict(self._bus)

    def __repr__(self):
        return self.__str__()

    def _get_by_direction(self, _dirs):
        dd = {}
        for key, data in self._bus_info.items():
            if data[2] in _dirs:
                if self._bus[key] is not None:
                    dd[key] = self._bus[key][0]
                else:
                    dd[key] = None
        return dd

    def getPortDict(self):
        return self._port_dict

    def getPortList(self):
        if self._port_list is not None:
            return self._port_list
        # (name, rangestr, dir)
        ll = []
        # I'd like to return the ports in some preferred order
        preferred_order = ('clk', 'addr', 'dout', 'din', 'we', 'wstb', 're', 'rstb')
        for key, portinfo in self._bus_info.items():
            portname = self._bus.get(key)
            if portname is not None:
                portname = portname[0]
                _dir = portinfo[2]
                rangestr = ""
                if key == "addr":
                    aw_range = self._bus.get("aw_range")
                    if aw_range is None:
                        aw_range = f"[{self.aw-1}:0]"
                    else:
                        rr = aw_range[0]
                        aw_range = f"[{rr[0]}:{rr[1]}]"
                    rangestr = aw_range
                elif key in ("dout", "din"):
                    dw_range = self._bus.get("dw_range")
                    if dw_range is None:
                        dw_range = f"[{self.dw-1}:0]"
                    else:
                        rr = dw_range[0]
                        dw_range = f"[{rr[0]}:{rr[1]}]"
                    rangestr = dw_range
                # (order, name, rangestr, dir)
                if key in preferred_order:
                    order = preferred_order.index(key)
                else:
                    order = len(preferred_order)
                ll.append((order, key, portname, rangestr, _dir))
        # Sort by preferred order index
        ll.sort(key=lambda x: x[0])
        # Discard the order index
        ll = [(x[1], x[2], x[3], x[4]) for x in ll]
        # Store the result for future calls
        self._port_list = ll
        return ll

    @property
    def name(self):
        return self._name

    @property
    def base(self):
        return self._base

    @base.setter
    def base(self, _base):
        if self._base is not None and _base != self._base:
            # MULTIPLE_ADDRESSES
            raise GhostbusException("Multiple explicit addresses set for bus.")
        self._base = _base
        return

    @property
    def access(self):
        acc = 0
        if self._bus["din"] is not None:
            acc |= self.READ
        if self._bus["dout"] is not None:
            acc |= self.WRITE
        return acc

    def inputs(self):
        return self._get_by_direction((self._input,))

    def outputs(self):
        return self._get_by_direction((self._output,))

    def outputs_and_clock(self):
        return self._get_by_direction((self._output, self._clk))

    def get_range(self, portname):
        for key, value in self._derived.items():
            if portname in value:
                _range = self._bus.get(key+"_range", None)
                if _range is not None:
                    return _range[0]
        return None

    def get_width(self, portname):
        for key, value in self._derived.items():
            if portname in value:
                return self._bus.get(key+"_str")[0]
        return 1

    def __getitem__(self, key):
        item = self._bus.__getitem__(key)
        if item is not None:
            return self._bus.__getitem__(key)[0]
        return None

    def get_source(self, key):
        return self._bus.__getitem__(key)[1]

    @property
    def aw(self):
        _aw = self._bus['aw']
        if _aw is not None:
            return _aw[0]
        return None

    @property
    def dw(self):
        _dw = self._bus['dw']
        if _dw is not None:
            return _dw[0]
        return None

    @classmethod
    def _matchExtra(cls, name):
        import re
        re_in = "extra_(in|input)(\d+)?"
        re_out = "extra_(out|output)(\d+)?"
        _match = re.match(re_in, name)
        if _match:
            index = _match.groups()[1]
            if index is None or len(index) == 0:
                index = 0
            else:
                index = int(index)
            portname = f"extra_in{index:d}"
            return (cls._input, portname)
        _match = re.match(re_out, name)
        if _match:
            index = _match.groups()[1]
            if index is None or len(index) == 0:
                index = 0
            else:
                index = int(index)
            portname = f"extra_out{index:d}"
            return (cls._output, portname)
        return None

    def _validate_portname(self, name):
        if name not in self._alias_keys:
            err = "Invalid value ({}) for attribute 'ghostbus_port'.".format(name) + \
                  "  Valid values are {}".format(self._alias_keys)
            raise GhostbusException(err)
        return self._alias_map[name]

    def set_port(self, portname, netname, portwidth=1, rangestr=None, source=None):
        # Check for "extra" ports
        _match = self._matchExtra(portname)
        if _match is not None:
            _dir, portname = _match
            busval = self._bus.get(portname)
            # Register the direction in _bus_info
            self._bus_info[portname] = ((), self.optional, _dir)
        else:
            portname = self._validate_portname(portname)
            busval = self._bus[portname]
        if busval is None:
            self._bus[portname] = (netname, source)
            # Get width of addr/data
            self._set_width(portname, width=portwidth, rangestr=rangestr)
        else:
            if source != busval[1]:
                raise GhostbusException("'ghostbus_port={}' defined at {} is already defined at {}".format(
                    busval[0].strip().lower(), source, busval[1]))
            else:
                raise GhostbusFeatureRequest("Name-mangle a named bus if declared in a module that is instantiated more than once.")
        return

    def _set_width(self, name, width=1, rangestr=None):
        for wparam, ports in self._derived.items():
            if name in ports:
                existing = self._bus[wparam]
                if existing is not None and existing[0] != width:
                    raise GhostbusException(f"Ghostbus ports ({ports}) must all be the same width.")
                self._bus[wparam] = (width, None)
                if rangestr is not None:
                    self._bus[wparam+"_range"] = (rangestr, None)
                    self._bus[wparam+"_str"] = (rangestr[0] + "+1", None)
        return

    def validate(self):
        _valid = True
        err = ""
        missing = []
        for key, data in self._bus_info.items():
            mandatory = data[1]
            if mandatory and self._bus[key] is None:
                missing.append(key)
                _valid = False
        if not _valid:
            err = f"Bus {self.name} is missing mandatory ports: "
            err += " ".join(missing)
            return _valid, err
        # Ensure we have at least one of 'wdata' or 'rdata'
        # First, check for 'wdata' ('dout')
        if self._bus['dout'] is not None:
            # If we have a 'dout', we need a 'we'
            if self._bus['we'] is None:
                err = f"Bus {self.name} has a wdata port but no write-enable"
                _valid = False
        elif self._bus['din'] is None:
            err = f"Bus {self.name} has no data ports (neither wdata nor rdata)"
            _valid = False
        self._valid = _valid
        return _valid, err

    def get(self):
        """Get a copy of the bus dict without the 'source' references"""
        _valid, err = self.validate()
        if not _valid:
            serr = "Incomplete bus definition: " + err
            raise GhostbusException(serr)
        dd = {}
        for key, val in self._bus.items():
            if val is not None:
                dd[key] = val[0] # Discarding the "source" part
            else:
                dd[key] = None
        return dd

def createPortBus(busses):
    """The singular port bus defines the names and sizes of the ports used to let the ghostbus into a module.
    When multiple busses exist, this bus should have the union of their ports (i.e. all their ports combined
    with duplicates removed).  Then each bus can hookup to the ports it needs and ignore the others."""
    # Iterate through the busses, collecting port keys and widths (ensuring widths agree)
    portkeys = []
    aw = None
    awbusname = None
    dw = None
    dwbusname = None
    ignores = [key for key in BusLB._derived.keys()]
    ignores.append("aw_str")
    ignores.append("aw_range")
    ignores.append("dw_str")
    ignores.append("dw_range")
    for bus in busses:
        for key, portname in bus.get().items():
            if key in ignores:
                continue
            if key not in portkeys:
                portkeys.append(key)
            if key == "addr":
                if aw is None:
                    aw = bus.aw
                    awbusname = bus.name
                else:
                    if aw != bus.aw:
                        raise Exception(f"Busses {bus.name} and {awbusname} have different address widths ({bus.aw} and {aw}).")
            elif key in ("din", "dout"):
                if dw is None:
                    dw = bus.dw
                    dwbusname = bus.name
                else:
                    if dw != bus.dw:
                        raise Exception(f"Busses {bus.name} and {dwbusname} have different data widths ({bus.dw} and {dw}).")
    if aw is None or dw is None:
        raise Exception("createPortBus somehow managed to not find 'aw' and 'dw' in the busses")
    # Create the bus
    portbus = BusLB("ports")
    for key in portkeys:
        if key == "addr":
            portwidth = aw
        elif key in ("din", "dout"):
            portwidth = dw
        else:
            portwidth = 1
        # TODO - Replace this someday with a global NetNamer class which guarantees name collision avoidance
        # Look for 'wstb+wen' dual role
        netname = "GBPORT_" + key
        portbus.set_port(key, netname, portwidth=portwidth, rangestr=None, source=None)
    return portbus

#   The "DecoderDomainLB.submods" list needs to only contain submodules in its domain because of din routing.
#   Also, DecoderLB functions as both a module and a submodule, and so has both an "outside" API and an "inside" API
#   We just need to ensure that the generated code from all the DecoderDomainLB instances is collected and exposed
#   via the "inside" API while the "outside" API is singular (one-domain always).

class DecoderLB():
    def __init__(self, memorytree, ghostbusses, gbportbus):
        self.domains = {}
        self.ghostbusses = {bus.name: bus for bus in ghostbusses}
        self.GhostbusPortBus = gbportbus
        self.parent_domain = memorytree.parent_domain
        self._def_file = "defs.vh" # TODO - harmonize with DecoderDomainLB()
        self.genblock = memorytree.genblock
        self.gen_addrs = {}
        for memregion in memorytree.memories:
            domain = memregion.domain
            self.domains[domain] = DecoderDomainLB(self, memregion, ghostbusses, gbportbus)
        # Recall that from every module's perspective, the domain in which it is
        # instantiated (in its parent module) is default ("None")
        self.parent_domain_decoder = self.domains[None]
        # Keep track of instance name within the parent's scope
        self.inst = self.parent_domain_decoder.inst
        # As well as the module name it represents
        self.name = self.parent_domain_decoder.name
        for key, node in memorytree.items():
            # Get the domain that the node is instantiated in
            domain = node.parent_domain
            # Also get the 'start' address. The only place it's used is in submodsTopInit(), which gives it to submodInitStr()
            # so this 'start' address is the relative address in 'domain' in which this submodule is rooted.
            # We need to get the GBMemoryRegion that is the same domain as 'node.parent_domain', then loop through
            # the parent's memory associated with this domain until we find a reference to the exact same object
            target = node.get_memory_by_domain(None) # It has to be the default domain here
            if target is None:
                print(f"Ignoring non-ghostbus module {node.label}")
                continue
            parent_mem = memorytree.get_memory_by_domain(domain)
            if parent_mem is None:
                raise Exception(f"Failed to find memory by domain {domain} in {memorytree}")
            start = None
            for _start, _stop, ref in parent_mem.get_entries():
                if ref == target:
                    start = _start
                    break
            if start is None:
                raise Exception(f"Failed to find start address for {key}, {node.label}")
            submod = self.__class__(node, ghostbusses, self.GhostbusPortBus)
            self._handleSubmod(submod, domain, start)
        for domain, decoder in self.domains.items():
            decoder._resolveSubmods()

    def _handleSubmod(self, submod, domain, start_addr):
        if hasattr(submod, "genblock") and submod.genblock is not None:
            if isForLoop(submod.genblock):
                print(f"DecoderDomainLB {submod.inst} is instantiated within generate-FOR block {submod.genblock.branch}")
                self.domains[domain].add_block_submod(submod.genblock.branch, submod, start_addr)
                # We'll handle these later
                return
            else:
                print(f"DecoderDomainLB {submod.inst} is instantiated within generate-IF block {submod.genblock.branch}")
                # Generate-if, just strip the branch name from the submod name
                #gen_branch, instname, gen_index = block_inst(submod.inst)
                #submod.setInst(instname)
        self.domains[domain].add_submod(submod, start_addr)
        return

    def _clearDef(self, dest_dir):
        """Start with empty macro definitions file"""
        fd = open(os.path.join(dest_dir, self._def_file), "w")
        fd.close()
        return

    @staticmethod
    def _logDef(suffix):
        # Weird, akward, ugly
        DecoderDomainLB._defs.append(suffix)
        return

    def _addDef(self, dest_dir, macrostr, macrodef):
        defstr = f"`define {macrostr} {macrodef}\n"
        with open(os.path.join(dest_dir, self._def_file), "a") as fd:
            fd.write(defstr)
        return

    def setInst(self, instname):
        self.inst = instname
        for domain, decoder in self.domains.items():
            decoder.inst = instname
        return

    def _addGhostbusDef(self, dest_dir, suffix):
        #if self._isDefd(suffix):
        #    return
        macrostr = f"GHOSTBUS_{suffix}"
        macrodef = f"`include \"ghostbus_{suffix}.vh\""
        self._logDef(suffix)
        return self._addDef(dest_dir, macrostr, macrodef)

    def GhostbusMagic(self, dest_dir="_auto"):
        self._clearDef(dest_dir)
        for domain, decoder in self.domains.items():
            decoder.GhostbusMagic(dest_dir)
        return

    def _collectCSRs(self, csrlist):
        # optional, only used for testbench magic
        for domain, decoder in self.domains.items():
            decoder._collectCSRs(csrlist)
        return

    def _collectRAMs(self, ramlist):
        # optional, only used for testbench magic
        for domain, decoder in self.domains.items():
            decoder._collectRAMs(ramlist)
        return

    def submodInitStr(self, base_rel, parent):
        # the declaration of ports that get hooked up in GhostbusSubmodMap
        return self.parent_domain_decoder.submodInitStr(base_rel, parent)

    def _WriteGhostbusSubmodMap(self, dest_dir, parentname):
        return self.parent_domain_decoder._WriteGhostbusSubmodMap(dest_dir, parentname)

    def _GhostbusDoSubmods(self, dest_dir):
        # First, generate own internal bus decoding code in all domains
        decode = self._GhostbusDecoding()
        fname = f"ghostbus_{self.name}.vh"
        with open(os.path.join(dest_dir, fname), "w") as fd:
            fd.write(decode)
            print(f"Wrote to {fname}")
        self.parent_domain_decoder._addGhostbusDef(dest_dir, self.name)
        # Then, generate decoding logic for each block scope
        block_decode = self._GhostbusBlockDecoding()
        for branch, decode in block_decode.items():
            fname = f"ghostbus_{self.name}_{branch}.vh"
            with open(os.path.join(dest_dir, fname), "w") as fd:
                fd.write(decode)
                print(f"Wrote to {fname}")
                self.parent_domain_decoder._addGhostbusDef(dest_dir, f"{self.name}_{branch}")
        # Then generate instantiation code for any children in their appropriate domains
        for domain, decoder in self.domains.items():
            if domain in decoder.mod.declared_busses:
                # If this submodule's bus (domain) is declared in my scope, I need to use the
                # net names in the codebase
                parentbus = self.ghostbusses[domain]
            else:
                # Otherwise, the bus comes in from ports with global (common) names
                parentbus = self.GhostbusPortBus
            for base, submod in decoder.submods:
                ss = submod._WriteGhostbusSubmodMap(dest_dir, self.name)
                submod._GhostbusDoSubmods(dest_dir)
        return

    def _GhostbusDecoding(self):
        """Generate the bus decoding logic for this instance."""
        ss = []
        for domain, decoder in self.domains.items():
            ss.append(decoder.localInit())
            ss.append(decoder.submodsTopInit())
            ss.append(decoder.extmodsTopInit())
            ss.append(decoder.dinRouting())
            ss.append(decoder.busDecoding())
        return "\n".join(ss)

    def _GhostbusBlockDecoding(self):
        block_decode = {}
        for domain, decoder in self.domains.items():
            decode = decoder.blockDecoding()
            for branch, decodestr in decode.items():
                ss = block_decode.get(branch, "")
                block_decode[branch] = ss + decodestr + "\n"
        return block_decode

    def GhostbusMagic(self, dest_dir="_auto"):
        """Generate the automatic files for this project and write to
        output directory 'dest_dir'."""
        import os
        self._addGhostbusLive(dest_dir)
        self._addGhostPortsDef(dest_dir)
        self._GhostbusDoSubmods(dest_dir)
        return

    def _addGhostbusLive(self, dest_dir):
        live = "GHOSTBUS_LIVE"
        macrostr = (
            f"`ifndef {live}",
            f"`define {live}",
            f"`endif // ifndef {live}",
        )
        with open(os.path.join(dest_dir, self._def_file), "a") as fd:
            fd.write("\n".join(macrostr) + "\n")
        return

    def _addGhostPortsDef(self, dest_dir):
        gbports = self._GhostbusPorts()
        fname = "ghostbusports.vh"
        with open(os.path.join(dest_dir, fname), "w") as fd:
            fd.write(gbports + "\n")
            print(f"Wrote to {fname}")
        macrostr = f"GHOSTBUSPORTS"
        macrodef = f"`include \"{fname}\""
        return self._addDef(dest_dir, macrostr, macrodef)

    def _GhostbusPorts(self):
        """Generate the necessary ghostbus Verilog port declaration"""
        ghostbus = self.GhostbusPortBus
        ports = ghostbus.getPortList() # (key, name, rangestr, dir)
        ss = ["// Ghostbus ports"]
        for key, portname, rangestr, _dir in ports:
            dirstr = BusLB.direction_string_periph(_dir)
            ss.append(f",{dirstr} {rangestr} {portname}")
        return "\n".join(ss)

    def ExtraVerilogMemoryMap(self, filename, ghostbusses):
        """An extra (non-core functionality) feature.  Generate a memory
        map in Verilog syntax which can be used for automatic testbench
        decoder validation.
        Generates:
            localparam nCSRs = X;
            localparam nRAMs = Y;
            // For CSRs
            reg [aw-1:0] GHOSTBUS_ADDRS [0:nCSRs-1];
            reg [dw-1:0] GHOSTBUS_INITVALS [0:nCSRs-1];
            reg [dw-1:0] GHOSTBUS_RANDVALS [0:nCSRs-1];
            reg [nCSRs-1:0] GHOSTBUS_WRITABLE;
            // For RAMs
            reg [aw-1:0] GHOSTBUS_RAM_BASES [0:nRAMs-1];
            reg [dw-1:0] GHOSTBUS_RAM_WIDTHS [0:nRAMs-1];
            reg [dw-1:0] GHOSTBUS_RAM_DEPTHS [0:nRAMs-1];
            reg [nRAMs-1:0]GHOSTBUS_RAM_WRITABLE;
        """
        import random
        def flatten_bits(ll):
            v = 0
            for n in range(len(ll)):
                if ll[n]:
                    v |= (1<<n)
            return v

        # TODO - Enable all the ghostbusses
        bus = ghostbusses[0]
        csrs = []
        rams = []
        self._collectCSRs(csrs)
        self._collectRAMs(rams)
        # TODO - Find and remove any prefix common to all CSRs (this is done elsewhere a bit sloppily)
        print("CSRs:")
        csr_writeable = []
        for csr in csrs:
            print("{}.{}: 0x{:x}".format(csr._domain[1], csr.name, csr._domain[0] + csr.base))
            wa = 1 if (((csr.access & Register.WRITE) > 0) and not csr.strobe) else 0
            csr_writeable.append(wa)
        cw = flatten_bits(csr_writeable)
        print("RAMs:")
        ram_writeable = []
        for ram in rams:
            print("{}.{}: 0x{:x}".format(ram._domain[1], ram.name, ram._domain[0] + ram.base))
            wa = 1 if (ram.access & Register.WRITE) > 0 else 0
            ram_writeable.append(wa)
        rw = flatten_bits(ram_writeable)
        aw = bus["aw"]
        dw = bus["dw"]
        nCSRs = len(csrs)
        nRAMs = len(rams)
        # Define the structures
        ss = [
            "// Auto-generated with ghostbusser",
            f"localparam nCSRs = {len(csrs)};",
            f"localparam nRAMs = {len(rams)};",
            "// For CSRs",
            f"reg [{aw}-1:0] GHOSTBUS_ADDRS [0:nCSRs-1];",
            f"reg [{dw}-1:0] GHOSTBUS_INITVALS [0:nCSRs-1];",
            f"reg [{dw}-1:0] GHOSTBUS_RANDVALS [0:nCSRs-1];",
            f"reg [nCSRs-1:0] GHOSTBUS_WRITABLE = {vhex(cw, nCSRs)};",
            "// For RAMs",
            f"reg [{aw}-1:0] GHOSTBUS_RAM_BASES [0:nRAMs-1];",
            f"reg [{dw}-1:0] GHOSTBUS_RAM_WIDTHS [0:nRAMs-1];",
            f"reg [{aw}-1:0] GHOSTBUS_RAM_DEPTHS [0:nRAMs-1];",
            f"reg [nRAMs-1:0] GHOSTBUS_RAM_WRITABLE = {vhex(rw, nRAMs)};",
            "// Initialization",
            #"integer N;",
            "initial begin",
            #"  for (N=0; N<nCSRs; N=N+1) begin: CSR_Init",
        ]
        # Initialize CSR info
        for n in range(len(csrs)):
            csr = csrs[n]
            ss.append(f"  GHOSTBUS_ADDRS[{n}] = {vhex(csr._domain[0] + csr.base, aw)}; // {csr._domain[1]}.{csr.name}")
            ss.append(f"  GHOSTBUS_INITVALS[{n}] = {vhex(csr.initval, dw)};")
            randval = random.randint(0, (1<<csr.dw)-1) # Random number within the range of the CSR's width
            ss.append(f"  GHOSTBUS_RANDVALS[{n}] = {vhex(randval, dw)}; // 0 <= x <= 0x{(1<<csr.dw) - 1:x}")
        #ss.append("  end")
        # Initialize RAM info
        #ss.append("  for (N=0; N<nRAMs; N=N+1) begin: RAM_Init")
        for n in range(len(rams)):
            ram = rams[n]
            ss.append(f"  GHOSTBUS_RAM_BASES[{n}] = {vhex(ram._domain[0] + ram.base, aw)}; // {ram._domain[1]}.{ram.name}")
            ss.append(f"  GHOSTBUS_RAM_WIDTHS[{n}] = {vhex(ram.dw, dw)}; // TODO - may not be accurate due to parameterization...")
            ss.append(f"  GHOSTBUS_RAM_DEPTHS[{n}] = {vhex((1<<ram.aw), aw)}; // TODO - may not be accurate due to parameterization...")
        #ss.append("  end")
        ss.append("end")
        # GB tasks
        # TODO - Do it right depending on what bus signals are defined
        tasks = (
            "// Bus transaction tasks",
            "reg test_pass=1'b1;",
            f"task GB_WRITE (input [{aw-1}:0] addr, input [{dw-1}:0] data);",
            "  begin",
            f"    @(posedge {bus['clk']}) {bus['addr']} = addr;",
            f"    {bus['dout']} = data;",
            f"    {bus['we']} = 1'b1;",
            f"    {bus['wstb']} = 1'b1;" if (bus['wstb'] is not None and bus['wstb'] != bus['we']) else "",
            f"    @(posedge {bus['clk']}) {bus['we']} = 1'b0;",
            f"    {bus['wstb']} = 1'b0;" if (bus['wstb'] is not None and bus['wstb'] != bus['we']) else "",
            "  end",
            "endtask",

            "`ifndef RDDELAY",
            "  `define RDDELAY 2",  # TODO parameterize somehow
            "`endif",
            f"task GB_READ_CHECK (input [{aw-1}:0] addr, input [{dw-1}:0] checkval);",
            "  begin",
            f"    @(posedge {bus['clk']}) {bus['addr']} = addr;",
            f"    {bus['dout']} = {vhex(0, dw)};",
            f"    {bus['we']} = 1'b0;",
            f"    {bus['re']} = 1'b1;" if bus['re'] is not None else "",
            "    #(`RDDELAY*TICK);",
            f"    @(posedge {bus['clk']});",
            f"    {bus['rstb']} = 1'b1;" if bus['rstb'] is not None else "",
            f"    @(posedge {bus['clk']}) {bus['rstb']} = 1'b0;" if bus['rstb'] is not None else "",
            f"    {bus['re']} = 1'b0;" if bus['re'] is not None else "",
            f"    if ({bus['din']} != checkval) begin",
            "       test_pass = 1'b0;",
            "`ifndef YOSYS",
            f"       $display(\"ERROR: Read from addr 0x%x. Expected 0x%x, got 0x%x\", addr, checkval, {bus['din']});",
            "`endif",
            "    end",
            "  end",
            "endtask",
        )
        ss.extend(tasks)
        stimulus = (
            "// Stimulus",
            "integer LOOPN;",
            "initial begin",
            "  #TICK;",
            "  `ifdef GHOSTBUS_TEST_CSRS",
            "  $display(\"Reading init values.\");",
            "  for (LOOPN=0; LOOPN<nCSRs; LOOPN=LOOPN+1) begin",
            "    #TICK GB_READ_CHECK(GHOSTBUS_ADDRS[LOOPN], GHOSTBUS_INITVALS[LOOPN]);",
            "  end",
            "  if (test_pass) $display(\"PASS\");",
            "  else $display(\"FAIL\");",
            "  #TICK test_pass = 1'b1;",
            "  $display(\"Writing CSRs with random values.\");",
            "  for (LOOPN=0; LOOPN<nCSRs; LOOPN=LOOPN+1) begin",
            "    if (GHOSTBUS_WRITABLE[LOOPN]) begin",
            "      #TICK GB_WRITE(GHOSTBUS_ADDRS[LOOPN], GHOSTBUS_RANDVALS[LOOPN]);",
            "    end",
            "  end",
            "  $display(\"Reading back written values.\");",
            "  for (LOOPN=0; LOOPN<nCSRs; LOOPN=LOOPN+1) begin",
            "    if (GHOSTBUS_WRITABLE[LOOPN]) begin",
            "      #TICK GB_READ_CHECK(GHOSTBUS_ADDRS[LOOPN], GHOSTBUS_RANDVALS[LOOPN]);",
            "    end",
            "  end",
            "  if (test_pass) $display(\"PASS\");",
            "  else $display(\"FAIL\");",
            "  #TICK test_pass = 1'b1;",
            "  `endif // GHOSTBUS_TEST_CSRS",
            "  `ifdef GHOSTBUS_TEST_RAMS",
            "  // TODO", # TODO
            "  `endif // GHOSTBUS_TEST_RAMS",
            "  if (test_pass) begin",
            "    $display(\"PASS\");",
            "    $finish(0);",
            "  end else begin",
            "    $display(\"FAIL\");",
            "    $stop(0);",
            "  end",
            "end",
        )
        ss.extend(stimulus)
        outs = "\n".join(ss).replace('\n\n', '\n')
        if filename is None:
            print("\n".join(outs))
            return
        else:
            with open(filename, 'w') as fd:
                fd.write(outs)
        return


class DecoderDomainLB():
    # This list is singular to the class and keeps track of macros
    # defined by any instance
    _defs = []
    def __init__(self, parent, memregion, ghostbusses, gbportbus):
        self.parent = parent
        self.bustop = False
        self.mod = memregion
        self.domain = memregion.domain
        self.gbportbus = gbportbus
        # Keep a list of all known ghostbusses (global, could be anywhere)
        self._ghostbusses = ghostbusses
        self.busdomain = self.mod.busname # I think this may be identical to self.domain
        self.ghostbus_dict = {}
        for bus in self._ghostbusses:
            self.ghostbus_dict[bus.name] = bus
        # Ok, let's figure out self.ghostbus
        # If our domain is declared here (bustop for this domain), then self.ghostbus
        #   should refer to the net names in the codebase
        # Otherwise, it should refer to the global "gbportbus"
        if self.domain in memregion.declared_busses:
            self.ghostbus = self.ghostbus_dict[self.domain]
        else:
            self.ghostbus = gbportbus
        self.aw = self.mod.aw
        self.inst = self.mod.hierarchy[-1]
        self.name = self.mod.label
        if self.mod.toptag:
            # If the toptag is set, no implied busses coming in
            implied_busses = ()
        else:
            implied_busses = (self.mod.busname,)
        memregion.implicit_busses = implied_busses
        # ========================================= Cute print formatting - DELETEME
        if False:
            print(f"{self.__class__}({self.name})", end="")
            if len(memregion.declared_busses) > 0:
                print(f" declares ghostbusses {memregion.declared_busses}", end="")
                if len(implied_busses) > 0:
                    print(" and", end="")
            if len(implied_busses) > 0:
                implied_bus = implied_busses[0]
                if implied_bus is None:
                    print(f" lets in the default bus", end="")
                else:
                    print(f" lets in {implied_bus}.", end="")
            print()
        # ===========================================================================
        #self.nbusses = len(self.mod.declared_busses)
        self.nbusses = len(self.mod.declared_busses) + len(self.mod.implicit_busses)
        if len(memregion.declared_busses) > 0:
            self.bustop = True
        self.base = self.mod.base
        self.submods = []
        self.rams = []
        self.csrs = []
        self.exts = []
        # Independently keep track of items declared within block (generate) scope
        self.block_submods = {} # {branch_name: [], ...}
        self.block_rams = {} # {branch_name: [], ...}
        self.block_csrs = {} # {branch_name: [], ...}
        self.block_exts = {} # {branch_name: [], ...}
        self.max_local = 0
        self._no_reads = False # TODO Assume True and prove me wrong by finding something readable
        self._parseMemoryRegion(memregion)

        if self.max_local == 0:
            self.no_local = True
        else:
            self.no_local = False
        self.local_aw = bits(self.max_local)
        self._def_file = "defs.vh"
        self.check_bus()
        # Net names for universal auto-generated nets
        self.en_local = "ghostbus_addrhit_local" # TODO - Harmonize this with a singleton netname generator class
        self.local_din = "ghostbus_rdata_local"  # TODO - Harmonize this with a singleton netname generator class
        self.autogen_loop_index = "GHOSTBUS_AUTOGEN_INDEX" # TODO - Harmonize this with a singleton netname generator class

    def _parseMemoryRegion(self, memregion):
        for start, stop, ref in memregion.get_entries():
            if hasattr(ref, "access"):
                if ref.access & ref.READ:
                    self._no_reads = False
            if isinstance(ref, GBRegister):
                if hasattr(ref, "genblock") and ref.genblock is not None:
                    print(f"GBRegister {ref.name} is instantiated within generate block {ref.genblock.branch}")
                    if self.block_csrs.get(ref.genblock.branch) is None:
                        self.block_csrs[ref.genblock.branch] = []
                    self.block_csrs[ref.genblock.branch].append(ref)
                else:
                    self.csrs.append(ref)
            elif isinstance(ref, GBMemory):
                if hasattr(ref, "genblock") and ref.genblock is not None:
                    print(f"GBMemory {ref.name} is instantiated within generate block {ref.genblock.branch}")
                    if self.block_rams.get(ref.genblock.branch) is None:
                        self.block_rams[ref.genblock.branch] = []
                    self.block_rams[ref.genblock.branch].append(ref)
                else:
                    self.rams.append(ref)
            elif isinstance(ref, ExternalModule):
                ref.ghostbus = self.ghostbus
                if hasattr(ref, "genblock") and ref.genblock is not None:
                    print(f"ExternalModule {ref.name} is instantiated within generate block {ref.genblock.branch}")
                    if self.block_exts.get(ref.genblock.branch) is None:
                        self.block_exts[ref.genblock.branch] = []
                    self.block_exts[ref.genblock.branch].append(ref)
                else:
                    self.exts.append((start, ref))
            if isinstance(ref, Register): # Should catch MetaRegister and MetaMemory
                if stop > self.max_local:
                    self.max_local = stop

    @property
    def genblock(self):
        return self.parent.genblock

    @property
    def gen_addrs(self):
        return self.parent.gen_addrs

    def add_submod(self, submod, base):
        self.submods.append((base, submod))
        # TODO - Detect whether submod is readable and update self._no_reads

    def add_block_submod(self, branch, submod, base):
        if self.block_submods.get(branch) is None:
            self.block_submods[branch] = []
        self.block_submods[branch].append((base, submod))

    def _resolveSubmods(self):
        block_submods = {}
        for branch, submods in self.block_submods.items():
            block_submods[branch] = []
            moddict = {}
            # Re-organize the data a bit
            for start_addr, submod in submods:
                block_name, modname, loop_index = block_inst(submod.inst)
                if moddict.get(modname) is None:
                    moddict[modname] = {"indices": [], "refs": [], "addrs": []}
                moddict[modname]["indices"].append(loop_index)
                moddict[modname]["refs"].append(submod)
                moddict[modname]["addrs"].append(start_addr)
            loop_len = None
            for modname, modinfo in moddict.items():
                indices = modinfo["indices"]
                refs = modinfo["refs"]
                addrs = modinfo["addrs"]
                ref = refs[0]
                if not check_complete_indices(indices):
                    raise GhostbusInternalException(f"Did not find all indices for {ref.name} in {block_info['module_name']}")
                if loop_len is None:
                    loop_len = len(indices)
                elif len(indices) != loop_len:
                    err = f"Somehow I'm getting inconsistent number of loops through {block_name} in {block_info['module_name']}" \
                        + f" ({len(indices)} != {loop_len})"
                    raise GhostbusInternalException()
                ref.setInst(modname)
                ref.gen_addrs = {indices[n]: addrs[n] for n in range(len(addrs))}
                print(f"Submod {modname} gets addresses: {ref.gen_addrs}")
                block_submods[branch].append(ref)
            print(f"Branch {branch}: submods = {block_submods[branch]}")
        # Clobber block_submods
        self.block_submods = block_submods
        #print(f"self.block_submods = {self.block_submods}")
        #for branch, decoders in self.block_submods.items():
        #    for decoder in decoders:
        #        print(f"  decoder.gen_addrs = {decoder.gen_addrs}")
        return

    def check_bus(self):
        """If any strobes exist, verify the bus has the appropriate strobe signal
        defined."""
        #print(self.ghostbus)
        for csr in self.csrs:
            if csr.strobe or (len(csr.write_strobes) > 0):
                if self.ghostbus["wstb"] is None:
                    if csr.strobe:
                        strobe_name = csr.name
                    else:
                        strobe_name = csr.write_strobes[0]
                    serr = f"\n{strobe_name} requires a 'wstb' signal in the ghostbus. " + \
                            "Please define it with the other bus signals, e.g.:\n" + \
                            "  (* ghostbus_port='wstb' *) wire wstb;\n" + \
                            "If your write-enable signal is also a strobe (1-cycle long), " + \
                            "you can define it to also be the 'wstb' as in e.g.:\n" + \
                            "  (* ghostbus_port='wstb, we' *) wire wen;"
                    raise Exception(serr)
            if len(csr.read_strobes) > 0:
                if self.ghostbus["rstb"] is None:
                    strobe_name = csr.read_strobes[0]
                    serr = f"\n{strobe_name} requires a 'rstb' signal in the ghostbus. " + \
                            "Please define it with the other bus signals, e.g.:\n" + \
                            "  (* ghostbus_port='rstb' *) wire rstb;\n" + \
                            "If your read-enable signal is also a strobe (1-cycle long), " + \
                            "you can define it to also be the 'rstb' as in e.g.:\n" + \
                            "  (* ghostbus_port='rstb, re' *) wire ren;"
                    raise Exception(serr)
        # Make some decoding definitions here to save checks later
        portdict = self.ghostbus.getPortDict()
        namemap = self.ghostbus
        if (self.ghostbus['wstb'] is None) or (self.ghostbus['we'] == self.ghostbus['wstb']):
            self._bus_we = namemap['we']
        else:
            self._bus_we = f"{namemap['we']} & {namemap['wstb']}"
        if self.ghostbus['re'] is not None:
            self._asynch_read = False
            self._bus_re = namemap['re']
        else:
            self._bus_re = f"~{namemap['we']}"
            self._asynch_read = True
        return

    @classmethod
    def _logDef(cls, suffix):
        cls._defs.append(suffix)
        return

    @classmethod
    def _isDefd(cls, suffix):
        for ss in cls._defs:
            if ss == suffix:
                return True
        return False

    def _addDef(self, dest_dir, macrostr, macrodef):
        defstr = f"`define {macrostr} {macrodef}\n"
        with open(os.path.join(dest_dir, self._def_file), "a") as fd:
            fd.write(defstr)
        return

    def _addGhostbusDef(self, dest_dir, suffix):
        if self._isDefd(suffix):
            return
        macrostr = f"GHOSTBUS_{suffix}"
        macrodef = f"`include \"ghostbus_{suffix}.vh\""
        self._logDef(suffix)
        return self._addDef(dest_dir, macrostr, macrodef)

    def _collectCSRs(self, csrlist):
        for csr in self.csrs:
            # Adding attribute!
            # Need to copy because multiple module instances actually reference the same "Register" instances
            copy = csr.copy()
            copy._domain = (self.base, self.mod.name)
            csrlist.append(copy)
        for base, submod in self.submods:
            submod._collectCSRs(csrlist)
        return csrlist

    def _collectRAMs(self, ramlist):
        for ram in self.rams:
            # Need to copy because multiple module instances actually reference the same "Register" instances
            copy = ram.copy()
            # Adding attribute!
            copy._domain = (self.base, self.mod.name)
            ramlist.append(copy)
        for base, submod in self.submods:
            submod._collectRAMs(ramlist)
        return ramlist

    def _WriteGhostbusSubmodMap(self, dest_dir, parentname):
        fname = f"ghostbus_{parentname}_{self.inst}.vh"
        ss = self._GhostbusSubmodMap()
        with open(os.path.join(dest_dir, fname), "w") as fd:
            fd.write(ss)
            print(f"Wrote to {fname}")
        self._addGhostbusDef(dest_dir, f"{parentname}_{self.inst}")
        return

    def _GhostbusSubmodMap(self):
        """Generate the necessary ghostbus Verilog port map for this instance
        within its parent module.
        This will hook up all nets in the ghostbus, even if they are not used
        in this particular domain.  The nets are declared in submodInitStr()."""
        portlist = self.gbportbus.getPortList() # (key, name, rangestr, dirstr)
        ss = []
        for port in portlist:
            portkey, portname, rangestr, _dir = port
            if len(rangestr):
                rangestr = " " + rangestr
            dirstr = BusLB.direction_string_periph(_dir)
            ss.append(f",.{portname}({portname}_{self.inst}) // {dirstr}{rangestr}")
        return "\n".join(ss)

    def localInit(self):
        # wire en_local = gb_addr[11:9] == 3'b000; // 0x000-0x1ff
        # reg  [31:0] local_din=0;
        if self.no_local:
            return ""
        en_local = self.en_local
        local_din = self.local_din
        if self.domain is not None:
            en_local += "_" + self.domain
            local_din += "_" + self.domain
        busaw = self.ghostbus.aw
        divwidth = busaw - self.local_aw
        ss = [
            f"// local init",
            f"wire {en_local} = {self.ghostbus['addr']}[{busaw-1}:{self.local_aw}] == {vhex(0, divwidth)}; // 0x0-0x{1<<self.local_aw:x}",
            f"reg  [{self.ghostbus['dw']-1}:0] {local_din}=0;",
        ]
        if len(self.rams) > 0:
            ss.append("// local rams")
            for n in range(len(self.rams)):
                ss.append(self._ramInit(self.rams[n]))
        ss.append(self.localBlockInit())
        return "\n".join(ss)

    def localBlockInit(self):
        ss = []
        any_block = False
        for branch, csrs in self.block_csrs.items():
            if len(csrs) == 0:
                continue
            if not any_block:
                ss.append("// CSRs in block scope")
                any_block = True
            ss.append(f"//   Generate Block {branch}")
            for csr in csrs:
                ss.append(self._blockCsrInit(csr, branch))
        any_block = False
        for branch, rams in self.block_rams.items():
            if len(rams) == 0:
                continue
            if not any_block:
                ss.append("// RAMs in block scope")
                any_block = True
            ss.append(f"//   Generate Block {branch}")
            for ram in rams:
                ss.append(self._blockRamInit(ram, branch))
        return "\n".join(ss)

    def submodsTopInit(self):
        ss = []
        for base, submod in self.submods:
            ss.append(submod.submodInitStr(base, self))

        for branch, submods in self.block_submods.items():
            ss.append(f"// Branch {branch}")
            for submod in submods:
                ss.append(submod.submodInitStr(None, self))
        return "\n".join(ss)

    def extmodsTopInit(self):
        ss = []
        for base_rel, ext in self.exts:
            ss.append(f"// External Module Instance {ext.name}")
            ss.append(self._addrHit(base_rel, ext, self))
            ss.append(self.busHookup(ext, self))

        any_block = False
        for branch, exts in self.block_exts.items():
            if len(exts) == 0:
                continue
            if not any_block:
                ss.append("// Extmods in block scope")
                any_block = True
            ss.append(f"//   Generate Block {branch}")
            for ext in exts:
                ss.append(self._blockExtInit(ext, branch))

        return "\n".join(ss)

    def _ramInit(self, mod):
        # localparam FOO_RAM_AW = $clog2(RD);
        # wire en_foo_ram = gb_addr[8:3] == 6'b001000;
        if self.local_aw is None:
            local_aw = self.ghostbus['aw']
        else:
            local_aw = self.local_aw
        divwidth = local_aw - mod.aw
        base_rel = mod.base
        end = base_rel + (1<<mod.aw) - 1
        ss = (
            f"localparam {mod.name.upper()}_AW = $clog2({mod.depth[1]}+1);",
            f"wire addrhit_{mod.name} = {self.ghostbus['addr']}[{local_aw-1}:{mod.aw}] == {vhex(mod.base>>mod.aw, divwidth)}; // 0x{base_rel:x}-0x{end:x}",
        )
        return "\n".join(ss)

    def _blockCsrInit(self, csr, branch):
        ss = []
        # Make one register for reading and one for writing
        if None in csr.range:
            rangestr = ""
        else:
            rangestr = f"[{csr.range[0]}:{csr.range[1]}] "
        looprange = ""
        if isForLoop(csr.genblock):
            looprange = f" {csr.genblock.loop_range}"
        ss.append(f"reg {rangestr}{branch}_{csr.name}_r{looprange};")
        ss.append(f"reg {rangestr}{branch}_{csr.name}_w{looprange};")
        return "\n".join(ss)

    def _blockRamInit(self, ram, branch):
        # Declare a wire for reading from within the block scope, then declare RAM as normal
        # but with branch name incorporated into net names
        if self.local_aw is None:
            local_aw = self.ghostbus['aw']
        else:
            local_aw = self.local_aw
        divwidth = local_aw - ram.aw
        base_rel = ram.base
        end = base_rel + (1<<ram.aw) - 1
        if None in ram.range:
            rangestr = ""
        else:
            rangestr = f"[{ram.range[0]}:{ram.range[1]}] "
            addrhit = f"wire addrhit_{branch}_{ram.name} = {self.ghostbus['addr']}[{local_aw-1}:{ram.aw}] == {vhex(ram.base>>ram.aw, divwidth)}; // 0x{base_rel:x}-0x{end:x}"
            if ram.genblock.isFor():
                rangestr = ram.genblock.unrollRangeString(rangestr) + " "
                addrhit_range = f"[{ram.genblock.unrolled_size}-1:0] "
                addrhit = f"wire {addrhit_range}addrhit_{branch}_{ram.name};"
        ss = [f"wire {rangestr}{branch}_{ram.name}_r;"]
        ss.extend([
            f"localparam {branch.upper()}_{ram.name.upper()}_AW = $clog2({ram.depth[1]}+1);",
            addrhit,
        ])
        return "\n".join(ss)

    def _blockExtInit(self, extmod, branch):
        # TODO
        return f"// TODO - Initialize extmod {extmod.name} in branch {branch}"

    @staticmethod
    def _addrHit(base_rel, mod, parent=None):
        if parent is None:
            bus = mod.ghostbus
        else:
            bus = parent.ghostbus
        busaw = bus['aw']
        addr_net = bus['addr']
        divwidth = busaw - mod.aw
        end = base_rel + (1<<mod.aw) - 1
        # TODO - Should I be using the string 'aw_str' here instead of the integer 'aw'? I would need to be implicit with the width
        #        to 'vhex' or do some tricky concatenation
        if divwidth == 0:
            return f"wire addrhit_{mod.inst} = 1'b1; // 0x{base_rel:x}-0x{end:x}"
        return f"wire addrhit_{mod.inst} = {addr_net}[{busaw-1}:{mod.aw}] == {vhex(base_rel>>mod.aw, divwidth)}; // 0x{base_rel:x}-0x{end:x}"

    @staticmethod
    def _addrMask(mod, parent):
        if parent is None:
            bus = mod.ghostbus
        else:
            bus = parent.ghostbus
        busaw = bus['aw']
        addr_net = bus['addr']
        divwidth = busaw - mod.aw
        if divwidth == 0:
            return f"wire [{busaw-1}:0] {mod.ghostbus['addr']}_{mod.inst} = {addr_net}[{mod.aw-1}:0]; // address relative to own base (0x0)"
        return f"wire [{busaw-1}:0] {mod.ghostbus['addr']}_{mod.inst} = {{{vhex(0, divwidth)}, {addr_net}[{mod.aw-1}:0]}}; // address relative to own base (0x0)"

    def _wen(self, mod, parent_bustop):
        return self._andPort(mod, "we", parent_bustop=parent_bustop)

    def _andPort(self, mod, portname, parent_bustop=False):
        portdict = mod.ghostbus.getPortDict()
        signal = portdict[portname]
        if parent_bustop:
            parent_signal = mod.ghostbus[portname]
        else:
            parent_signal = signal
        return f"wire {signal}_{mod.inst}={parent_signal} & addrhit_{mod.inst};"

    def submodInitStr(self, base_rel, parent):
        """Declare and assign the nets required to attach a submod to the ghostbus.
        'parent' is the module in which the submodule is instantiated.
        For a multi-domain codebase, it's possible that parent.ghostbus does not use all
        the nets in the ghostbus.  In this case, unused nets are still declared.
        Unused inputs into the submod are tied low (assigned to 0).
        """
        parentbus = parent.ghostbus
        gbports = self.gbportbus
        addrMask = self._addrMask(self, parent)
        ss = [f"// submodule {self.inst}"]
        # If this is in a For-Loop, addrHit needs to be declared here as a vector then assigned within the loop
        loopsize = ""
        loopvector = ""
        if isForLoop(self.genblock):
            loopsize = self.genblock.unrolled_size
            loopvector = f"[{loopsize}-1:0] "
            ss.append(f"wire {loopvector} addrhit_{self.inst};")
        else:
            addrHit = self._addrHit(base_rel, self, parent)
            ss.append(addrHit)
        netlist = self.gbportbus.getPortList() # (key, name, rangestr, dirstr)
        for net in netlist:
            netkey, netname, rangestr, _dir = net
            if netkey == "addr":
                ss.append(addrMask)
                continue
            # If net is unused in parentbus
            if parentbus[netkey] is None:
                # If it's an input to the submod (host-centric output)
                if _dir == BusLB._output:
                    # Wire to 0
                    ss.append(f"wire {rangestr}{gbports[netkey]}_{self.inst} = 0; // (unused submod input)")
                else:
                    ss.append(f"wire {rangestr}{gbports[netkey]}_{self.inst}; // (unused submod output)")
            else:
                if len(rangestr):
                    rangestr += " "
                if netkey in ('clk', 'addr', 'dout'):
                    ss.append(f"wire {rangestr}{gbports[netkey]}_{self.inst} = {parentbus[netkey]};")
                elif netkey in ('we', 'wstb', 're', 'rstb'):
                    if loopsize == "":
                        pbk = f"{parentbus[netkey]}"
                    else:
                        pbk = f"{{{loopsize}{{{parentbus[netkey]}}}}}"
                        rangestr = loopvector
                    ss.append(f"wire {rangestr}{gbports[netkey]}_{self.inst} = {pbk} & addrhit_{self.inst};")
                elif netkey in ('din',):
                    if isForLoop(self.genblock):
                        rangestr = self.genblock.unrollRangeString(rangestr) + " "
                    ss.append(f"wire {rangestr}{gbports[netkey]}_{self.inst};")
                else:
                    ss.append(f"wire {rangestr}{gbports[netkey]}_{self.inst} = {parentbus[netkey]}; // extra port?")
        return "\n".join(ss)

    def dinRouting(self):
        # assign gb_din = en_baz_0 ? gb_din_baz_0 :
        #                 en_bar_0 ? gb_din_bar_0 :
        #                 en_local ? local_din :
        #                 32'h00000000;
        if self._no_reads:
            return ""
        if self.ghostbus["din"] is None:
            return ""
        en_local = self.en_local
        local_din = self.local_din
        if self.domain is not None:
            en_local += "_" + self.domain
            local_din += "_" + self.domain
        portdict = self.gbportbus
        namemap = self.ghostbus
        ss = [
            "// din routing",
        ]
        if self.no_local:
            ss.append(f"assign {namemap['din']} = ")
        else:
            ss.append(f"assign {namemap['din']} = {en_local} ? {local_din} :")
        for n in range(len(self.submods)):
            base, submod = self.submods[n]
            inst = submod.inst
            if n == 0 and self.no_local:
                ss[-1] = ss[-1] + f"addrhit_{inst} ? {portdict['din']}_{inst} :"
            else:
                ss.append(f"                addrhit_{inst} ? {portdict['din']}_{inst} :")
        for n in range(len(self.exts)):
            base_rel, ext = self.exts[n]
            if not ext.access & Register.READ:
                # Skip non-readable ext modules
                continue
            inst = ext.name
            din = ext.getDinPort()
            if (n == 0) and (self.no_local) and (len(self.submods) == 0):
                ss[-1] = ss[-1] + f"addrhit_{inst} ? {{{{{self.ghostbus['dw']-ext.dw}{{1'b0}}}}, {din}}} :"
            else:
                ss.append(f"                addrhit_{inst} ? {{{{{self.ghostbus['dw']-ext.dw}{{1'b0}}}}, {din}}} :")
        ss.append(f"                {vhex(0, self.ghostbus['dw'])};")
        return "\n".join(ss)

    def busDecoding(self):
        en_local = self.en_local
        if self.domain is not None:
            en_local += "_" + self.domain

        _ramwrites = self.ramWrites()
        if len(_ramwrites) == 0:
            ramwrites = "// No rams"
        else:
            ramwrites = _ramwrites
        csrdefaults = []
        _csrwrites, wdefaults = self.csrWrites()
        if len(_csrwrites) == 0:
            csrwrites = "// No CSRs"
        else:
            csrwrites = _csrwrites
        _ramreads = self.ramReads()
        crindent = 4*" "
        extraend = ""
        midend = ""
        if len(_ramreads) == 0:
            #crindent = 6*" "
            ramreads = "// No rams"
        else:
            ramreads = _ramreads
        _csrreads, rdefaults = self.csrReads()
        if len(_csrreads) == 0:
            if len(_ramreads) > 0:
                midend = " else begin"
            csrreads = "// No CSRs"
        else:
            csrreads = _csrreads
        ss = []
        hasclk = False
        csrdefaults.extend(wdefaults)
        csrdefaults.extend(rdefaults)
        namemap = self.ghostbus
        ss.append(f"integer {self.autogen_loop_index}=0;")
        if len(_ramwrites) > 0 or len(_csrwrites) > 0:
            ss.append(f"always @(posedge {namemap['clk']}) begin")
            ss.append(f"  {self.local_din} <= 0;")
            if len(csrdefaults) > 0:
                ss.append("  // Strobe default assignments")
            for strobe in csrdefaults:
                if hasattr(strobe, "name"):
                    ss.append(f"  {strobe.name} <= {vhex(0, strobe.dw)};")
                else:
                    ss.append(f"  {strobe} <= {vhex(0, 1)};")
            ss.append("  // local writes")
            ss.append(f"  if ({en_local} & {self._bus_we}) begin")
            ss.append("    " + ramwrites.replace("\n", "\n    "))
            ss.append("    " + csrwrites.replace("\n", "\n    "))
            ss.append(f"  end // if ({en_local} & {self._bus_we})")
            hasclk = True
        if len(_ramreads) > 0 or len(_csrreads) > 0:
            if not hasclk:
                ss.append(f"always @(posedge {namemap['clk']}) begin")
            ss.append("  // local reads")
            ss.append(f"  if ({en_local} & {self._bus_re}) begin")
            ss.append("    " + ramreads.replace("\n", "\n    ") + midend)
            ss.append(crindent + csrreads.replace("\n", "\n"+crindent))
            ss.append(extraend)
            ss.append(f"  end // if ({en_local} & {self._bus_re})")
        if hasclk:
            ss.append(f"end // always @(posedge {namemap['clk']})")
        return "\n".join(ss)

    def _get_all_csrs(self, block_append=""):
        csrs = self.csrs.copy()
        # Include CSRs declared in generate-if blocks
        for branch, block_csrs in self.block_csrs.items():
            for csr in block_csrs:
                if csr.genblock is not None and csr.genblock.isIf():
                    copy = csr.copy()
                    copy.name = f"{branch}_{csr.name}{block_append}"
                    csrs.append(copy)
        return csrs

    def csrWrites(self):
        if len(self.csrs) == 0:
            return ("", [])
        namemap = self.ghostbus
        # Default-assign any strobes
        defaults = []
        ss = [
            "// CSR writes",
            f"casez ({namemap['addr']}[{self.local_aw-1}:0])",
        ]
        writes = 0
        csrs = self._get_all_csrs(block_append="_w")
        for csr in csrs:
            if csr.strobe:
                defaults.append(csr)
            if len(csr.write_strobes) > 0:
                defaults.extend(csr.write_strobes)
        for n in range(len(csrs)):
            csr = csrs[n]
            if (csr.access & Register.WRITE) == 0:
                # Skip read-only registers
                continue
            writes += 1
            if len(csr.write_strobes) == 0:
                if csr.strobe:
                    ss.append(f"  {vhex(csr.base, self.local_aw)}: {csr.name} <= {vhex(1, csr.dw)};")
                else:
                    ss.append(f"  {vhex(csr.base, self.local_aw)}: {csr.name} <= {namemap['dout']}[{csr.range[0]}:0];")
            else:
                ss.append(f"  {vhex(csr.base, self.local_aw)}: begin")
                if csr.strobe:
                    ss.append(f"    {csr.name} <= {vhex(0, strobe.dw)};")
                else:
                    ss.append(f"    {csr.name} <= {namemap['dout']}[{csr.range[0]}:0];")
                for strobe_name in csr.write_strobes:
                    ss.append(f"    {strobe_name} <= 1'b1;")
                ss.append(f"  end")
        ss.append("endcase")
        ss.append(self.genCsrWrites())
        #if writes == 0:
        #    return ("", [])
        return ("\n".join(ss), defaults)

    def genCsrWrites(self):
        """Return write decoding logic for CSRs declared in generate-for block scope"""
        #// Generate-For CSRs
        #// foo_generator.top_foo_n
        #for (AUTOGEN_INDEX=0; AUTOGEN_INDEX<FOO_COPIES; AUTOGEN_INDEX=AUTOGEN_INDEX+1) begin
        #  if (gb_addr[5:0] == (FOO_GENERATOR_TOP_FOO_N_BASE[5:0] | AUTOGEN_INDEX[5:0])) begin
        #    foo_generator_top_foo_n_w[AUTOGEN_INDEX] <= gb_wdata[3:0];
        #  end
        #end
        ss = []
        agi = self.autogen_loop_index
        for branch, csrs in self.block_csrs.items():
            if len(csrs) == 0:
                continue
            isfor = csrs[0].genblock.isFor()
            if not isfor:
                continue
            block_size = csrs[0].genblock.unrolled_size
            ss.append(f"// Generate {branch}")
            # Generate-For
            ss.append(f"for ({agi}=0; {agi}<{block_size}; {agi}={agi}+1) begin")
            for csr in csrs:
                #depth = f"({ram.depth[1]}+1)"
                ar = f"[{self.local_aw-1}:0]"
                #addrs = [addr for addr in csr.gen_addrs.values()]
                #addrs.sort()
                base = csr.base
                dec = f"{self.ghostbus['addr']}{ar} == {vhex(base, self.local_aw)} + {agi}{ar}"
                ss.append(f"  // {csr.name}")
                ss.append(f"  if ({dec}) begin")
                ss.append(f"    {branch}_{csr.name}_w[{agi}] <= {self.ghostbus['dout']}[{csr.range[0]}:{csr.range[1]}];")
                ss.append( "  end")
            ss.append("end")
        return "\n".join(ss)

    def csrReads(self):
        if len(self.csrs) == 0:
            return ("", [])
        local_din = self.local_din
        if self.domain is not None:
            local_din += "_" + self.domain
        namemap = self.ghostbus
        csrs = self._get_all_csrs(block_append="_r")
        # Default-assign any strobes
        defaults = []
        for csr in csrs:
            if len(csr.read_strobes) > 0:
                defaults.extend(csr.read_strobes)
        ss = [
            "// CSR reads",
            f"casez ({namemap['addr']}[{self.local_aw-1}:0])",
        ]
        reads = 0
        for n in range(len(csrs)):
            csr = csrs[n]
            if (csr.access & Register.READ) == 0:
                # Skip write-only registers
                continue
            if len(csr.read_strobes) == 0:
                ss.append(f"  {vhex(csr.base, self.local_aw)}: {local_din} <= {{{{{self.ghostbus['dw']}-({csr.range[0]}+1){{1'b0}}}}, {csr.name}}};")
            else:
                ss.append(f"  {vhex(csr.base, self.local_aw)}: begin")
                ss.append(f"    {local_din} <= {{{{{self.ghostbus['dw']}-({csr.range[0]}+1){{1'b0}}}}, {csr.name}}};")
                for strobe_name in csr.read_strobes:
                    ss.append(f"    {strobe_name} <= 1'b1;")
                ss.append(f"  end")
            reads += 1
        # I need to leave the default off to allow RAM reads to take effect
        #ss.append(f"  default: {local_din} <= {vhex(0, self.ghostbus['dw'])};")
        ss.append("endcase")
        ss.append(self.genCsrReads())
        #if reads == 0:
        #    return ("", [])
        return ("\n".join(ss), defaults)

    def genCsrReads(self):
        """Return read decoding logic for CSRs declared in generate-for block scope"""
        #// Generate-For CSRs
        #// foo_generator.top_foo_n
        #for (AUTOGEN_INDEX=0; AUTOGEN_INDEX<FOO_COPIES; AUTOGEN_INDEX=AUTOGEN_INDEX+1) begin
        #  if (gb_addr[5:0] == (FOO_GENERATOR_TOP_FOO_N_BASE[5:0] | AUTOGEN_INDEX[5:0])) begin
        #    local_din <= {{32-(3+1){1'b0}}, foo_generator_top_foo_n_r[AUTOGEN_INDEX]};
        #  end
        #end
        ss = []
        agi = self.autogen_loop_index
        for branch, csrs in self.block_csrs.items():
            if len(csrs) == 0:
                continue
            isfor = csrs[0].genblock.isFor()
            if not isfor:
                continue
            block_size = csrs[0].genblock.unrolled_size
            ss.append(f"// Generate {branch}")
            # Generate-For
            ss.append(f"for ({agi}=0; {agi}<{block_size}; {agi}={agi}+1) begin")
            for csr in csrs:
                #depth = f"({ram.depth[1]}+1)"
                ar = f"[{self.local_aw-1}:0]"
                #addrs = [addr for addr in csr.gen_addrs.values()]
                #addrs.sort()
                #base = addrs[0]
                base = csr.base
                dec = f"{self.ghostbus['addr']}{ar} == {vhex(base, self.local_aw)} + {agi}{ar}"
                ss.append(f"  // {csr.name}")
                ss.append(f"  if ({dec}) begin")
                ss.append(f"    {self.local_din} <= {{{{{self.ghostbus['dw']}-({csr.range[0]}+1){{1'b0}}}}, {branch}_{csr.name}_r[{agi}]}};")
                #ss.append(f"    {self.local_din} <= {{32-(3+1){1'b0}}, {branch}_{csr.name}_r[{agi}]};")
                #ss.append(f"    {branch}_{csr.name}_w <= {self.ghostbus['dout']}[{csr.range[0]}:{csr.range[1]}];")
                ss.append( "  end")
            ss.append("end")
        return "\n".join(ss)

    def _get_all_rams(self, block_append=""):
        rams = self.rams.copy()
        # Include RAMs declared in generate-if blocks
        for branch, block_rams in self.block_rams.items():
            for ram in block_rams:
                if ram.genblock is not None and ram.genblock.isIf():
                    copy = ram.copy()
                    copy.name = f"{branch}_{ram.name}{block_append}"
                    rams.append(copy)
        return rams

    def ramWrites(self):
        if len(self.rams) == 0:
            return ""
        namemap = self.ghostbus
        ss = [
            "// RAM writes",
            "",
        ]
        # Writes to RAMs in generate-if blocks are handled in block scope
        for n in range(len(self.rams)):
            ram = self.rams[n]
            s0 = f"if (addrhit_{ram.name}) begin"
            if n > 0:
                s0 = " else " + s0
            ss[-1] = ss[-1] + s0
            ss.append(f"  {ram.name}[{namemap['addr']}[{ram.name.upper()}_AW-1:0]] <= {namemap['dout']}[{ram.range[0]}:{ram.range[1]}];")
            ss.append("end")
        return "\n".join(ss)

    def ramReads(self):
        """Return read-decoding for RAMs declared in top scope."""
        #rams = self._get_all_rams(block_append="_r")
        rams = self.rams
        local_din = self.local_din
        if self.domain is not None:
            local_din += "_" + self.domain
        namemap = self.ghostbus
        if len(rams) == 0:
            ss = []
        else:
            ss = [
                "// RAM reads",
                "",
            ]
        for n in range(len(rams)):
            ram = rams[n]
            s0 = f"if (addrhit_{ram.name}) begin"
            if n > 0:
                s0 = " else " + s0
            ss[-1] = ss[-1] + s0
            #ss.append(f"  {ram.name}[{self.ghostbus['addr']}[{ram.name.upper()}_AW-1:0]] <= {self.ghostbus['dout']}[{ram.range[0]}:{ram.range[1]}];")
            ss.append(f"  {local_din} <= {{{{{self.ghostbus['dw']}-({ram.range[0]}+1){{1'b0}}}}, {ram.name}[{namemap['addr']}[{ram.name.upper()}_AW-1:0]]}};")
            ss.append("end")
        ss.append(self.genRamReads())
        return "\n".join(ss)

    def genRamReads(self):
        """Return read-decoding for RAMs declared in generate-for block scope."""
        ss = []
        num_rams = 0
        #// Generate RAMs
        #// foo_generator.foo_ram
        #for (AUTOGEN_INDEX=0; AUTOGEN_INDEX<FOO_COPIES; AUTOGEN_INDEX=AUTOGEN_INDEX+1) begin
        #  if (addrhit_foo_ram[AUTOGEN_INDEX]) begin
        #    local_din <= {{32-(3+1){1'b0}}, foo_generator_foo_ram_r[((AUTOGEN_INDEX+1)*8)-1-:8]};
        #  end
        #end
        agi = self.autogen_loop_index
        for branch, rams in self.block_rams.items():
            if len(rams) == 0:
                continue
            block_size = rams[0].genblock.unrolled_size
            isfor = rams[0].genblock.isFor()
            ss.append(f"// Generate {branch}")
            if isfor:
                # Generate-For
                ss.append(f"for ({agi}=0; {agi}<{block_size}; {agi}={agi}+1) begin")
                for ram in rams:
                    depth = f"({ram.depth[1]}+1)"
                    ss.append(f"  // {ram.name}")
                    ss.append(f"  if (addrhit_{branch}_{ram.name}[{agi}]) begin")
                    ss.append(f"    {self.local_din} <= {{{{{self.ghostbus['dw']}-({ram.range[0]}+1){{1'b0}}}}, {branch}_{ram.name}_r[(({agi}+1)*{depth})-1-:{depth}]}};")
                    ss.append( "  end")
                ss.append("end")
            else:
                # Generate-If
                for ram in rams:
                    ss.append(f"// {ram.name}")
                    ss.append(f"if (addrhit_{branch}_{ram.name}) begin")
                    ss.append(f"  {self.local_din} <= {{{{{self.ghostbus['dw']}-({ram.range[0]}+1){{1'b0}}}}, {branch}_{ram.name}_r}};")
                    ss.append("end")
            num_rams += len(rams)
        if num_rams == 0:
            return "// No block-scope RAMs"
        return "\n".join(ss)

    def busHookup(self, extmod, parent=None):
        """Create code to attach an extmod (ExternalModule) to a ghostbus."""
        if parent is None:
            ghostbus = extmod.ghostbus
        else:
            ghostbus = parent.ghostbus
        ss = []
        for portname, ext_port in extmod.extbus.outputs_and_clock().items():
            if ext_port is None:
                continue
            gb_port = ghostbus[portname]
            if (ext_port == extmod.extbus._bus["addr"][0]) and (extmod.aw != extmod.true_aw):
                # Oddball case of 'addr' doesn't fit the pattern
                # From:
                #   assign extmod_addr = GBPORT_addr[aw-1:0];
                # To:
                #   assign extmod_addr = {{true_aw-aw{1'b0}}, GBPORT_addr[aw-1:0]};
                true_aw_str = extmod.extbus.get_width(portname)
                ss.append(f"assign {ext_port} = {{{{{true_aw_str}-{extmod.aw}{{1'b0}}}}, {gb_port}[{extmod.aw}-1:0]}};")
            else:
                #print(f"  portname = {portname}; ext_port = {ext_port}; gb_port = {gb_port}")
                _range = extmod.extbus.get_range(portname)
                if _range is not None:
                    _s, _e = _range
                    ss.append(f"assign {ext_port} = {gb_port}[{_s}:{_e}];")
                elif portname in ('wen', 'ren', 'wstb', 'rstb'):
                    ss.append(f"assign {ext_port} = {gb_port} & addrhit_{extmod.name};")
                else:
                    ss.append(f"assign {ext_port} = {gb_port};")
        return "\n".join(ss)

    def blockDecoding(self):
        dd = {} # {branch: decodestring}
        # CSRs
        for branch, csrs in self.block_csrs.items():
            if dd.get(branch) is None:
                dd[branch] = []
            ss = []
            for csr in csrs:
                if csr.genblock.isIf():
                    continue
                index = csr.genblock.index
                ss.append(f"// CSR {csr.name}")
                ss.append("initial begin")
                ss.append(f"  {branch}_{csr.name}_w[{index}] = {csr.name};")
                ss.append("end")
                ss.append(f"always @({csr.name} or {branch}_{csr.name}_w[{index}]) begin")
                ss.append(f"  {branch}_{csr.name}_r[{index}] <= {csr.name};")
                ss.append(f"  {csr.name} <= {branch}_{csr.name}_w[{index}];")
                ss.append("end")
            dd[branch].extend(ss)
        # RAMs
        for branch, rams in self.block_rams.items():
            if dd.get(branch) is None:
                dd[branch] = []
            ss = []
            for ram in rams:
                if ram.genblock.isIf():
                    continue
                index = csr.genblock.index
                rangestr = f"[{ram.range[0]}:{ram.range[1]}]"
                sizestr = csr.size_str
                awstr = f"{branch.upper()}_{csr.name.upper()}_AW"
                ss.append(f"// RAM {ram.name}")
                awdiff = self.ghostbus.aw - ram.aw
                gbah = self.ghostbus.get_range('addr')[0]
                ramname = f"{branch}_{ram.name}"
                ss.append(f"assign addrhit_{ramname}[{index}] = {self.ghostbus['addr']}[{gbah}:{ram.aw}] == {vhex(ram.base>>ram.aw, awdiff)} + {index}[{awdiff}-1:0];")
                ss.append(f"assign {ramname}_r[(({index}+1)*{sizestr})-1-:{sizestr}] = {ram.name}[{self.ghostbus['addr']}[{awstr}-1:0]];")
                ss.append(f"always @(posedge {self.ghostbus['clk']}) begin")
                ss.append(f"  if (addrhit_{ramname}[{index}] & {self.ghostbus['we']}) begin")
                ss.append(f"    {ram.name}[{self.ghostbus['addr']}[{awstr}-1:0]] <= {self.ghostbus['dout']}{rangestr};")
                ss.append( "  end")
                ss.append( "end")
            dd[branch].extend(ss)
        # Submods
        for branch, submods in self.block_submods.items():
            if dd.get(branch) is None:
                dd[branch] = []
            ss = []
            for submod in submods:
                if submod.genblock.isIf():
                    continue
                index = csr.genblock.index
                aw = submod.domains[None].mod.aw
                base = submod.domains[None].mod.base
                awdiff = self.ghostbus.aw - aw
                rangestr = f"[{ram.range[0]}:{ram.range[1]}]"
                ss.append(f"// Submodule {submod.name}")
                ss.append(f"assign addrhit_{branch}_{submod.name}[{index}] = {self.ghostbus['addr']}[{self.ghostbus.aw}-1:{aw}] == {vhex(base>>aw, awdiff)} + {index}[{awdiff}-1:0];")
            dd[branch].extend(ss)
        for key in dd.keys():
            ss = "\n".join(dd[key])
            dd[key] = ss
        # Extmods TODO
        return dd

def test_createPortBus():
    # Bus 1 is write-only
    bus1 = BusLB("one")
    bus1.set_port("clk", "one_clk", 1)
    bus1.set_port("addr", "one_addr", 24)
    bus1.set_port("dout", "one_wdata", 16)
    bus1.set_port("we", "one_we", 1)
    # This is the same net as 'we' serving dual roles, it should NOT appear
    bus1.set_port("wstb", "one_we", 1)

    # Bus 2 is read-only with a read-enable and an extra input
    bus2 = BusLB("two")
    bus2.set_port("clk", "two_clk", 1)
    bus2.set_port("addr", "two_addr", 24)
    bus2.set_port("din", "two_rdata", 16)
    bus2.set_port("re", "two_re", 1)
    bus2.set_port("extra_in0", "two_extra", 1)

    portbus = createPortBus((bus1, bus2))
    print(portbus)
    expected_ports = ("clk", "addr", "dout", "din", "we", "re", "extra_in0")

    missing = []
    busdict = portbus.get()
    for portkey in expected_ports:
        busport = busdict.get(portkey)
        if busport is None:
            missing.append(portkey)

    if len(missing) > 0:
        print(f"FAIL: missing = {missing}")
        return 1
    else:
        print("PASS")
    return 0

if __name__ == "__main__":
    test_createPortBus()
