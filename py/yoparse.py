#! /usr/bin/python3

# Use yosys parsing to generate automatic instantiation for a verilog module

import os
import subprocess
import json
import re

def srcParse(s):
    # FILEPATH:LINESTART.CHARSTART-LINEEND.CHAREND
    reYoSrc = "\A([^:]+):(\d+).(\d+)-(\d+).(\d+)"
    _match = re.match(reYoSrc, s)
    if not _match:
        return None
    filepath, linestart, charstart, lineend, charend = _match.groups()
    return (filepath, int(linestart), int(charstart), int(lineend), int(charend))

class VParser():
    # Helper values
    LINETYPE_PARAM = 0
    LINETYPE_PORT  = 0
    LINETYPE_MACRO = 1

    def __init__(self, filelist, top=None):
        self._filelist = filelist
        self._top = top
        self.valid = self.parse()

    def parse(self):
        self._dict = None
        for filename in self._filelist:
            if not os.path.exists(filename):
                raise Exception(f"File {filename} not found")
                return False
        #ycmd = f'yosys -q -p "proc -noopt read_verilog {self._filename}" -p write_json'
        #ycmd = f'yosys -q -p "read_verilog {self._filename}" -p write_json'
        filestr = " ".join(self._filelist)
        if self._top is not None:
            topstr = f"\nhierarchy -top {self._top}"
        else:
            topstr = ""
        ycmd = f'yosys -q -p "verilog_defines -DYOSYS\nread_verilog {filestr}{topstr}\nproc" -p write_json'
        #try:
        jsfile = subprocess.check_output(ycmd, shell=True).decode('latin-1')
        #except subprocess.CalledProcessError as e:
        self._dict = json.loads(jsfile)
        # Separate attributes for this module
        mod = self._dict.get("modules", None)
        if mod is not None:
            # Get first (should be only) module
            name,mdict = [x for x in mod.items()][0]
            self.modname = name
            self.ports = mdict.get('ports', None)
        else:
            self.modname = None
            self.ports = []
        return True

    def getPorts(self):
        """Return list of (0, name, dirstr, rangeStart, rangeEnd), one for
        each port in the parsed module. The first '0' in the list is for compatibility
        with the non-Yosys parser which captures inline macros as well.  These need to
        be inserted at the proper location so they are included in the ports list (with
        non-zero as the first entry).  The Yosys parser acts on the preprocessed source
        so all macros are already resolved."""
        ports = []
        for portname,vdict in self.ports.items():
            portdir = vdict.get('direction', 'unknown')
            pbits = vdict.get('bits', [0])
            pw = len(pbits)
            if len(pbits) > 1:
                rangeStart = len(pbits)-1
                rangeEnd = 0
            else:
                rangeStart = None
                rangeEnd = None
            ports.append((self.LINETYPE_PORT, portname, portdir, rangeStart, rangeEnd))
        return ports

    def getParams(self):
        """Yosys parser does not preserve parameters - seems to resolve them to literals."""
        return None

    def getDict(self):
        return self._dict

    def getTopName(self):
        return self.modname

    def _strToDepth(self, _dict, depth=0, indent=0):
        """RECURSIVE"""
        if depth == 0:
            return []
        l = []
        sindent = " "*indent
        for key, val in _dict.items():
            if hasattr(val, 'keys'):
                l.append(f"{sindent}{key} : dict size {len(val)}")
                l.extend(self._strToDepth(val, depth-1, indent+2))
            else:
                l.append(f"{sindent}{key} : {val}")
        return l

    def strToDepth(self, depth=0, partSelect = None):
        _d = self.selectPart(partSelect)
        l = ["VParser()"]
        l.extend(self._strToDepth(_d, depth, indent=2))
        return '\n'.join(l)

    def __str__(self):
        if self._dict == None:
            return "BDParser(Uninitialized)"
        return self.strToDepth(3)

    def __repr__(self):
        return self.__str__()

    def selectPart(self, partSelect = None):
        _d = self._dict
        if partSelect is not None:
            parts = partSelect.split('.')
            for nselect in range(len(parts)):
                select = parts[nselect]
                for key, val in _d.items():
                    if key == select:
                        _d = val
        if not isinstance(_d, dict):
            _d = self._dict
        return _d

    def getTrace(self, partselect):
        sigdict = self.selectPart(partselect)
        selftrace = [s.strip() for s in partselect.split('.')]
        # The resulting dict needs to have a 'bits' key
        bits = sigdict.get('bits', None)
        if bits is None:
            print(f"Partselect {partselect} does not refer to a valid net dict (key of 'netnames' dict)")
            return None
        bitlist = []
        for net in bits:
            bitlist.append([net, []])
        # Now walk the whole top-level dict and look connected nets by index
        def _do(trace, val):
            if trace == selftrace:
                return # Don't count yourself
            if hasattr(val, 'get'):
                valbits = val.get('bits', None)
                if valbits is not None:
                    # FIXME
                    # trstr = '.'.join(trace)
                    # print(f"{trstr} : {valbits}")
                    for n in range(len(bitlist)):
                        net, hitlist = bitlist[n]
                        if not isinstance(net, int):
                            # Skip special nets '0' and '1'
                            continue
                        if net in valbits:
                            valbitIndex = valbits.index(net)
                            trstr = '.'.join(trace)
                            if len(valbits) > 1:
                                trstr += f'[{valbitIndex}]'
                            hitlist.append(trstr)
                        bitlist[n] = hitlist
        self.walk(_do)
        # print the bit dict
        for n in range(len(bitlist)):
            net, hitlist = bitlist[n]
            if not isinstance(net, int):
                print(f"{n} : 1'b{net}")
            else:
                print(f"{n} : {hitlist}")
        return

    def getSigNames(self, indices, directions=("output", "input", None), selftrace=[]):
        """Get the signal name (source) associated with index 'index' (a number that Yosys
        assigns to every net)."""
        #sigdict = self.selectPart(partselect)
        #selftrace = [s.strip() for s in partselect.split('.')]
        bitlist = []
        for index in indices:
            bitlist.append([index, []])
        # Now walk the whole top-level dict and look connected nets by index
        def _do(trace, val):
            if trace == selftrace:
                return # Don't count yourself
            if hasattr(val, 'get'):
                _dir = val.get('direction', None)
                if _dir in directions:
                    valbits = val.get('bits', None)
                    valattr = val.get('attributes', None)
                    if valattr is not None:
                        valsrc = valattr.get('src', None)
                    else:
                        valsrc = None
                    if valbits is not None:
                        for n in range(len(bitlist)):
                            net, hitlist = bitlist[n]
                            if not isinstance(net, int):
                                # Skip special nets '0' and '1'
                                continue
                            if net in valbits:
                                valbitIndex = valbits.index(net)
                                trstr = '.'.join(trace)
                                if len(valbits) > 1:
                                    trstr += f'[{valbitIndex}]'
                                hitlist.append((trstr, _dir, valsrc))
                                bitlist[n][1] = hitlist
        self.walk(_do)
        return bitlist

    def search(self, target_key):
        """Search the dict structure for all keys that match 'target_key' and return as a nested dict."""
        hitlist = []
        def _do(trace, val):
            if trace[-1] == target_key:
                tstr = '.'.join(trace)
                hitlist.append((tstr, val))
        self.walk(_do)
        return hitlist

    def walk(self, do = lambda trace, val : None):
        return self._walk(self._dict, [], do)

    @classmethod
    def _walk(cls, td, trace = [], do = lambda trace, val : None):
        """RECURSIVE"""
        if not hasattr(td, 'items'):
            return False
        for key, val in td.items():
            trace.append(key)   # Add key
            do(trace, val)
            if hasattr(val, 'items'):
                cls._walk(val, trace, do)   # When this returns, we are done with this dict
            trace.pop() # So we can pop the key from the trace and continue the loop
        return True

if __name__ == "__main__":
    pass
