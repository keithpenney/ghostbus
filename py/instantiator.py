#! /usr/bin/python3

# Use yosys parsing to generate automatic instantiation for a verilog module

import os
import re
from yoparse import VParser

# ======== Clock matching regexp ==========
# Match any port that ends in 'clk' (case insensitive)
reClk = "[Cc][Ll][Kk]$"

def _decomma(s):
    """Remove the comma from the end of a port instantiation string."""
    if ',' in s:
        b, e, = s.split(',')
        return b+e
    else:
        return s

def makeTemplate(filename):
    vp = VParser(filename)
    if not vp.valid:
        return False
    name = vp.modname
    ports = vp.getPorts()
    params = vp.getParams()
    # find clkname
    clkname = 'clk'
    #for portname,vdict in ports.items():
    for port in ports:
        linetype, portname, pdir, rangeStart, rangeEnd = port
        if rangeStart is None or rangeEnd is None:
            # pw = 1
            if pdir == 'input':
                if re.match(reClk, 'clk'):
                    clkname = portname
                    break
    sl = (
        "`timescale 1ns/1ns",
        "",
        f"module {name}_tb;",
        "",
        # Clock
        f"reg {clkname}=1'b0;",
        f"always #5 {clkname} <= ~{clkname};",
        "",
        # Dumpfile
        "// VCD dump file for gtkwave",
        "reg [32*8-1:0] dumpfile; // 32-chars max",
        "initial begin",
        "  if (! $value$plusargs(\"df=%s\", dumpfile)) begin",
        "    $display(\"No dumpfile name supplied; Wave data will not be saved.\");",
        "  end else begin",
        "    $dumpfile(dumpfile);",
        "    $dumpvars;",
        "  end",
        "end",
        "",
        # Timeout
        ""
        "localparam TOW = 12;",
        "localparam TOSET = {TOW{1'b1}};",
        "reg [TOW-1:0] timeout=0;",
        f"always @(posedge {clkname}) begin",
        "  if (timeout > 0) timeout <= timeout - 1;",
        "end",
        "wire to = ~(|timeout);",
        ""
    )
    for s in sl:
        print(s)
    if ports is not None:
            print(makeWires(ports, params, skip=[clkname]))
            print(makeInstantiator(name, ports, params))
    sl = (
        "",
        "// =========== Stimulus =============",
        "initial begin",
        "  $display(\"Done\");",
        "  $finish(0);",
        "end",
        "",
        "endmodule"
    )
    for s in sl:
        print(s)
    return

def makeTemplateOld(filename):
    vp = VParser(filename)
    if not vp.valid:
        return False
    name = vp.modname
    ports = vp.getPorts()
    params = vp.getParams()
    # find clkname
    clkname = 'clk'
    #for portname,vdict in ports.items():
    for port in ports:
        linetype, name, pdir, rangeStart, rangeEnd = port
        pdir = vdict.get('direction')
        if rangeStart is None or rangeEnd is None:
            # pw = 1
            if pdir == 'input':
                if re.match(reClk, 'clk'):
                    clkname = portname
                    break
    sl = (
        "`timescale 1ns/1ns",
        "",
        f"module {name}_tb;",
        "",
        # Clock
        f"reg {clkname}=1'b0;",
        f"always #5 {clkname} <= ~{clkname};",
        "",
        # Dumpfile
        "// VCD dump file for gtkwave",
        "reg [32*8-1:0] dumpfile; // 32-chars max",
        "initial begin",
        "  if (! $value$plusargs(\"df=%s\", dumpfile)) begin",
        "    $display(\"No dumpfile name supplied; Wave data will not be saved.\");",
        "  end else begin",
        "    $dumpfile(dumpfile);",
        "    $dumpvars;",
        "  end",
        "end",
        "",
        # Timeout
        ""
        "localparam TOW = 12;",
        "localparam TOSET = {TOW{1'b1}};",
        "reg [TOW-1:0] timeout=0;",
        f"always @(posedge {clkname}) begin",
        "  if (timeout > 0) timeout <= timeout - 1;",
        "end",
        "wire to = ~(|timeout);",
        ""
    )
    for s in sl:
        print(s)
    if ports is not None:
            print(makeWires(ports, params, skip=[clkname]))
            print(makeInstantiator(name, ports, params))
    sl = (
        "",
        "// =========== Stimulus =============",
        "initial begin",
        "  $display(\"Done\");",
        "  $finish(0);",
        "end",
        "",
        "endmodule"
    )
    for s in sl:
        print(s)
    return


def makeWires(ports, params=[], skip=[]):
    l = []
    if params is None:
        params = []
    for param in params:
        linetype, name, rspec, val = param
        if linetype == VParser.LINETYPE_MACRO:
            #print(f"  Macro: {name}")
            l.append(f"{name}")
        else:
            #print(f"  parameter {name} = {val}")
            l.append(f"localparam {name} = {val};")
    #for portname,vdict in ports.items():
    for port in ports:
        linetype, portname, pdir, rangeStart, rangeEnd = port
        if portname in skip:
            continue
        if pdir == 'input':
            ptype = 'reg'
        else:
            ptype = 'wire'
        if rangeStart is not None and rangeEnd is not None:
            sel = f" [{rangeStart}:{rangeEnd}]"
        else:
            sel = ''
        l.append(f'{ptype}{sel} {portname};')
    return '\n'.join(l)

def makeWiresOld(ports, params=None, skip=[]):
    # TODO - Get/handle parameters
    l = []
    for portname,vdict in ports.items():
        if portname in skip:
            continue
        pdir = vdict.get('direction')
        pbits = vdict.get('bits')
        if pdir == 'input':
            ptype = 'reg'
        else:
            ptype = 'wire'
        pw = len(pbits)
        if pw > 1:
            sel = f" [{pw-1}:0]"
        else:
            sel = ''
        l.append(f'{ptype}{sel} {portname};')
    return '\n'.join(l)

def makeInstantiatorOld(name, ports, params=None):
    # TODO - Get/handle parameters
    l = [f'{name} {name}_i (\n']
    for portname,vdict in ports.items():
        portdir = vdict.get('direction', 'unknown')
        pbits = vdict.get('bits', [0])
        pw = len(pbits)
        if pw > 1:
            portwidth = f" [{pw-1}:0]"
        else:
            portwidth = ""
        l.append('  .{0}({0}), // {1}{2}\n'.format(portname, portdir, portwidth))
    # Hack. Remove the comma from the last entry
    l[-1] = _decomma(l[-1])
    l.append(');')
    return ''.join(l)

def makeInstantiator(name, ports, params=[]):
    if params is not None and len(params) > 0:
        p = ["#("]
        for param in params:
            linetype, pname, rspec, val = param
            if linetype == VParser.LINETYPE_MACRO:
                #print(f"  Macro: {name}")
                p.append(f"{pname}")
            else:
                #print(f"  parameter {name} = {val}")
                p.append(f"  .{pname}({pname}),")
        # Hack. Remove the comma from the last entry
        p[-1] = _decomma(p[-1])
        p.append(")")
        pstr = " " + '\n'.join(p) + " "
    else:
        pstr = " "
    l = [f'{name}{pstr}{name}_i (\n']
    #for portname,vdict in ports.items():
    for port in ports:
        linetype, pname, pdir, rangeStart, rangeEnd = port
        if linetype == VParser.LINETYPE_MACRO:
            l.append('{}\n'.format(pname))
        else:
            if rangeStart is not None and rangeEnd is not None:
                pw = f" [{rangeStart}:{rangeEnd}]"
            else:
                pw = ''
            l.append('  .{0}({0}), // {1}{2}\n'.format(pname, pdir, pw))
    # Hack. Remove the comma from the last entry
    l[-1] = _decomma(l[-1])
    l.append(');')
    return ''.join(l)


def instantiate(filename):
    vp = VParser(filename)
    if not vp.valid:
        return False
    #print(vp.strToDepth(3))
    d = vp.getDict()
    name = vp.modname
    ports = vp.getPorts()
    if ports is not None:
        print(makeWires(ports))
        print(makeInstantiator(name, ports))
    return True

def doTestbench(argv):
    USAGE = "python3 {} filename.v".format(argv[0])
    if len(argv) < 2:
        print(USAGE)
        return 1
    filename = argv[1]
    makeTemplate(filename)
    return

def doInstantiate(argv):
    USAGE = "python3 {} filename.v".format(argv[0])
    if len(argv) < 2:
        print(USAGE)
        return 1
    filename = argv[1]
    if instantiate(filename):
        return 0
    else:
        return 1

def doBrowse(argv):
    import argparse
    parser = argparse.ArgumentParser("Browse a JSON AST from a verilog codebase")
    parser.add_argument("-d", "--depth", default=4, help="Depth to browse from the partselect.")
    parser.add_argument("-s", "--select", default=None, help="Partselect string.")
    parser.add_argument("-t", "--top", default=None, help="Explicitly specify top module for hierarchy.")
    parser.add_argument("files", default=[], action="append", nargs="+", help="Source files.")
    args = parser.parse_args()
    vp = VParser(args.files[0], top=args.top)
    if not vp.valid:
        return False
    print(vp.strToDepth(int(args.depth), args.select))
    return True

def doTrace(argv):
    USAGE = f"python3 {argv[0]} filename.v part_select"
    if len(argv) < 3:
        print(USAGE)
        return False
    filename = argv[1]
    partselect = argv[2]
    vp = VParser(filename)
    #vp.search(partselect)
    sigtrace = vp.getTrace(partselect)

if __name__ == "__main__":
    import sys
    sys.exit(doInstantiate(sys.argv))
