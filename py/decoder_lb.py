# Ghostbus localbus-style decoder logic

from memory_map import Register, MemoryRegion, bits

def vhex(num, width):
    """Verilog hex constant generator"""
    fmt = "{{:0{}x}}".format(width>>2)
    return "{}'h{}".format(width, fmt.format(num))


class DecoderLB():
    def __init__(self, memregion, bus, csr_class, ram_class, ext_class):
        self.mod = memregion
        self.bus = bus
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
        import os
        fd = open(os.path.join(dest_dir, self._def_file), "w")
        fd.close()
        return

    def _addDef(self, dest_dir, macrostr, macrodef):
        import os
        defstr = f"`define {macrostr} {macrodef}\n"
        with open(os.path.join(dest_dir, self._def_file), "a") as fd:
            fd.write(defstr)
        return

    def _addGhostbusDef(self, dest_dir, suffix):
        macrostr = f"GHOSTBUS_{suffix}"
        macrodef = f"`include \"ghostbus_{suffix}.vh\""
        return self._addDef(dest_dir, macrostr, macrodef)

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
        # TODO - Find and remove any prefix common to all CSRs
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
        self._addGhostbusDef(dest_dir, "ports")
        self._GhostbusDoSubmods(dest_dir)
        return

    def _GhostbusDoSubmods(self, dest_dir):
        import os
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
                ss.append(self.rams[n].getInitStr(self.bus, self.local_aw))
        return "\n".join(ss)

    def submodsTopInit(self):
        ss = []
        for base, submod in self.submods:
            ss.append(submod.submodInitStr(base))
        for base_rel, ext in self.exts:
            ss.append(f"// External Module Instance {ext.name}")
            ss.append(ext.initStr(base_rel))
            ss.append(ext.getAssignment())
        return "\n".join(ss)

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
        ss = [
            # Mandatory ports
            f"// submodule {self.inst}",
            f"wire [{self.bus['dw']-1}:0] {self.bus['din']}_{self.inst};",
            f"wire en_{self.inst} = {self.bus['addr']}[{busaw-1}:{self.aw}] == {vhex(base_rel>>self.aw, divwidth)}; // 0x{base_rel:x}-0x{end:x}",
            f"wire [{busaw-1}:0] {self.bus['addr']}_{self.inst} = {{{vhex(0, divwidth)}, {self.bus['addr']}[{self.aw-1}:0]}}; // address relative to own base (0x0)",
            f"wire {self.bus['we']}_{self.inst}={self.bus['we']} & en_{self.inst};",
        ]
        # Optional ports
        if self.bus['wstb'] is not None and self.bus['wstb'] != self.bus['we']:
            ss.append(f"wire {self.bus['wstb']}_{self.inst}={self.bus['wstb']} & en_{self.inst};")
        if self.bus['re'] is not None:
            ss.append(f"wire {self.bus['re']}_{self.inst}={self.bus['re']} & en_{self.inst};")
        if self.bus['rstb'] is not None and self.bus['rstb'] != self.bus['re']:
            ss.append(f"wire {self.bus['rstb']}_{self.inst}={self.bus['rstb']} & en_{self.inst};")
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
            inst = ext.name
            dout = ext.getDoutPort()
            if (n == 0) and (self.no_local) and (len(self.submods) == 0):
                ss[-1] = ss[-1] + f"en_{inst} ? {{{{{self.bus['dw']-ext.dw}{{1'b0}}}}, {dout}}} :"
            else:
                ss.append(f"                en_{inst} ? {{{{{self.bus['dw']-ext.dw}{{1'b0}}}}, {dout}}} :")
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
                ss.append(f"  {vhex(csr.base, self.local_aw)}: local_din <= {{{{{self.bus['dw']}-{csr.range[0]}+1{{1'b0}}}}, {csr.name}}};")
            else:
                ss.append(f"  {vhex(csr.base, self.local_aw)}: begin")
                ss.append(f"    local_din <= {{{{{self.bus['dw']}-{csr.range[0]}+1{{1'b0}}}}, {csr.name}}};")
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
