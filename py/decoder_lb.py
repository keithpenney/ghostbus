# Ghostbus localbus-style decoder logic

import os

from memory_map import Register, MemoryRegion, bits
from gbexception import GhostbusException, GhostbusFeatureRequest
from gbmemory_map import GBMemoryRegionStager, GBRegister, GBMemory, ExternalModule, isForLoop
from util import strDict, check_complete_indices
from yoparse import block_inst
from verilogger import Verilogger
from policy import Policy


def vhex(num, width):
    """Verilog hex constant generator"""
    #print(f"num = {num}, width = {width}")
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
        self.genblock = None

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
        """Returns list of (key, portname, rangestr, _dir) for all ports used in the bus.
        where 'key' is one of self._bus_info.keys(),
        and 'portname' is the net name used for the port in the codebase,
        and 'rangestr' is the bit range as a string
        and '_dir' is one of (self._input, self._output, self._inout)"""
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
        #print(f"get_range({portname})")
        for key, value in self._derived.items():
            if portname in value:
                #print(f"  key = {key}, looking for {key}_range")
                _range = self._bus.get(key+"_range", None)
                #print(f"  _range = {_range}")
                if _range is not None:
                    return _range[0]
        #print("  Could not find!")
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
                #if name == "addr":
                #    print(f"  ############# {self.name}: setting {wparam}_range = ({rangestr}, None)")
                #    if rangestr is None:
                #        raise Exception()
                if rangestr is not None:
                    self._bus[wparam+"_range"] = (rangestr, None)
                    self._bus[wparam+"_str"] = (rangestr[0] + "+1", None)
        return

    @property
    def aw_str(self):
        return self._bus["aw_str"][0]

    @property
    def dw_str(self):
        return self._bus["dw_str"][0]

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
        # Ensure we have at least one of 'ren', 'wen', 'wstb'
        try:
            self.rw_triggers()
        except GhostbusException as gbe:
            _valid = False
            err = str(gbe)
        # Ensure we have at least one of 'wdata' or 'rdata'
        if self._bus['dout'] is None and self._bus['din'] is None:
            err = f"Bus {self.name} has no data ports (neither wdata nor rdata)"
            _valid = False
        self._valid = _valid
        #if self._bus["addr_range"] is None:
        #    self._bus["addr_range"] = f"[{self._bus['aw']}:0]"
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

    def rw_triggers(self):
        """Which signal or combination of signals determines when reads and writes occur.
        Returns (read_signal, write_signal).
        Note that 'rstb' is not considered here because it is deemed informative, not
        critical. The read strobe simply informs downstream logic that the bus controller
        has captured the 'rdata' signal (which is provided to the bus controller asynchronously
        based on the value of 'addr')."""
        wen = 0b001
        wstb= 0b010
        ren = 0b100
        _wen_sig = self['we']
        _wstb_sig = self['wstb']
        _ren_sig = self['re']
        _wen  = wen  if _wen_sig  is not None else 0
        _wstb = wstb if _wstb_sig is not None else 0
        _ren  = ren  if _ren_sig  is not None else 0
        case = _wen | _wstb | _ren
        read_signal = None
        write_signal = None
        if case == wen:
            # Use wen as 'wnr'
            write_signal = _wen_sig
            read_signal = f"!{_wen_sig}"
        elif case == wstb:
            # Use wstb as 'wnr'
            write_signal = _wstb_sig
            read_signal = f"!{_wstb_sig}"
        elif case == ren:
            # Use ren as 'rnw'
            write_signal = f"!{_ren_sig}"
            read_signal = _ren_sig
        elif case == (wen | wstb):
            # Write at wen&wstb, read at !wen
            write_signal = f"{_wen_sig} & {_wstb_sig}"
            read_signal = f"!{_wen_sig}"
        elif case == (wen | ren):
            # Write at wen; read at ren
            write_signal = _wen_sig
            read_signal = _ren_sig
        elif case == (wstb | ren):
            # Write at (!ren) & wstb. Probably safe to ignore ren, but this is safer in cases
            # of strange bus controllers.
            # Read at ren
            write_signal = f"(!{_ren_sig}) & {_wstb_sig}"
            read_signal = _ren_sig
        elif case == (wen | wstb | ren):
            # (same as wen|wstb) Write at wen&wstb
            write_signal = f"{_wen_sig} & {_wstb_sig}"
            read_signal = _ren_sig
        if None in (write_signal, read_signal):
            raise GhostbusException("Incomplete bus! Missing all of 're', 'we', and 'wstb'")
        return (read_signal, write_signal)


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
            if portname is not None and key not in portkeys:
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
            rangestr = (f"{aw}-1", '0')
        elif key in ("din", "dout"):
            portwidth = dw
            rangestr = (f"{dw}-1", '0')
        else:
            rangestr = None
            portwidth = 1
        # TODO - Replace this someday with a global NetNamer class which guarantees name collision avoidance
        # Look for 'wstb+wen' dual role
        netname = "GBPORT_" + key
        portbus.set_port(key, netname, portwidth=portwidth, rangestr=rangestr, source=None)
    return portbus

#   The "DecoderDomainLB.submods" list needs to only contain submodules in its domain because of din routing.
#   Also, DecoderLB functions as both a module and a submodule, and so has both an "outside" API and an "inside" API
#   We just need to ensure that the generated code from all the DecoderDomainLB instances is collected and exposed
#   via the "inside" API while the "outside" API is singular (one-domain always).

class DecoderLB():
    doneModules = []

    @classmethod
    def jobDone(cls, modulename):
        """Keep global track of files created so we don't repeat work.
        The 'modulename' name of the Ghostbus module (ghostmod) being analyzed.
        Each ghostmod will generate at least one file but can be encountered
        many times across the memory map (once for each instance in the project).
        """
        if modulename in cls.doneModules:
            return True
        cls.doneModules.append(modulename)
        return False

    def __init__(self, memorytree, ghostbusses, gbportbus, debug=False):
        self._debug = debug
        self.domains = {}
        self.ghostbusses = {bus.name: bus for bus in ghostbusses}
        self.GhostbusPortBus = gbportbus
        self.parent_domain = memorytree.parent_domain
        self._def_file = "defs.vh" # TODO - harmonize with DecoderDomainLB()
        self.genblock = memorytree.genblock
        self.gen_addrs = {}
        self.autogen_loop_index = "GHOSTBUS_AUTOGEN_INDEX" # TODO - Harmonize this with a singleton netname generator class
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
        self.init_veriloggers()
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
            submod = self.__class__(node, ghostbusses, self.GhostbusPortBus, debug=self._debug)
            self._handleSubmod(submod, domain, start)
        for domain, decoder in self.domains.items():
            block_submods = decoder._resolveSubmods()
            for branch, submods in block_submods.items():
                for submod in submods:
                    self.veriloggers_inst[submod.inst] = Verilogger(self._debug)

    def init_veriloggers(self):
        self.verilogger_top = Verilogger(self._debug)
        # A dict of Verilogger instances indexed by generate branch name. Each of these represents one .vh file to generate.
        self.veriloggers_block = {}
        # A dict of Verilogger instances indexed by submodule instance name. Each of these represents one .vh file to generate.
        self.veriloggers_inst = {}
        return

    def _handleSubmod(self, submod, domain, start_addr):
        if hasattr(submod, "genblock") and submod.genblock is not None:
            branch = submod.genblock.branch
            if isForLoop(submod.genblock):
                print(f"DecoderDomainLB {submod.inst} is instantiated within generate-FOR block {branch}")
                self.domains[domain].add_block_submod(branch, submod, start_addr)
                # We'll handle these later
                if branch not in self.veriloggers_block.keys():
                    self.veriloggers_block[branch] = Verilogger(self._debug)
                return
            else:
                print(f"DecoderDomainLB {submod.inst} is instantiated within generate-IF block {submod.genblock.branch}")
                # Generate-if, just strip the branch name from the submod name
                #gen_branch, instname, gen_index = block_inst(submod.inst)
                #submod.setInst(instname)
                if branch not in self.veriloggers_block.keys():
                    self.veriloggers_block[branch] = Verilogger(self._debug)
        self.veriloggers_inst[submod.inst] = Verilogger(self._debug)
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
        self._addGhostbusLive(dest_dir)
        self._addGhostPortsDef(dest_dir)
        self._GhostbusAutogen(dest_dir)
        #for domain, decoder in self.domains.items():
        #    decoder.GhostbusMagic(dest_dir)
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

    def _collectExtmods(self, extlist):
        # optional, only used for testbench magic
        for domain, decoder in self.domains.items():
            decoder._collectExtmods(extlist)
        return

    def submodInitStr(self, base_rel, parent, verilogger):
        # the declaration of ports that get hooked up in GhostbusSubmodMap
        return self.parent_domain_decoder.submodInitStr(base_rel, parent, verilogger)

    def _WriteGhostbusSubmodMap(self, dest_dir, parentname, verilogger):
        return self.parent_domain_decoder._WriteGhostbusSubmodMap(dest_dir, parentname, verilogger)

    def _GhostbusAutogen(self, dest_dir):
        """For each Ghostbus module, we will create the following files:
        * 1 top file: top-level decoding logic
        * 0 or more instance files: port connection for submod instances within a module
        * 0 or more block files: block-scope decoding logic
        Also, for a given memory structure, the same module can be traversed many times
        (depending on how many times it's instantiated).  If we did things correctly, the
        generated code will be identical for each pass, so we should only do it once.
        """
        doThis = True
        if self.jobDone(f"{self.name}"):
            doThis = False
        if doThis:
            # Global init e.g. integer GHOSTBUS_AUTOGEN_INDEX=0;
            self._globalInit()
            # First, generate own internal bus decoding code in all domains
            self._GhostbusDecoding()
            fname = f"ghostbus_{self.name}.vh"
            self.verilogger_top.write(dest_dir=dest_dir, filename=fname)
            self.parent_domain_decoder._addGhostbusDef(dest_dir, self.name)
            # Then, generate decoding logic for each block scope
            self._GhostbusBlockDecoding(dest_dir)
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
                vl = self.veriloggers_inst[submod.inst]
                if doThis:
                    submod._WriteGhostbusSubmodMap(dest_dir, self.name, vl)
                submod._GhostbusAutogen(dest_dir)
            # TODO Where are the submods instantiated in block scope?
            # oh right, decoder.block_submods # {branch_name: [], ...}
            for branch, submods in decoder.block_submods.items():
                for submod in submods:
                    vl = self.veriloggers_inst[submod.inst]
                    if doThis:
                        submod._WriteGhostbusSubmodMap(dest_dir, self.name + "_" + branch, vl)
                    submod._GhostbusAutogen(dest_dir)
        return

    @property
    def has_gens(self):
        for domain, decoder in self.domains.items():
            if decoder.has_gens:
                return True
        return False

    def _globalInit(self):
        """Some generated code needs to be done once for all domains."""
        vl = self.verilogger_top
        if self.has_gens:
            vl.add(f"integer {self.autogen_loop_index}=0;")
        return

    def _GhostbusDecoding(self):
        """Generate the bus decoding logic for this instance."""
        for domain, decoder in self.domains.items():
            decoder.topDecoding(self.verilogger_top)
        return

    def _GhostbusBlockDecoding(self, dest_dir):
        for domain, decoder in self.domains.items():
            decoder.blockDecoding(self.veriloggers_block)
        for branch, verilogger in self.veriloggers_block.items():
            fname = f"ghostbus_{self.name}_{branch}.vh"
            verilogger.write(dest_dir=dest_dir, filename=fname)
            self.parent_domain_decoder._addGhostbusDef(dest_dir, f"{self.name}_{branch}")
        return

    def _addGhostPortsDef(self, dest_dir):
        fname = "ghostbusports.vh"
        self._GhostbusPorts(dest_dir=dest_dir, filename=fname)
        macrostr = f"GHOSTBUSPORTS"
        macrodef = f"`include \"{fname}\""
        return self._addDef(dest_dir, macrostr, macrodef)

    def _GhostbusPorts(self, dest_dir, filename):
        """Generate the necessary ghostbus Verilog port declaration"""
        ghostbus = self.GhostbusPortBus
        ports = ghostbus.getPortList() # (key, name, rangestr, dir)
        vl = Verilogger(self._debug)
        vl.add("// Ghostbus ports")
        for key, portname, rangestr, _dir in ports:
            dirstr = BusLB.direction_string_periph(_dir)
            vl.add(f",{dirstr} {rangestr} {portname}")
        vl.write(filename=filename, dest_dir=dest_dir)
        return

    def ExtraVerilogTasks(self, ghostbus):
        bus = ghostbus
        aw = bus["aw"]
        dw = bus["dw"]
        atre = f"@(posedge {bus['clk']})"
        gb_write_task = (
            "// Bus transaction tasks",
            f"task GB_WRITE (input [{aw-1}:0] addr, input [{dw-1}:0] data);",
            "  begin",
            f"    {atre} {bus['addr']} = addr;",
            f"    {bus['dout']} = data;",
            #f"    @(posedge {bus['clk']}) {bus['we']} = 1'b1;",
            f"    {atre}; // Stupid simulator issues",
            f"    {bus['we']} = 1'b1;",
            f"    {bus['wstb']} = 1'b1;" if (bus['wstb'] is not None and bus['wstb'] != bus['we']) else "",
            f"    {atre}; // Stupid simulator issues",
            f"    {atre} {bus['we']} = 1'b0;",
            f"    {bus['wstb']} = 1'b0;" if (bus['wstb'] is not None and bus['wstb'] != bus['we']) else "",
            "`ifndef YOSYS",
            "`ifdef DEBUG_WRITES",
            f"       $display(\"DEBUG: Write 0x%x to addr 0x%x\", data, addr);",
            "`endif",
            "`endif",
            "  end",
            "endtask",
        )
        gb_read_task = (
            "`ifndef RDDELAY",
            "  `define RDDELAY 2",  # TODO parameterize somehow
            "`endif",
            f"task GB_READ_CHECK (input [{aw-1}:0] addr, input [{dw-1}:0] checkval);",
            "  begin",
            f"    {atre} {bus['addr']} = addr;",
            f"    {bus['dout']} = {vhex(0, dw)};",
            f"    {bus['we']} = 1'b0;",
            f"    {bus['re']} = 1'b1;" if bus['re'] is not None else "",
            "    #(`RDDELAY*TICK);",
            f"    {atre};",
            f"    {bus['rstb']} = 1'b1;" if bus['rstb'] is not None else "",
            f"    {atre} {bus['rstb']} = 1'b0;" if bus['rstb'] is not None else "",
            f"    {bus['re']} = 1'b0;" if bus['re'] is not None else "",
            "`ifndef YOSYS",
            "`ifdef DEBUG_READS",
            f"       $display(\"DEBUG: Read from addr 0x%x. Expected 0x%x, got 0x%x\", addr, checkval, {bus['din']});",
            "`endif",
            "`endif",
            f"    if ({bus['din']} !== checkval) begin",
            "       test_pass = 1'b0;",
            "`ifndef YOSYS",
            f"       $display(\"ERROR: Read from addr 0x%x. Expected 0x%x, got 0x%x\", addr, checkval, {bus['din']});",
            "`endif",
            "    end",
            "  end",
            "endtask",
        )
        gb_write_read_task = (
            "// RAM Write/Read",
            "task WRITE_READ_CHECK (input [23:0] addr, input [31:0] checkval);",
            "  begin",
            "    GB_WRITE(addr, checkval);",
            f"    {atre} GB_READ_CHECK(addr, checkval);",
            "  end",
            "endtask",
        )
        csr_read_task = (
            "// CSR Reads",
            f"task CSR_READ_CHECK_ALL;",
            "  for (LOOPN=0; LOOPN<nCSRs; LOOPN=LOOPN+1) begin",
            f"    {atre} GB_READ_CHECK(GHOSTBUS_ADDRS[LOOPN], GHOSTBUS_INITVALS[LOOPN]);",
            "  end",
            "endtask",
        )
        csr_write_task = (
            "// CSR Writes",
            f"task CSR_WRITE_ALL;",
            "  for (LOOPN=0; LOOPN<nCSRs; LOOPN=LOOPN+1) begin",
            "    if (GHOSTBUS_WRITABLE[LOOPN]) begin",
            f"      {atre} GB_WRITE(GHOSTBUS_ADDRS[LOOPN], GHOSTBUS_RANDVALS[LOOPN]);",
            f"      GHOSTBUS_INITVALS[LOOPN] = GHOSTBUS_RANDVALS[LOOPN];",
            "    end",
            "  end",
            "endtask",
        )

        csr_write_read_all_task = (
            "// CSR Write/Read All",
            "task CSR_WRITE_READ_CHECK_ALL;",
            "  for (LOOPN=0; LOOPN<nCSRs; LOOPN=LOOPN+1) begin",
            "    if (GHOSTBUS_WRITABLE[LOOPN]) begin",
            f"      {atre} WRITE_READ_CHECK(GHOSTBUS_ADDRS[LOOPN], GHOSTBUS_RANDVALS[LOOPN]);",
            "    end",
            "  end",
            "endtask",
        )

        ram_write_read_all_task = (
            "// RAM Write/Read All",
            "`ifndef MAX_RAM_CHECKS",
            "`define MAX_RAM_CHECKS 4",
            "`endif",
            "task RAM_WRITE_READ_CHECK_ALL;",
            "  for (LOOPN=0; LOOPN<nRAMs; LOOPN=LOOPN+1) begin",
            "    for (LOOPM=0; LOOPM<(GHOSTBUS_RAM_DEPTHS[LOOPN] > `MAX_RAM_CHECKS ? `MAX_RAM_CHECKS : GHOSTBUS_RAM_DEPTHS[LOOPN]); LOOPM=LOOPM+1) begin",
            "      if (GHOSTBUS_RAM_WRITABLE[LOOPN]) begin",
            f"        {atre} WRITE_READ_CHECK(GHOSTBUS_RAM_BASES[LOOPN]+LOOPM, $urandom & ((1<<GHOSTBUS_RAM_WIDTHS[LOOPN])-1));",
            "      end",
            "    end",
            "  end",
            "endtask",
        )

        ss = []
        ss.append("reg test_pass=1'b1;")
        ss.append("integer LOOPN;")
        ss.append("integer LOOPM;")
        ss.extend(gb_write_task)
        ss.extend(gb_read_task)
        ss.extend(gb_write_read_task)
        ss.extend(csr_read_task)
        ss.extend(csr_write_task)
        ss.extend(csr_write_read_all_task)
        ss.extend(ram_write_read_all_task)
        return "\n".join(ss)

    def ExtraVerilogMemoryMap(self, ghostbus):
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
            reg [nRAMs-1:0] GHOSTBUS_RAM_WRITABLE;
        """
        import random
        def flatten_bits(ll):
            v = 0
            for n in range(len(ll)):
                if ll[n]:
                    v |= (1<<n)
            return v
        bus = ghostbus
        aw = bus["aw"]
        dw = bus["dw"]
        csrs = []
        rams = []
        exts = []
        self._collectCSRs(csrs)
        self._collectRAMs(rams)
        self._collectExtmods(exts)
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
        print("Extmods:")
        ext_writeable = []
        for ext in exts:
            print("{}.{}: 0x{:x}".format(ext._domain[1], ext.name, ext._domain[0] + ext.base))
            wa = 1 if (ext.access & ext.WRITE) > 0 else 0
            ext_writeable.append(wa)
        ew = flatten_bits(ext_writeable)
        nCSRs = len(csrs)
        nRAMs = len(rams)
        ram_names = []
        for n in range(len(rams)):
            ram = rams[n]
            name = f"{ram._domain[1].replace('.', '_')}_{ram.name.replace('.', '_')}"
            ram_names.append(f"localparam {name.upper()}_BASE = {vhex(ram._domain[0] + ram.base, 32)}; // {ram._domain[1]}.{ram.name}")
        ext_names = []
        for n in range(len(exts)):
            ext = exts[n]
            name = f"{ext._domain[1].replace('.', '_')}_{ext.name.replace('.', '_')}"
            ext_names.append(f"localparam {name.upper()}_BASE = {vhex(ext._domain[0] + ext.base, 32)}; // {ext._domain[1]}.{ext.name}")
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
        ]
        ss.append("// RAMs by name")
        ss.extend(ram_names)
        ss.append("// External Modules by name")
        ss.extend(ext_names)
        ss.append("// Initialization")
        ss.append("initial begin")
        # Initialize CSR info
        for n in range(len(csrs)):
            csr = csrs[n]
            ss.append(f"  GHOSTBUS_ADDRS[{n}] = {vhex(csr._domain[0] + csr.base, aw)}; // {csr._domain[1]}.{csr.name}")
            ss.append(f"  GHOSTBUS_INITVALS[{n}] = {vhex(csr.initval, dw)};")
            randval = random.randint(0, (1<<csr.dw)-1) # Random number within the range of the CSR's width
            ss.append(f"  GHOSTBUS_RANDVALS[{n}] = {vhex(randval, dw)}; // 0 <= x <= 0x{(1<<csr.dw) - 1:x}")
        # Initialize RAM info
        for n in range(len(rams)):
            ram = rams[n]
            ss.append(f"  GHOSTBUS_RAM_BASES[{n}] = {vhex(ram._domain[0] + ram.base, aw)}; // {ram._domain[1]}.{ram.name}")
            ss.append(f"  GHOSTBUS_RAM_WIDTHS[{n}] = {vhex(ram.dw, dw)}; // TODO - may not be accurate due to parameterization...")
            ss.append(f"  GHOSTBUS_RAM_DEPTHS[{n}] = {vhex((1<<ram.aw), aw)}; // TODO - may not be accurate due to parameterization...")
        #ss.append("  end")
        ss.append("end")
        return "\n".join(ss)

    def ExtraVerilogTestbench(self, filename, ghostbusses):
        # TODO - Enable all the ghostbusses
        ghostbus = ghostbusses[0]
        ss = []
        # GB Memory Map
        ss.append(self.ExtraVerilogMemoryMap(ghostbus))
        # GB Tasks
        ss.append(self.ExtraVerilogTasks(ghostbus))
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
        self._no_reads = False # Assume True and prove me wrong by finding something readable
        self._parseMemoryRegion(memregion)

        if self.max_local == 0:
            self.has_local_csrs = False
        else:
            self.has_local_csrs = True
        self.local_aw = bits(self.max_local)
        self._def_file = "defs.vh"
        self.check_bus()
        # Net names for universal auto-generated nets
        self.en_local = "ghostbus_addrhit_local" # TODO - Harmonize this with a per-module netname generator class
        self.local_din = "ghostbus_rdata_local"  # TODO - Harmonize this with a per-module netname generator class
        self.autogen_loop_index = self.parent.autogen_loop_index

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
                    print(f"ExternalModule {ref.name} is instantiated at 0x{start:x} ?== 0x{ref.base:x} within generate block {ref.genblock.branch}")
                    # BUBBLES - The relative address 'start' is available here.  Do I need to store it for future use, or is extmod.base equivalent?
                    if self.block_exts.get(ref.genblock.branch) is None:
                        self.block_exts[ref.genblock.branch] = []
                    self.block_exts[ref.genblock.branch].append(ref)
                else:
                    #print(f"ExternalModule {ref.name} is at the top level")
                    self.exts.append((start, ref))
            if isinstance(ref, GBRegister): # Only CSRs are local now
                if stop > self.max_local:
                    #print(f"    =============== {self.name}: max_local {self.max_local} -> {stop} (ref.name = {ref.name})")
                    self.max_local = stop
        return

    @property
    def has_gens(self):
        if len(self.block_csrs) > 0 or len(self.block_rams) > 0 or len(self.block_exts) > 0:
            return True
        return False

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
        return block_submods

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
        self._bus_re, self._bus_we = self.ghostbus.rw_triggers()
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
        for branch, csrs in self.block_csrs.items():
            for csr in csrs:
                if csr.genblock.isFor():
                    # If the CSR is in a FOR loop, I need to unroll it here
                    base = csr.base
                    #print(f"CSR {csr.name} in FOR loop of loop_len {csr.genblock.loop_len} from 0x{csr.base:x}")
                    for n in range(csr.genblock.loop_len):
                        copy = csr.copy()
                        copy.base = base + n
                        copy._domain = (self.base, f"{self.mod.name}_{branch}_{n}")
                        csrlist.append(copy)
                else:
                    # CSRs in IF block just go in like normal
                    copy = csr.copy()
                    copy._domain = (self.base, f"{self.mod.name}_{branch}")
                    csrlist.append(copy)
        for base, submod in self.submods:
            submod._collectCSRs(csrlist)
        # TODO: include submods in generate blocks
        return csrlist

    def _collectRAMs(self, ramlist):
        for ram in self.rams:
            # Need to copy because multiple module instances actually reference the same "Register" instances
            copy = ram.copy()
            # Adding attribute!
            copy._domain = (self.base, self.mod.name)
            ramlist.append(copy)
        for branch, rams in self.block_rams.items():
            for ram in rams:
                copy = ram.copy()
                copy._domain = (self.base, f"{self.mod.name}_{branch}")
                ramlist.append(copy)
        for base, submod in self.submods:
            submod._collectRAMs(ramlist)
        # TODO: include submods in generate blocks
        return ramlist

    def _collectExtmods(self, extlist):
        for base, extmod in self.exts:
            copy = extmod.copy()
            # Adding attribute!
            copy._domain = (self.base, self.mod.name)
            extlist.append(copy)
        for branch, exts in self.block_exts.items():
            for ext in exts:
                copy = ext.copy()
                copy._domain = (self.base, f"{self.mod.name}_{branch}")
                extlist.append(copy)
        for base, submod in self.submods:
            submod._collectExtmods(extlist)
        # TODO: include submods in generate blocks
        return extlist

    def _WriteGhostbusSubmodMap(self, dest_dir, parentname, verilogger):
        fname = f"ghostbus_{parentname}_{self.inst}.vh"
        self._GhostbusSubmodMap(verilogger)
        verilogger.write(dest_dir=dest_dir, filename=fname)
        self._addGhostbusDef(dest_dir, f"{parentname}_{self.inst}")
        return

    def _GhostbusSubmodMap(self, verilogger):
        """Generate the necessary ghostbus Verilog port map for this instance
        within its parent module.
        This will hook up all nets in the ghostbus, even if they are not used
        in this particular domain.  The nets are declared in submodInitStr()."""
        vl = verilogger
        portlist = self.gbportbus.getPortList() # (key, name, rangestr, dirstr)
        for port in portlist:
            portkey, portname, rangestr, _dir = port
            if len(rangestr):
                rangestr = " " + rangestr
            dirstr = BusLB.direction_string_periph(_dir)
            sel = ""
            if portkey not in ('clk', 'addr', 'dout') and isForLoop(self.genblock):
                index = self.genblock.index
                dw = self.gbportbus['dw']
                if portkey == 'din':
                    sel = f"[(({index}+1)*{dw})-1-:{dw}]"
                else:
                    sel = f"[{index}]"
            vl.add(f",.{portname}({portname}_{self.inst}{sel}) // {dirstr}{rangestr}")
        return

    def topDecoding(self, verilogger):
        self._vl = verilogger
        self.localInit()
        self.submodsTopInit()
        self.extmodsTopInit()
        self.dinRouting()
        self.busDecoding()
        return

    def localInit(self):
        # wire en_local = gb_addr[11:9] == 3'b000; // 0x000-0x1ff
        # reg  [31:0] local_din=0;
        en_local = self.en_local
        local_din = self.local_din
        if self.domain is not None:
            en_local += "_" + self.domain
            local_din += "_" + self.domain
        busaw = self.ghostbus.aw
        divwidth = busaw - self.local_aw
        vl = self._vl
        vl.comment(f"Local Initialization")
        if self.has_local_csrs:
            vl.add(f"wire {en_local} = {self.ghostbus['addr']}[{busaw-1}:{self.local_aw}] == {vhex(0, divwidth)}; // 0x0-0x{(1<<self.local_aw)-1:x}")
            vl.add(f"reg  [{self.ghostbus['dw']-1}:0] {local_din}=0;")
        if len(self.rams) > 0:
            vl.comment("Local RAMs")
            for n in range(len(self.rams)):
                vl.add(self._ramInit(self.rams[n]))
        self.localBlockInit()
        return

    def localBlockInit(self):
        vl = self._vl
        any_block = False
        for branch, csrs in self.block_csrs.items():
            if len(csrs) == 0:
                continue
            if not any_block:
                vl.comment("CSRs in block scope")
                any_block = True
            vl.comment(f"Generate Block {branch}")
            for csr in csrs:
                vl.add(self._blockCsrInit(csr, branch))
        any_block = False
        for branch, rams in self.block_rams.items():
            if len(rams) == 0:
                continue
            if not any_block:
                vl.comment("RAMs in block scope")
                any_block = True
            vl.comment(f"Generate Block {branch}")
            for ram in rams:
                vl.add(self._blockRamInit(ram, branch))
        return

    def submodsTopInit(self):
        vl = self._vl
        for base, submod in self.submods:
            #vl.add(submod.submodInitStr(base, self, self._vl))
            submod.submodInitStr(base, self, vl)

        for branch, submods in self.block_submods.items():
            vl.comment(f"Branch {branch}")
            for submod in submods:
                #vl.add(submod.submodInitStr(None, self, self._vl))
                submod.submodInitStr(None, self, self._vl)
        return

    def extmodsTopInit(self):
        vl = self._vl
        if len(self.exts) == 0:
            #print(f"  {self.name} No External Modules")
            pass
        for base_rel, ext in self.exts:
            #print(f"  {self.name} External Module Instance {ext.name}; {base_rel}")
            vl.comment(f"External Module Instance {ext.name}")
            vl.add(self._addrHit(base_rel, ext, self))
            self.busHookup(ext, vl, self)
        any_block = False
        for branch, exts in self.block_exts.items():
            if len(exts) == 0:
                continue
            if not any_block:
                vl.comment("Extmods in block scope")
                any_block = True
            vl.comment(f"Generate Block {branch}")
            for ext in exts:
                print(f"  {self.name} Block-Scope External Module Instance {ext.name} in branch {branch}")
                self._blockExtInit(ext, branch, vl)
        return

    def _ramInit(self, ram):
        # localparam FOO_RAM_AW = $clog2(RD);
        # wire addrhit_foo_ram = gb_addr[8:3] == 6'b001000;
        # reg [DW-1:0] foo_ram_registered_read=0;
        local_aw = self.ghostbus['aw']
        divwidth = local_aw - ram.aw
        end = ram.base + (1<<ram.aw) - 1
        dw = ram.size_str
        ss = [
            f"localparam {ram.name.upper()}_AW = $clog2({ram.depth_str}); // must resolve to <={ram.aw} or upper regions will be inaccessible",
            f"wire addrhit_{ram.name} = {self.ghostbus['addr']}[{local_aw-1}:{ram.aw}] == {vhex(ram.base>>ram.aw, divwidth)}; // 0x{ram.base:x}-0x{end:x}",
        ]
        if Policy.registered_rams:
            ss.append(f"reg [{dw}-1:0] {ram.name}_registered_read=0;") # TODO - harmonize in per-module net namer class
        else:
            ss.append(f"wire [{dw}-1:0] {ram.name}_registered_read = " \
                    + f"{{{{{self.ghostbus['dw']}-{ram.size_str}{{1'b0}}}}, {ram.name}[{self.ghostbus['addr']}[{ram.name.upper()}_AW-1:0]]}};")
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
        local_aw = self.ghostbus['aw']
        divwidth = local_aw - ram.aw
        base_rel = ram.base
        end = base_rel + (1<<ram.aw) - 1
        if None in ram.range:
            rangestr = ""
        else:
            rangestr = f"[{ram.range[0]}:{ram.range[1]}] "
            addrhit = f"wire addrhit_{branch}_{ram.name} = {self.ghostbus['addr']}[{local_aw-1}:{ram.aw}] == {vhex(ram.base>>ram.aw, divwidth)};" \
                    + f" // 0x{base_rel:x}-0x{end:x}"
            if ram.genblock.isFor():
                rangestr = ram.genblock.unrollRangeString(rangestr) + " "
                addrhit_range = f"[{ram.genblock.unrolled_size}-1:0] "
                addrhit = f"wire {addrhit_range}addrhit_{branch}_{ram.name};"
        ss = []
        ss.append(f"wire {rangestr}{branch}_{ram.name}_r;")
        if Policy.registered_rams:
            ss.append(f"reg {rangestr}{branch}_{ram.name}_registered_read=0;")
        else:
            ss.append(f"wire {rangestr}{branch}_{ram.name}_registered_read = {branch}_{ram.name}_r;")
        ss.extend([
            f"localparam {branch.upper()}_{ram.name.upper()}_AW = $clog2({ram.depth[1]}+1);",
            addrhit,
        ])
        return "\n".join(ss)

    def _blockExtInit(self, extmod, branch, verilogger):
        vl = verilogger
        vl.comment(f"Extmod {extmod.name}")
        base_rel = extmod.base # BUBBLES Is this right? Or does extmod.base store the global/absolute address?
        if extmod.genblock.isFor():
            pass # TODO
        else:
            vl.add(self._addrHit(base_rel, extmod, self))
            dw_range = extmod.extbus["dw_range"]
            #dw_range = self.ghostbus["dw_range"]
            rangestr = f"[{dw_range[0]}:{dw_range[1]}]"
            vl.add(f"wire {rangestr} {extmod.name}_rdata_topscope;")
        return

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

    def submodInitStr(self, base_rel, parent, verilogger):
        """Declare and assign the nets required to attach a submod to the ghostbus.
        'parent' is the module in which the submodule is instantiated.
        For a multi-domain codebase, it's possible that parent.ghostbus does not use all
        the nets in the ghostbus.  In this case, unused nets are still declared.
        Unused inputs into the submod are tied low (assigned to 0).
        """
        vl = verilogger
        parentbus = parent.ghostbus
        gbports = self.gbportbus
        addrMask = self._addrMask(self, parent)
        #ss = [f"// submodule {self.inst}"]
        vl.comment(f"submodule {self.inst}")
        # If this is in a For-Loop, addrHit needs to be declared here as a vector then assigned within the loop
        loopsize = ""
        loopvector = ""
        branch = ""
        if isForLoop(self.genblock):
            loopsize = self.genblock.unrolled_size
            loopvector = f"[{loopsize}-1:0] "
            branch = self.genblock.branch
            #ss.append(f"wire {loopvector} addrhit_{branch}_{self.inst};")
            vl.add(f"wire {loopvector} addrhit_{branch}_{self.inst};")
        else:
            addrHit = self._addrHit(base_rel, self, parent)
            #ss.append(addrHit)
            vl.add(addrHit)
        netlist = self.gbportbus.getPortList() # (key, name, rangestr, dirstr)
        for net in netlist:
            netkey, netname, rangestr, _dir = net
            if netkey == "addr":
                #ss.append(addrMask)
                vl.add(addrMask)
                continue
            # If net is unused in parentbus
            if parentbus[netkey] is None:
                # If it's an input to the submod (host-centric output)
                if _dir == BusLB._output:
                    # Wire to 0
                    #ss.append(f"wire {rangestr}{gbports[netkey]}_{self.inst} = 0; // (unused submod input)")
                    vl.add(f"wire {rangestr}{gbports[netkey]}_{self.inst} = 0; // (unused submod input)")
                else:
                    #ss.append(f"wire {rangestr}{gbports[netkey]}_{self.inst}; // (unused submod output)")
                    vl.add(f"wire {rangestr}{gbports[netkey]}_{self.inst}; // (unused submod output)")
            else:
                if len(rangestr):
                    rangestr += " "
                if netkey in ('clk', 'addr', 'dout'):
                    #ss.append(f"wire {rangestr}{gbports[netkey]}_{self.inst} = {parentbus[netkey]};")
                    vl.add(f"wire {rangestr}{gbports[netkey]}_{self.inst} = {parentbus[netkey]};")
                elif netkey in ('we', 'wstb', 're', 'rstb'):
                    if loopsize == "":
                        pbk = f"{parentbus[netkey]}"
                    else:
                        pbk = f"{{{loopsize}{{{parentbus[netkey]}}}}}"
                        rangestr = loopvector
                    inst = self.inst
                    if len(branch) > 0:
                        inst = f"{branch}_{self.inst}"
                    #ss.append(f"wire {rangestr}{gbports[netkey]}_{self.inst} = {pbk} & addrhit_{inst};")
                    vl.add(f"wire {rangestr}{gbports[netkey]}_{self.inst} = {pbk} & addrhit_{inst};")
                elif netkey in ('din',):
                    if isForLoop(self.genblock):
                        rangestr = self.genblock.unrollRangeString(rangestr) + " "
                    #ss.append(f"wire {rangestr}{gbports[netkey]}_{self.inst};")
                    vl.add(f"wire {rangestr}{gbports[netkey]}_{self.inst};")
                else:
                    #ss.append(f"wire {rangestr}{gbports[netkey]}_{self.inst} = {parentbus[netkey]}; // extra port?")
                    vl.add(f"wire {rangestr}{gbports[netkey]}_{self.inst} = {parentbus[netkey]}; // extra port?")
        #return "\n".join(ss)
        return

    def dinRouting(self):
        # assign gb_din = en_baz_0 ? gb_din_baz_0 :
        #                 en_bar_0 ? gb_din_bar_0 :
        #                 en_local ? local_din :
        #                 32'h00000000;
        if self._no_reads:
            return
        if self.ghostbus["din"] is None:
            return
        en_local = self.en_local
        local_din = self.local_din
        if self.domain is not None:
            en_local += "_" + self.domain
            local_din += "_" + self.domain
        portdict = self.gbportbus
        namemap = self.ghostbus
        vl = self._vl
        vl.comment("din routing")
        vl.add(f"assign {namemap['din']} =")
        for n in range(len(self.rams)):
            ram = self.rams[n]
            vl.add(f"  addrhit_{ram.name} ? {ram.name}_registered_read :")
        for branch, rams in self.block_rams.items():
            for ram in rams:
                vl.add(f"  addrhit_{branch}_{ram.name} ? {branch}_{ram.name}_registered_read :")
        for n in range(len(self.submods)):
            base, submod = self.submods[n]
            inst = submod.inst
            vl.add(f"  addrhit_{inst} ? {portdict['din']}_{inst} :")
        for n in range(len(self.exts)):
            base_rel, ext = self.exts[n]
            if not ext.access & Register.READ:
                # Skip non-readable ext modules
                continue
            inst = ext.name
            gb_dwstr = self.ghostbus.dw_str
            dwstr = ext.extbus.dw_str
            din = ext.extbus['din']
            vl.add(f"  addrhit_{inst} ? {{{{{gb_dwstr}-{dwstr}{{1'b0}}}}, {din}}} :")
        for branch, extmods in self.block_exts.items():
            for ext in extmods:
                if not ext.access & Register.READ:
                    # Skip non-readable ext modules
                    continue
                gb_dwstr = self.ghostbus.dw_str
                ext_dwstr = ext.extbus.dw_str
                din = f"{ext.name}_rdata_topscope"
                vl.add(f"  addrhit_{ext.name} ? {{{{{gb_dwstr}-{ext_dwstr}{{1'b0}}}}, {din}}} :")
        if self.has_local_csrs:
            vl.add(f"  {en_local} ? {local_din} :")
        vl.add(f"  {vhex(0, self.ghostbus['dw'])};")
        return

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
        if len(_ramreads) == 0:
            ramreads = "// No rams"
        else:
            ramreads = _ramreads
        _csrreads, rdefaults = self.csrReads()
        if len(_csrreads) == 0:
            csrreads = "// No CSRs"
        else:
            csrreads = _csrreads
        hasclk = False
        csrdefaults.extend(wdefaults)
        csrdefaults.extend(rdefaults)
        namemap = self.ghostbus
        local_din = self.local_din
        if self.domain is not None:
            local_din += "_" + self.domain
        vl = self._vl
        if len(_ramwrites) > 0 or len(_csrwrites) > 0:
            hasclk = True
            vl.always_at_clk(f"{namemap['clk']}")
            if self.has_local_csrs:
                vl.add(f"{local_din} <= 0;")
            if len(csrdefaults) > 0:
                vl.comment("Strobe default assignments")
            for strobe in csrdefaults:
                if hasattr(strobe, "name"):
                    vl.add(f"{strobe.name} <= {vhex(0, strobe.dw)};")
                else:
                    vl.add(f"{strobe} <= {vhex(0, 1)};")
            vl.comment("Local writes")
            vl._if(f"{self._bus_we}")
            if self.has_local_csrs:
                vl._if(f"{en_local}")
                vl.add(csrwrites)
                vl.end(f"if ({en_local})")
            vl.add(ramwrites)
            vl.end(f"if ({self._bus_we})")
        if len(_ramreads) > 0 or len(_csrreads) > 0:
            if not hasclk:
                hasclk = True
                vl.always_at_clk(f"{namemap['clk']}")
            vl.comment("Local reads")
            vl._if(f"{self._bus_re}")
            if self.has_local_csrs:
                vl._if(f"{en_local}")
                vl.add(csrreads)
                vl.end(f"if ({en_local})")
            vl.add(ramreads)
            vl.end(f"if ({self._bus_re})")
        if hasclk:
            vl.end(f"always @(posedge {namemap['clk']})")
        return

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
        local_din = self.local_din
        if self.domain is not None:
            local_din += "_" + self.domain
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
                ss.append(f"    {local_din} <= {{{{{self.ghostbus['dw']}-({csr.range[0]}+1){{1'b0}}}}, {branch}_{csr.name}_r[{agi}]}};")
                #ss.append(f"    {local_din} <= {{32-(3+1){1'b0}}, {branch}_{csr.name}_r[{agi}]};")
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
        if not Policy.registered_rams:
            return ""
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
            ss.append(f"  {ram.name}_registered_read <= {{{{{self.ghostbus['dw']}-{ram.size_str}{{1'b0}}}}, {ram.name}[{self.ghostbus['addr']}[{ram.name.upper()}_AW-1:0]]}};")
            ss.append("end")
        genrams = self.genRamReads()
        if len(genrams) > 0:
            ss.append(genrams)
        return "\n".join(ss)

    def genRamReads(self):
        """Return read-decoding for RAMs declared in generate-for block scope."""
        if not Policy.registered_rams:
            return ""
        ss = []
        num_rams = 0
        #// Generate RAMs
        #// foo_generator.foo_ram
        #for (AUTOGEN_INDEX=0; AUTOGEN_INDEX<FOO_COPIES; AUTOGEN_INDEX=AUTOGEN_INDEX+1) begin
        #  if (addrhit_foo_ram[AUTOGEN_INDEX]) begin
        #    local_din <= {{32-(3+1){1'b0}}, foo_generator_foo_ram_r[((AUTOGEN_INDEX+1)*8)-1-:8]};
        #  end
        #end
        #local_din = self.local_din
        #if self.domain is not None:
        #    local_din += "_" + self.domain
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
                    read_dest = f"{branch}_{ram.name}_registered_read"
                    depth = f"({ram.depth[1]}+1)"
                    ss.append(f"  // {ram.name}")
                    ss.append(f"  if (addrhit_{branch}_{ram.name}[{agi}]) begin")
                    ss.append(f"    {read_dest} <= {{{{{self.ghostbus['dw']}-({ram.range[0]}+1){{1'b0}}}}, {branch}_{ram.name}_r[(({agi}+1)*{depth})-1-:{depth}]}};")
                    ss.append( "  end")
                ss.append("end")
            else:
                # Generate-If
                for ram in rams:
                    ss.append(f"// {ram.name}")
                    read_dest = f"{branch}_{ram.name}_registered_read"
                    ss.append(f"if (addrhit_{branch}_{ram.name}) begin")
                    ss.append(f"  {read_dest} <= {{{{{self.ghostbus['dw']}-({ram.range[0]}+1){{1'b0}}}}, {branch}_{ram.name}_r}};")
                    ss.append("end")
            num_rams += len(rams)
        if num_rams == 0:
            return ""
        return "\n".join(ss)

    def busHookup(self, extmod, verilogger, parent=None):
        """Create code to attach an extmod (ExternalModule) to a ghostbus."""
        if parent is None:
            ghostbus = extmod.ghostbus
        else:
            ghostbus = parent.ghostbus
        #ss = []
        vl = verilogger
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
                #ss.append(f"assign {ext_port} = {{{{{true_aw_str}-{extmod.aw}{{1'b0}}}}, {gb_port}[{extmod.aw}-1:0]}};")
                vl.add(f"assign {ext_port} = {{{{{true_aw_str}-{extmod.aw}{{1'b0}}}}, {gb_port}[{extmod.aw}-1:0]}};")
            else:
                #print(f"  portname = {portname}; ext_port = {ext_port}; gb_port = {gb_port}")
                _range = extmod.extbus.get_range(portname)
                if _range is not None:
                    _s, _e = _range
                    #ss.append(f"assign {ext_port} = {gb_port}[{_s}:{_e}];")
                    vl.add(f"assign {ext_port} = {gb_port}[{_s}:{_e}];")
                elif portname in ('we', 're', 'wstb', 'rstb'):
                    vl.add(f"assign {ext_port} = {gb_port} & addrhit_{extmod.name};")
                else:
                    vl.add(f"assign {ext_port} = {gb_port};")
        #return "\n".join(ss)
        return

    def blockDecoding(self, verilogger_dict):
        # CSRs
        for branch, csrs in self.block_csrs.items():
            vl = verilogger_dict[branch]
            for csr in csrs:
                vl.comment(f"CSR {csr.name}")
                if csr.genblock.isIf():
                    vl.initial()
                    vl.add(f"{branch}_{csr.name}_w = {csr.name};")
                    vl.end()
                    vl.always_at(f"{csr.name} or {branch}_{csr.name}_w")
                    vl.add(f"{csr.name} <= {branch}_{csr.name}_w;")
                    vl.add(f"{branch}_{csr.name}_r <= {csr.name};")
                    vl.end()
                else:
                    index = csr.genblock.index
                    vl.initial()
                    vl.add(f"{branch}_{csr.name}_w[{index}] = {csr.name};")
                    vl.end()
                    vl.always_at(f"{csr.name} or {branch}_{csr.name}_w[{index}]")
                    vl.add(f"{branch}_{csr.name}_r[{index}] <= {csr.name};")
                    vl.add(f"{csr.name} <= {branch}_{csr.name}_w[{index}];")
                    vl.end()
        # RAMs
        gbah = self.ghostbus.get_range('addr')[0]
        for branch, rams in self.block_rams.items():
            vl = verilogger_dict[branch]
            for ram in rams:
                vl.comment(f"RAM {ram.name}")
                ramname = f"{branch}_{ram.name}"
                rangestr = f"[{ram.range[0]}:{ram.range[1]}]"
                sizestr = ram.size_str
                awdiff = self.ghostbus.aw - ram.aw
                awstr = f"{branch.upper()}_{ram.name.upper()}_AW"
                if ram.genblock.isIf():
                    vl.add(f"assign {branch}_{ram.name}_r = {ram.name}[{self.ghostbus['addr']}[{awstr}-1:0]];")
                    vl.always_at_clk(f"{self.ghostbus['clk']}")
                    vl._if(f"addrhit_{ramname} & {self._bus_we}")
                    vl.add(f"{ram.name}[{self.ghostbus['addr']}[{awstr}-1:0]] <= {self.ghostbus['dout']}{rangestr};")
                    vl.end()
                    vl.end()
                else:
                    index = ram.genblock.index
                    cmt = f"0x{ram.base:x}-0x{ram.base+(1<<ram.aw)-1:x} (+{index}*0x{1<<ram.aw:x})"
                    vl.add(f"assign addrhit_{ramname}[{index}] = {self.ghostbus['addr']}[{gbah}:{ram.aw}] == {vhex(ram.base>>ram.aw, awdiff)} + {index}[{awdiff}-1:0];",
                           comment=cmt)
                    vl.add(f"assign {ramname}_r[(({index}+1)*{sizestr})-1-:{sizestr}] = {ram.name}[{self.ghostbus['addr']}[{awstr}-1:0]];")
                    vl.always_at_clk(f"{self.ghostbus['clk']}")
                    #vl._if(f"addrhit_{ramname}[{index}] & {self.ghostbus['we']}")
                    vl._if(f"addrhit_{ramname}[{index}] & {self._bus_we}")
                    vl.add(f"{ram.name}[{self.ghostbus['addr']}[{awstr}-1:0]] <= {self.ghostbus['dout']}{rangestr};")
                    vl.end()
                    vl.end()
        # Submods
        for branch, submods in self.block_submods.items():
            vl = verilogger_dict[branch]
            for submod in submods:
                if submod.genblock.isIf():
                    continue
                index = csr.genblock.index
                aw = submod.domains[None].mod.aw
                base = submod.domains[None].mod.base
                awdiff = self.ghostbus.aw - aw
                rangestr = f"[{ram.range[0]}:{ram.range[1]}]"
                vl.comment(f"Submodule {submod.name} {submod.inst}")
                # TODO - This needs to be the submod instance, not the module name!
                vl.add(f"assign addrhit_{branch}_{submod.inst}[{index}] = {self.ghostbus['addr']}[{self.ghostbus.aw}-1:{aw}] == {vhex(base>>aw, awdiff)} + {index}[{awdiff}-1:0];")
        # Extmods TODO
        for branch, extmods in self.block_exts.items():
            vl = verilogger_dict[branch]
            for extmod in extmods:
                if extmod.genblock.isFor():
                    pass # TODO
                else:
                    vl.comment("Extmod extmod_bar")
                    self.busHookup(extmod, vl, self)
                    if extmod.extbus['din'] is not None: # Recall, some extmods are write-only
                        #vl.add(f"assign {extmod.name}_rdata_topscope = {{{{{self.ghostbus['dw']-extmod.dw}{{1'b0}}}}, {extmod.extbus['din']}}};")
                        vl.add(f"assign {extmod.name}_rdata_topscope = {extmod.extbus['din']};")
        return

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
