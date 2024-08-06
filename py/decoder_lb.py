# Ghostbus localbus-style decoder logic

import os

from memory_map import Register, MemoryRegion, bits
from gbexception import GhostbusException
from util import enum, strDict, print_dict


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
        "clk":      ((),  mandatory, _clk),
        "addr":     ((), mandatory, _output),
        "din":      (("rdata",),  mandatory, _input),
        "dout":     (("wdata",), mandatory, _output),
        "we":       (("wen",), mandatory, _output),
        "re":       (("ren",), optional, _output),
        "wstb":     (("write_strobe",), optional, _output),
        "rstb":     (("read_strobe",), optional, _output),
    }
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

    def __init__(self):
        self._bus = {}
        for key, data in self._bus_info.items():
            self._bus[key] = None
        # Add derived parameters
        for key in self._derived.keys():
            self._bus[key] = None
        # A few more bespoke parameters (see self._set_width)
        self._bus['aw_str'] = None
        self._bus['dw_str'] = None
        # Is this a fully-defined bus? See self.validate
        self._valid = False
        self._base = None

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

    @property
    def base(self):
        return self._base

    @base.setter
    def base(self, _base):
        if self._base is not None and _base != self._base:
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
            if portname in value and hasattr(self, key+"_str"):
                return getattr(self, key+"_str")
        return None

    def __getitem__(self, key):
        return self._bus.__getitem__(key)[0]

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
            print(f"Matched input: {portname}")
            return (cls._input, portname)
        _match = re.match(re_out, name)
        if _match:
            index = _match.groups()[1]
            if index is None or len(index) == 0:
                index = 0
            else:
                index = int(index)
            portname = f"extra_out{index:d}"
            print(f"Matched output: {portname}")
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
            raise GhostbusException("'ghostbus_port={}' already defined at {}".format(busval[0].strip().lower(), busval[1]))
        return

    def _set_width(self, name, width=1, rangestr=None):
        for wparam, ports in self._derived.items():
            if name in ports:
                existing = self._bus[wparam]
                if existing is not None and existing[0] != width:
                    raise GhostbusException(f"Ghostbus ports ({ports}) must all be the same width.")
                self._bus[wparam] = (width, None)
                self._bus[wparam+"_range"] = (rangestr, None)
                self._bus[wparam+"_str"] = (rangestr[0] + "+1", None)
        return

    def validate(self):
        _valid = True
        for key, data in self._bus_info.items():
            mandatory = data[1]
            if mandatory and self._bus[key] is None:
                _valid = False
        self._valid = _valid
        return _valid

    def get(self):
        """Get a copy of the bus dict without the 'source' references"""
        if not self._valid:
            serr = ["Incomplete bus definition"]
            missing = False
            for key, data in self._bus_info.items():
                mandatory = data[1]
                if mandatory and self._bus[key] is None:
                    serr.append("  Missing: {}".format(key))
                    missing = True
            if not missing:
                raise GhostbusException("Invalid bus not missing anything? bus = {}".format(strDict(self._bus)))
            raise GhostbusException("\n".join(serr))
        dd = {}
        for key, val in self._bus.items():
            if val is not None:
                dd[key] = val[0] # Discarding the "source" part
            else:
                dd[key] = None
        return dd


class DecoderLB():
    def __init__(self, memregion, bus, csr_class, ram_class, ext_class):
        self.mod = memregion
        self.bus = bus # TODO deleteme; replace with self.ghostbus
        self.ghostbus = bus
        self.aw = self.mod.aw
        self.inst = self.mod.hierarchy[-1]
        self.name = self.mod.label
        self.base = self.mod.base
        self.submods = []
        self.rams = []
        self.csrs = []
        self.exts = []
        self.max_local = 0
        for start, stop, ref in memregion.get_entries():
            if isinstance(ref, csr_class):
                ref._readRangeDepth()
                self.csrs.append(ref)
            elif isinstance(ref, ram_class):
                ref._readRangeDepth()
                self.rams.append(ref)
            elif isinstance(ref, ext_class):
                self.exts.append((start, ref))
            elif isinstance(ref, MemoryRegion):
                self.submods.append((start, self.__class__(ref, self.bus, csr_class, ram_class, ext_class)))
            if isinstance(ref, Register): # Should catch MetaRegister and MetaMemory
                if stop > self.max_local:
                    self.max_local = stop
        if self.max_local == 0:
            self.no_local = True
        else:
            self.no_local = False
        self.local_aw = bits(self.max_local)
        self._def_file = "defs.vh"
        self.check_bus()

    def check_bus(self):
        """If any strobes exist, verify the bus has the appropriate strobe signal
        defined."""
        for csr in self.csrs:
            if csr.strobe or (len(csr.write_strobes) > 0):
                if self.bus["wstb"] is None:
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
                if self.bus["rstb"] is None:
                    strobe_name = csr.read_strobes[0]
                    serr = f"\n{strobe_name} requires a 'rstb' signal in the ghostbus. " + \
                            "Please define it with the other bus signals, e.g.:\n" + \
                            "  (* ghostbus_port='rstb' *) wire rstb;\n" + \
                            "If your read-enable signal is also a strobe (1-cycle long), " + \
                            "you can define it to also be the 'rstb' as in e.g.:\n" + \
                            "  (* ghostbus_port='rstb, re' *) wire ren;"
                    raise Exception(serr)
        # Make some decoding definitions here to save checks later
        if (self.bus['wstb'] is None) or (self.bus['we'] == self.bus['wstb']):
            self._bus_we = self.bus['we']
        else:
            self._bus_we = f"{self.bus['we']} & {self.bus['wstb']}"
        if self.bus['re'] is not None:
            self._asynch_read = False
            self._bus_re = self.bus['re']
        else:
            self._bus_re = f"~{self.bus['we']}"
            self._asynch_read = True
        return

    def _clearDef(self, dest_dir):
        """Start with empty macro definitions file"""
        fd = open(os.path.join(dest_dir, self._def_file), "w")
        fd.close()
        return

    def _addDef(self, dest_dir, macrostr, macrodef):
        defstr = f"`define {macrostr} {macrodef}\n"
        with open(os.path.join(dest_dir, self._def_file), "a") as fd:
            fd.write(defstr)
        return

    def _addGhostbusDef(self, dest_dir, suffix):
        macrostr = f"GHOSTBUS_{suffix}"
        macrodef = f"`include \"ghostbus_{suffix}.vh\""
        return self._addDef(dest_dir, macrostr, macrodef)

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

    def ExtraVerilogMemoryMap(self, filename, bus):
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
            "`ifndef TICK",
            "  `define TICK 10",
            "`endif",
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

    def GhostbusMagic(self, dest_dir="_auto"):
        """Generate the automatic files for this project and write to
        output directory 'dest_dir'."""
        import os
        self._clearDef(dest_dir)
        gbports = self.GhostbusPorts()
        fname = "ghostbus_ports.vh"
        with open(os.path.join(dest_dir, fname), "w") as fd:
            fd.write(gbports)
            print(f"Wrote to {fname}")
        self._addGhostbusLive(dest_dir)
        self._addGhostbusDef(dest_dir, "ports")
        self._GhostbusDoSubmods(dest_dir)
        return

    def _GhostbusDoSubmods(self, dest_dir):
        decode = self.GhostbusDecoding()
        fname = f"ghostbus_{self.name}.vh"
        with open(os.path.join(dest_dir, fname), "w") as fd:
            fd.write(decode)
            print(f"Wrote to {fname}")
        self._addGhostbusDef(dest_dir, self.name)
        for base, submod in self.submods:
            fname = f"ghostbus_{self.name}_{submod.inst}.vh"
            ss = submod.GhostbusSubmodMap()
            with open(os.path.join(dest_dir, fname), "w") as fd:
                fd.write(ss)
                print(f"Wrote to {fname}")
            self._addGhostbusDef(dest_dir, f"{self.name}_{submod.inst}")
            submod._GhostbusDoSubmods(dest_dir)
        return

    def GhostbusDecoding(self):
        """Generate the bus decoding logic for this instance."""
        ss = []
        ss.append(self.localInit())
        ss.append(self.submodsTopInit())
        ss.append(self.dinRouting())
        ss.append(self.busDecoding())
        return "\n".join(ss)

    def GhostbusPorts(self):
        """Generate the necessary ghostbus Verilog port declaration"""
        ss = [
            # TODO - It is conceivable that one could have a read-only or write-only
            #        ghostbus and therefore 'wdata' or 'rdata' are not stricly necessary
            #        but there should be at least one present.
            # Mandatory ports
            "// Ghostbus ports",
            f",input  {self.bus['clk']}",
            f",input  [{self.bus['aw']-1}:0] {self.bus['addr']}",
            f",input  [{self.bus['dw']-1}:0] {self.bus['dout']}",
            f",output [{self.bus['dw']-1}:0] {self.bus['din']}",
            f",input  {self.bus['we']}",
        ]
        # Optional ports
        if self.bus['wstb'] is not None and self.bus['wstb'] != self.bus['we']:
            ss.append(f",input  {self.bus['wstb']}")
        if self.bus['re'] is not None:
            ss.append(f",input  {self.bus['re']}")
        if self.bus['rstb'] is not None and self.bus['rstb'] != self.bus['re']:
            ss.append(f",input  {self.bus['rstb']}")
        return "\n".join(ss)

    def GhostbusSubmodMap(self):
        """Generate the necessary ghostbus Verilog port map for this instance
        within its parent module."""
        clk = self.bus['clk']
        addr = self.bus['addr']
        dout = self.bus['dout']
        din = self.bus['din']
        we = self.bus['we']
        wstb = self.bus['wstb']
        re = self.bus['re']
        rstb = self.bus['rstb']
        ss = [
            # TODO - It is conceivable that one could have a read-only or write-only
            #        ghostbus and therefore 'wdata' or 'rdata' are not stricly necessary
            #        but there should be at least one present.
            # Mandatory ports
            f",.{clk}({clk})    // input",
            f",.{addr}({addr}_{self.inst})  // input [{self.bus['aw']-1}:0]",
            f",.{dout}({dout})  // input [{self.bus['dw']-1}:0]",
            f",.{din}({din}_{self.inst}) // output [{self.bus['dw']-1}:0]",
            f",.{we}({we}_{self.inst}) // input",
        ]
        # Optional ports
        if wstb is not None and wstb != we:
            ss.append(f",.{wstb}({wstb}_{self.inst}) // input")
        if re is not None:
            ss.append(f",.{re}({re}_{self.inst}) // input")
        if rstb is not None and rstb != re:
            ss.append(f",.{rstb}({rstb}_{self.inst}) // input")
        return "\n".join(ss)

    def localInit(self):
        # wire en_local = gb_addr[11:9] == 3'b000; // 0x000-0x1ff
        # reg  [31:0] local_din=0;
        if self.no_local:
            return ""
        busaw = self.bus['aw']
        divwidth = busaw - self.local_aw
        ss = [
            f"// local init",
            f"wire en_local = {self.bus['addr']}[{self.bus['aw']-1}:{self.local_aw}] == {vhex(0, divwidth)}; // 0x0-0x{1<<self.local_aw:x}",
            f"reg  [{self.bus['dw']-1}:0] local_din=0;",
        ]
        if len(self.rams) > 0:
            ss.append("// local rams")
            for n in range(len(self.rams)):
                ss.append(self._ramInit(self.rams[n], self.bus, self.local_aw))
        return "\n".join(ss)

    def submodsTopInit(self):
        ss = []
        for base, submod in self.submods:
            ss.append(submod.submodInitStr(base))
        for base_rel, ext in self.exts:
            ss.append(f"// External Module Instance {ext.name}")
            ss.append(self._addrHit(base_rel, ext))
            ss.append(self.busHookup(ext))
        return "\n".join(ss)

    @classmethod
    def _ramInit(cls, mod, bus, local_aw=None):
        # localparam FOO_RAM_AW = $clog2(RD);
        # wire en_foo_ram = gb_addr[8:3] == 6'b001000;
        if local_aw is None:
            local_aw = bus['aw']
        divwidth = local_aw - mod.aw
        ss = (
            f"localparam {mod.name.upper()}_AW = $clog2({mod.depth[1]}+1);",
            f"wire en_{mod.name} = {bus['addr']}[{local_aw-1}:{mod.aw}] == {vhex(mod.base>>mod.aw, divwidth)};",
        )
        return "\n".join(ss)

    @classmethod
    def _addrHit(cls, base_rel, mod):
        bus = mod.ghostbus
        busaw = bus['aw']
        divwidth = busaw - mod.aw
        end = base_rel + (1<<mod.aw) - 1
        # TODO - Should I be using the string 'aw_str' here instead of the integer 'aw'? I would need to be implicit with the width
        #        to 'vhex' or do some tricky concatenation
        return f"wire en_{mod.inst} = {bus['addr']}[{busaw-1}:{mod.aw}] == {vhex(base_rel>>mod.aw, divwidth)}; // 0x{base_rel:x}-0x{end:x}"

    @classmethod
    def _addrMask(cls, mod):
        bus = mod.ghostbus
        busaw = bus['aw']
        divwidth = busaw - mod.aw
        return f"wire [{busaw-1}:0] {bus['addr']}_{mod.inst} = {{{vhex(0, divwidth)}, {bus['addr']}[{mod.aw-1}:0]}}; // address relative to own base (0x0)"

    @classmethod
    def _wen(cls, mod):
        return cls._andPort(mod, "we")

    @staticmethod
    def _andPort(mod, portname):
        signal = mod.ghostbus[portname]
        return f"wire {signal}_{mod.inst}={signal} & en_{mod.inst};"

    def submodInitStr(self, base_rel):
        #e.g.
        # // submodule bar_0
        # wire [31:0] gb_din_bar_0;
        # wire en_bar_0 = gb_addr[11:9] == 3'b001; // 0x200-0x3ff
        # wire [11:0] gb_addr_bar_0 = {3'b000, gb_addr[8:0]}; // address relative to own base (0x0)
        # wire gb_we_bar_0=gb_we & en_bar_0;
        busaw = self.bus['aw']
        divwidth = busaw - self.aw
        end = base_rel + (1<<self.aw) - 1
        addrHit = self._addrHit(base_rel, self)
        addrMask = self._addrMask(self)
        wen = self._wen(self)
        ss = [
            # Mandatory ports
            f"// submodule {self.inst}",
            f"wire [{self.bus['dw']-1}:0] {self.bus['din']}_{self.inst};",
            addrHit,
            addrMask,
            wen,
        ]
        # Optional ports
        if self.bus['wstb'] is not None and self.bus['wstb'] != self.bus['we']:
            ss.append(self._andPort(self, "wstb"))
        if self.bus['re'] is not None:
            ss.append(self._andPort(self, "re"))
        if self.bus['rstb'] is not None and self.bus['rstb'] != self.bus['re']:
            ss.append(self._andPort(self, "rstb"))
        return "\n".join(ss)

    def dinRouting(self):
        # assign gb_din = en_baz_0 ? gb_din_baz_0 :
        #                 en_bar_0 ? gb_din_bar_0 :
        #                 en_local ? local_din :
        #                 32'h00000000;
        ss = [
            "// din routing",
        ]
        if not self.no_local:
            ss.append(f"assign {self.bus['din']} = en_local ? local_din :")
        else:
            ss.append(f"assign {self.bus['din']} = ")
        for n in range(len(self.submods)):
            base, submod = self.submods[n]
            inst = submod.inst
            if n == 0 and self.no_local:
                ss[-1] = ss[-1] + f"en_{inst} ? {self.bus['din']}_{inst} :"
            else:
                ss.append(f"                en_{inst} ? {self.bus['din']}_{inst} :")
        for n in range(len(self.exts)):
            base_rel, ext = self.exts[n]
            if not ext.access & Register.READ:
                # Skip non-readable ext modules
                continue
            inst = ext.name
            din = ext.getDinPort()
            if (n == 0) and (self.no_local) and (len(self.submods) == 0):
                ss[-1] = ss[-1] + f"en_{inst} ? {{{{{self.bus['dw']-ext.dw}{{1'b0}}}}, {din}}} :"
            else:
                ss.append(f"                en_{inst} ? {{{{{self.bus['dw']-ext.dw}{{1'b0}}}}, {din}}} :")
        ss.append(f"                {vhex(0, self.bus['dw'])};")
        return "\n".join(ss)

    def busDecoding(self):
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
            crindent = 6*" "
            #extraend = "  end // ram reads"
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
        if len(_ramwrites) > 0 or len(_csrwrites) > 0:
            ss.append(f"always @(posedge {self.bus['clk']}) begin")
            if len(csrdefaults) > 0:
                ss.append("  // Strobe default assignments")
            for strobe in csrdefaults:
                if hasattr(strobe, "name"):
                    ss.append(f"  {strobe.name} <= {vhex(0, strobe.dw)};")
                else:
                    ss.append(f"  {strobe} <= {vhex(0, 1)};")
            ss.append("  // local writes")
            ss.append(f"  if (en_local & {self._bus_we}) begin")
            ss.append("    " + ramwrites.replace("\n", "\n    "))
            ss.append("    " + csrwrites.replace("\n", "\n    "))
            ss.append(f"  end // if (en_local & {self._bus_we})")
            hasclk = True
        if len(_ramreads) > 0 or len(_csrreads) > 0:
            if not hasclk:
                ss.append(f"always @(posedge {self.bus['clk']}) begin")
            ss.append("  // local reads")
            ss.append(f"  if (en_local & {self._bus_re}) begin")
            ss.append("    " + ramreads.replace("\n", "\n    ") + midend)
            ss.append(crindent + csrreads.replace("\n", "\n"+crindent))
            ss.append(extraend)
            ss.append(f"  end // if (en_local & {self._bus_re})")
        if hasclk:
            ss.append(f"end // always @(posedge {self.bus['clk']})")
        return "\n".join(ss)

    def csrWrites(self):
        if len(self.csrs) == 0:
            return ("", [])
        # Default-assign any strobes
        defaults = []
        for csr in self.csrs:
            if csr.strobe:
                defaults.append(csr)
            if len(csr.write_strobes) > 0:
                defaults.extend(csr.write_strobes)
        ss = [
            "// CSR writes",
            f"casez ({self.bus['addr']}[{self.local_aw-1}:0])",
        ]
        writes = 0
        for n in range(len(self.csrs)):
            csr = self.csrs[n]
            if (csr.access & Register.WRITE) == 0:
                # Skip read-only registers
                continue
            writes += 1
            if len(csr.write_strobes) == 0:
                if csr.strobe:
                    ss.append(f"  {vhex(csr.base, self.local_aw)}: {csr.name} <= {vhex(1, csr.dw)};")
                else:
                    ss.append(f"  {vhex(csr.base, self.local_aw)}: {csr.name} <= {self.bus['dout']}[{csr.range[0]}:0];")
            else:
                ss.append(f"  {vhex(csr.base, self.local_aw)}: begin")
                if csr.strobe:
                    ss.append(f"    {csr.name} <= {vhex(0, strobe.dw)};")
                else:
                    ss.append(f"    {csr.name} <= {self.bus['dout']}[{csr.range[0]}:0];")
                for strobe_name in csr.write_strobes:
                    ss.append(f"    {strobe_name} <= 1'b1;")
                ss.append(f"  end")
        ss.append("endcase")
        if writes == 0:
            return ("", [])
        return ("\n".join(ss), defaults)

    def csrReads(self):
        if len(self.csrs) == 0:
            return ("", [])
        # Default-assign any strobes
        defaults = []
        for csr in self.csrs:
            if len(csr.read_strobes) > 0:
                defaults.extend(csr.read_strobes)
        ss = [
            "// CSR reads",
            f"casez ({self.bus['addr']}[{self.local_aw-1}:0])",
        ]
        reads = 0
        for n in range(len(self.csrs)):
            csr = self.csrs[n]
            if (csr.access & Register.READ) == 0:
                # Skip write-only registers
                continue
            if len(csr.read_strobes) == 0:
                ss.append(f"  {vhex(csr.base, self.local_aw)}: local_din <= {{{{{self.bus['dw']}-({csr.range[0]}+1){{1'b0}}}}, {csr.name}}};")
            else:
                ss.append(f"  {vhex(csr.base, self.local_aw)}: begin")
                ss.append(f"    local_din <= {{{{{self.bus['dw']}-({csr.range[0]}+1){{1'b0}}}}, {csr.name}}};")
                for strobe_name in csr.read_strobes:
                    ss.append(f"    {strobe_name} <= 1'b1;")
                ss.append(f"  end")
            reads += 1
        ss.append(f"  default: local_din <= {vhex(0, self.bus['dw'])};")
        ss.append("endcase")
        if reads == 0:
            return ("", [])
        return ("\n".join(ss), defaults)

    def ramWrites(self):
        if len(self.rams) == 0:
            return ""
        ss = [
            "// RAM writes",
            "",
        ]
        for n in range(len(self.rams)):
            ram = self.rams[n]
            s0 = f"if (en_{ram.name}) begin"
            if n > 0:
                s0 = " else " + s0
            ss[-1] = ss[-1] + s0
            ss.append(f"  {ram.name}[{self.bus['addr']}[{ram.name.upper()}_AW-1:0]] <= {self.bus['dout']}[{ram.range[0]}:{ram.range[1]}];")
            ss.append("end")
        return "\n".join(ss)

    def ramReads(self):
        if len(self.rams) == 0:
            return ""
        ss = [
            "// RAM reads",
            "",
        ]
        for n in range(len(self.rams)):
            ram = self.rams[n]
            s0 = f"if (en_{ram.name}) begin"
            if n > 0:
                s0 = " else " + s0
            ss[-1] = ss[-1] + s0
            #ss.append(f"  {ram.name}[{self.bus['addr']}[{ram.name.upper()}_AW-1:0]] <= {self.bus['dout']}[{ram.range[0]}:{ram.range[1]}];")
            ss.append(f"  local_din <= {{{{{self.bus['dw']}-{ram.range[0]}+1{{1'b0}}}}, {ram.name}[{self.bus['addr']}[{ram.name.upper()}_AW-1:0]]}};")
            ss.append("end")
        return "\n".join(ss)

    @classmethod
    def busHookup(cls, extmod):
        ss = []
        for portname, ext_port in extmod.extbus.outputs_and_clock().items():
            if ext_port is None:
                continue
            gb_port = extmod.ghostbus[portname]
            #print(f"  portname = {portname}; ext_port = {ext_port}; gb_port = {gb_port}")
            _range = extmod.extbus.get_range(portname)
            if _range is not None:
                _s, _e = _range
                ss.append(f"assign {ext_port} = {gb_port}[{_s}:{_e}];")
            else:
                ss.append(f"assign {ext_port} = {gb_port} & en_{extmod.name};")
        return "\n".join(ss)

