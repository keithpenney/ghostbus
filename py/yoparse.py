#! /usr/bin/python3

# Use yosys parsing to generate automatic instantiation for a verilog module

import os
import subprocess
import json
import re
from util import enum

_net_keywords = ('reg', 'wire', 'input', 'output', 'inout')
NetTypes = enum(_net_keywords, base=0)

def srcParse(s):
    # FILEPATH:LINESTART.CHARSTART-LINEEND.CHAREND
    reYoSrc = "\A([^:]+):(\d+).(\d+)-(\d+).(\d+)"
    _match = re.match(reYoSrc, s)
    if not _match:
        return None
    filepath, linestart, charstart, lineend, charend = _match.groups()
    return (filepath, int(linestart), int(charstart), int(lineend), int(charend))


def ismodule(s):
    restr = r"^\$(\w+)[\$\\]"
    _match = re.search(restr, s)
    if _match:
        yotype = _match.groups()[0]
        if yotype == "paramod":
            # all other yosys magic should be ignored
            return True
    else:
        # If it gets here, it's probably a module
        return True
    return False


def isgenerate(inst_name):
    """Match "gen_block[index].instance" string."""
    gen_block, inst, index = block_inst(inst_name)
    if gen_block is None:
        return False
    return True


def block_inst(inst_name):
    """
    If inst_name matches "gen_block[index].instance",
        return gen_block, instance, index
    elif inst_name matches "gen_block.instance", 
        return gen_block, instance, None
    else:
        return None, None, None
    """
    restr = "([^.$]+)\.(\w+)"
    reindex = "(\w+)\[(\d+)\]"
    gen_block = None
    inst = None
    index = None
    _match = re.match(restr, inst_name)
    if _match:
        groups = _match.groups()
        gen_block, inst = groups[:2]
        imatch = re.match(reindex, gen_block)
        if imatch:
            gen_block, index = imatch.groups()
            index = int(index)
    return gen_block, inst, index


def autogenblk(gen_block):
    """Yosys lazily gives names to anonymous generate blocks and doesn't detect collisions if you happen
    to name a block with the same auto-generated internal names assigned by Yosys.
    Return True if the string 'gen_block' matches Yosys's internal naming convention (else False)."""
    restr = "genblk(\d+)"
    if re.match(restr, gen_block):
        return True
    return False


def get_modname(s):
    # format 0
    restr = r"^\$(\w+)\$([0-9a-fA-F]+)\\(\w+)"
    _match = re.search(restr, s)
    if _match:
        modname = _match.groups()[2]
        return modname
    # format 1
    restr = r"^\$(\w+)\\([^\\]+)\\([^\\]+)"
    _match = re.search(restr, s)
    if _match:
        modname = _match.groups()[1]
        return modname
    return s


def get_value(bitlist):
    val = 0
    for n in range(len(bitlist)):
        if bitlist[n] == '1':
            val |= 1 << n
    return val


def getUnparsedWidth(source):
    """Get the width of a net as a unparsed string (i.e. however it is declared in source)
    The 'source' arg should come directly from the 'src' attribute of a given net
    and describes the location in the source code where the net is defined."""
    _range = getUnparsedWidthRange(source)
    if _range is not None:
        # Assume _range[1] is always '0'
        return "{}+1".format(_range[0])
    return None


def getUnparsedWidthAndDepthRange(source):
    """A convenience method to do both getUnparsedWidthRange() and
    getUnparsedDepthRange() with a single file access.
    Returns (getUnparsedWidthRange(), getUnparsedDepthRange())"""
    snippet, offset = _getSourceSnippet(source)
    _ww = _getUnparsedWidthRange(snippet, offset, get_type=False)
    _dd = _getUnparsedDepthRange(snippet, offset)
    return (_ww, _dd)


def getUnparsedWidthAndDepthRangeAndType(source):
    """A convenience method to do both getUnparsedWidthRange() and
    getUnparsedDepthRange() with a single file access.
    Returns (range_spec, depth_spec, net_type)"""
    snippet, offset = _getSourceSnippet(source)
    _ww, net_type = _getUnparsedWidthRange(snippet, offset)
    _dd = _getUnparsedDepthRange(snippet, offset)
    return (_ww, _dd, net_type)


def getUnparsedWidthRangeType(source):
    """Get the range and net type of a net (wire/reg/input/output/inout). The range
    is returned as an unparsed string (i.e. however it is declared in source).
    The net type is one of enum NetType.
    Returns ('0', '0') for the range if a net type keyword is encountered (walking
    backward) before a range spec, otherwise returns (str range_high, str range_low)."""
    snippet, offset = _getSourceSnippet(source)
    return _getUnparsedWidthRange(snippet, offset)


def getUnparsedWidthRange(source):
    """Get the range of a net (wire/reg/input/output/inout) as an unparsed string
    (i.e. however it is declared in source).
    Returns ('0', '0') if a net type keyword is encountered (walking backward) before
    a range spec, otherwise returns (str range_high, str range_low)."""
    snippet, offset = _getSourceSnippet(source)
    return _getUnparsedWidthRange(snippet, offset, get_type=False)


def _getUnparsedWidthRange(snippet, offset, get_type=True):
    _range = None
    if snippet is not None:
        _rangeStr, net_type = _findRangeStr(snippet, offset, get_type=get_type)
        split = _rangeStr.split(':')
        if len(split) > 1:
            _range = (split[0], split[1])
    if get_type:
        return (_range, net_type)
    return _range


def getUnparsedDepthRange(source):
    """Get the depth of a memory (RAM) as an unparsed string (i.e. however it is
    declared in source).
    Returns ('0', '0') if a ';' is encountered before a depth spec, otherwise
    returns (str start, str end)."""
    snippet, offset = _getSourceSnippet(source)
    return _getUnparsedDepthRange(snippet, offset)


def _getUnparsedDepthRange(snippet, offset):
    _depth = None
    if snippet is not None:
        _depthStr = _findDepthStr(snippet, offset)
        split = _depthStr.split(':')
        if len(split) > 1:
            _depth = (split[0], split[1])
    return _depth


def _getSourceSnippet(yosrc, size=1024):
    """Get a snippet (string) of source code surrounding a line defined
    by the Yosys 'src' attribute 'yosrc' of a given net.
    Returns (str snippet, int offset) where the net name begins 'offset'
    characters into the string 'snippet'"""
    groups = srcParse(yosrc)
    if groups is None:
        return False
    filepath, linestart, charstart, lineend, charend = groups
    snippet = None
    offset = 0
    try:
        line = ""
        with open(filepath, 'r') as fd:
            for n in range(linestart):
                line = fd.readline()
            # Rewind up to 512 chars before start of register name
            tell = fd.tell()
            # Set tell to the start of the identifier
            tell -= 1+len(line)-charstart
            fd.seek(max(0, tell-512))
            # Read up to 1024 chars
            snippet = fd.read(1024)
            offset = min(tell, 512)
            #namestr = snippet[offset:offset+charend-charstart]
            #print("_readRange: namestr = {}, offset = {}, len(snippet) = {}, rangeStr = {}".format(
            #    namestr, offset, len(snippet), rangeStr))
    except OSError:
        print("Cannot open file {}".format(filepath))
        return None, None
    return snippet, offset

def _matchKw(ss):
    for kw in _net_keywords:
        if ss.startswith(kw):
            return kw
    return None

def _findRangeStr(snippet, offset, get_type=True):
    """Start at char offset. Read backwards. Look for ']' to open a range.
    If we find either keyword 'reg' or 'wire' before the ']', we'll break and
    decide the reg is 1-bit."""
    grouplevel = 0
    endix = None
    rangestr = None
    keywords = _net_keywords
    nettype = None
    maxlen = max([len(kw) for kw in keywords])
    #print(f"  ::{snippet[offset:offset+10]} -----", end="")
    for n in range(offset, -1, -1):
        char = snippet[n]
        # Room for whitespace+'r'+'e'+'g'+whitespace
        slc = snippet[n:n+maxlen].replace('\n', ' ').replace('.', ' ')
        kw = _matchKw(slc.strip())
        if kw is not None:
            nettype = NetTypes.get(kw)
            if rangestr is None:
                rangestr = "0:0"
            #print(f"Breaking at offset {offset-n}: {snippet[n:n+10]}")
            break
        elif char == ']': # walking backwards
            if grouplevel == 0:
                endix = n
            grouplevel += 1
        elif char == '[':
            grouplevel -= 1
            if grouplevel == 0:
                rangestr = snippet[n+1:endix]
                if not get_type:
                    #print(f"Breaking at offset {offset-n}: {snippet[n:n+10]}")
                    break
        if n == 0:
            raise Exception("Reached 0 looking for a keyword from netname {snippet[offset:offset+10]}")
    return (rangestr, nettype)


def _findDepthStr(snippet, offset):
    """Start at char offset. Read forward. Look for '[' to open a range.
    If we find a semicolon '[', we'll break and decide the depth is 1.
    """
    grouplevel = 0
    startix = None
    depthstr = None
    for n in range(offset, len(snippet)):
        char = snippet[n]
        if char == '[':
            if grouplevel == 0:
                startix = n
            grouplevel += 1
        elif char == ']':
            grouplevel -= 1
            if grouplevel == 0:
                depthstr = snippet[startix+1:n]
                break
        elif char == ';':
            break
    return depthstr


# HACK ALERT!
def _matchForLoop(ss):
    """Match the last Verilog for-loop opening statement in the string 'ss'
    NOTE: This hack only catches simple for-loops.  It's pretty easy to break this if you're trying.
    I need a proper lexer to do this generically.
    Return (loop_index, start, stop, inc)"""
    restr = "for\s+\(\s*(\w+)\s*=\s*([^;]+);\s*(\w+)\s*([=<>!]+)\s*([^;]+);\s*(\w+)\s*=\s*(\w+)\s*([\+\-*/]+)\s*(\w+)\)"
    #_match = re.search(restr, ss)
    #if _match:
    _matches = re.findall(restr, ss)
    if len(_matches) > 0:
        groups = _matches[-1]
        #groups = _match.groups()
        loop_index = groups[0]
        # We can only understand simple for loops such that loop_index also appears at groups()[2, 5, and 6]
        for x in (2, 5, 6):
            if loop_index != groups[x].strip():
                ms = ss[_match.start(), _match.end()]
                raise YosysParsingError(f"I'm not smart enough to parse this construct; please simplify it: {ms}")
        start = groups[1].strip()
        comp = groups[3]
        compval = groups[4]
        inc_op = groups[7]
        inc_val = groups[8]
        return (loop_index, start, compval, inc_op+inc_val)
    return (None, None, None, None)


def findForLoop(yosrc):
    # We want to match the last for-loop in the portion of the string only up to the offset
    # loop_index, start, comp, inc
    snippet, offset = _getSourceSnippet(yosrc, size=1024)
    return _matchForLoop(snippet[:offset])


class YosysParsingError(Exception):
    def __init__(self, msg):
        super().__init__(msg)

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
        err = None
        try:
            jsfile = subprocess.check_output(ycmd, shell=True).decode('latin-1')
        except subprocess.CalledProcessError as e:
            err = str(e)
        if err is not None:
            raise YosysParsingError(err)
        self._dict = json.loads(jsfile)
        # Separate attributes for this module
        mod = self._dict.get("modules", None)
        self.params = {}
        if mod is not None:
            # Get first (should be only) module
            name,mdict = [x for x in mod.items()][0]
            self.modname = name
            self.elaboratePorts()
            self.ports = mdict.get('ports', None)
            paramdict = mdict.get("parameter_default_values", None)
            if paramdict is not None:
                dd = {}
                for paramname, paramstr in paramdict.items():
                    try:
                        pval = int(paramstr, 2)
                    except ValueError:
                        # Handle the oddball value where the paramstr is literally '""'
                        if len(paramstr.strip()) == 0:
                            paramstr = '""'
                        pval = paramstr
                    dd[paramname] = pval
                self.params[name] = dd
        else:
            self.modname = None
            self.ports = {}
        return True

    def elaboratePorts(self):
        """Capture the unparsed range string for all ports of all modules"""
        mod = self._dict.get("modules", None)
        if mod is not None:
            for name, mdict in mod.items():
                ports = mdict.get("ports", None)
                nets = mdict.get("netnames", None)
                for portname in ports.keys():
                    _range = None
                    net_dict = nets[portname]
                    if net_dict is not None:
                        attr_dict = net_dict.get("attributes", None)
                        if attr_dict is not None:
                            src = attr_dict.get("src", None)
                            if src is not None:
                                _range = getUnparsedWidthRange(src)
                    ports[portname]['range'] = _range
        return

    def getPorts(self, parsed=True):
        """Return list of (0, name, dirstr, rangeStart, rangeEnd), one for
        each port in the parsed module. The first '0' in the list is for compatibility
        with the non-Yosys parser which captures inline macros as well.  These need to
        be inserted at the proper location so they are included in the ports list (with
        non-zero as the first entry).  The Yosys parser acts on the preprocessed source
        so all macros are already resolved.
        If 'parsed', rangeStart and rangeEnd are integers (resolved expressions).
        Otherwise, they are unparsed strings (directly copied from the source code)."""
        ports = []
        for portname,vdict in self.ports.items():
            portdir = vdict.get('direction', 'unknown')
            pbits = vdict.get('bits', [0])
            if parsed:
                pw = len(pbits)
                if len(pbits) > 1:
                    rangeStart = len(pbits)-1
                    rangeEnd = 0
                else:
                    rangeStart = None
                    rangeEnd = None
            else:
                _range = vdict['range']
                if _range is None:
                    print(f"{portname} _range is None!")
                    rangeStart = None
                    rangeEnd = None
                else:
                    if _range[0] == '0' and _range[1] == '0':
                        rangeStart, rangeEnd = (None, None)
                    else:
                        rangeStart, rangeEnd = _range[:2]
            ports.append((self.LINETYPE_PORT, portname, portdir, rangeStart, rangeEnd))
        return ports

    def getParams(self, module=None):
        """Returns {param_name: default_value, ...}"""
        if len(self.params) == 0:
            return {}
        if module is None:
            # Just get the first module
            module = [key for key in self.params.keys()][0]
        mdict = self.params[module]
        return mdict

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


def doBrowse():
    import argparse
    parser = argparse.ArgumentParser("Browse a JSON AST from a verilog codebase")
    parser.add_argument("-d", "--depth", default=4, help="Depth to browse from the partselect.")
    parser.add_argument("-s", "--select", default=None, help="Partselect string.")
    parser.add_argument("-t", "--top", default=None, help="Explicitly specify top module for hierarchy.")
    parser.add_argument("files", default=None, action="append", nargs="+", help="Source files.")
    args = parser.parse_args()
    vp = VParser(args.files[0], top=args.top)
    if not vp.valid:
        return False
    print(vp.strToDepth(int(args.depth), args.select))
    return True


if __name__ == "__main__":
    doBrowse()
