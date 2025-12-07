#! /usr/bin/python3

# Use slang parsing to generate automatic instantiation for a verilog module

import os
import subprocess
import json
import re
from util import enum, strDict
from struct_walker import StructWalker

_net_keywords = ('reg', 'wire', 'input', 'output', 'inout')
NetTypes = enum(_net_keywords, base=0)
# TODO - hopefully I don't need this anymore
SLANG_JSON_BUG_WORKAROUND = False
# slang can output type as a simple string or as a verbose dict
SLANG_TYPE_IS_STRING = True

def srcParse(s):
    # FILEPATH:LINESTART.CHARSTART-LINEEND.CHAREND
    reYoSrc = r"\A([^:]+):(\d+).(\d+)-(\d+).(\d+)"
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
    restr = r"([^.$]+)\.(\w+)"
    reindex = r"(\w+)\[(\d+)\]"
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
    restr = r"genblk(\d+)"
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
        return None, None
    filepath, linestart, charstart, lineend, charend = groups
    snippet = None
    offset = 0
    try:
        line = ""
        with open(filepath, 'r') as fd:
            for n in range(linestart):
                line = fd.readline()
            # Rewind up to size/2 chars before start of register name
            tell = fd.tell()
            # Set tell to the start of the identifier
            tell -= 1+len(line)-charstart
            fd.seek(max(0, tell-int(size//2)))
            # Read up to 1024 chars
            snippet = fd.read(int(size))
            offset = min(tell, int(size//2))
            #namestr = snippet[offset:offset+charend-charstart]
            #print("_readRange: namestr = {}, offset = {}, len(snippet) = {}, rangeStr = {}".format(
            #    namestr, offset, len(snippet), rangeStr))
    except OSError:
        # print("Cannot open file {}".format(filepath))
        return None, None
    return snippet, offset


def _getSourceFromStart(yosrc):
    """Read in the file reference by 'yosrc' and return the portion from the beginning of the file
    up until the line/char referenced by 'yosrc'."""
    groups = srcParse(yosrc)
    if groups is None:
        return False
    filepath, linestart, charstart, lineend, charend = groups
    lines = []
    try:
        with open(filepath, 'r') as fd:
            nline = 0
            line = True
            while line:
                line = fd.readline()
                nline += 1
                if nline == linestart:
                    lines.append(line[:charstart])
                else:
                    lines.append(line)
    except OSError:
        return None
    return "".join(lines)


def _matchKw(ss):
    for kw in _net_keywords:
        if re.search(r"\b" + kw + r"\b", ss):
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
        if (grouplevel == 0) and kw is not None:
            nettype = NetTypes.get(kw)
            if rangestr is None:
                rangestr = "0:0"
            #print(f"xx Breaking at offset {offset-n}: {snippet[n:n+10]} (kw = {kw}) (using input \"{slc.strip()}\")")
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
                    #print(f"xy Breaking at offset {offset-n}: {snippet[n:n+10]}")
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
def decomment(ss):
    """A hackish attempt to de-comment a block of Verilog code"""
    cbs = "/*"
    cbe = "*/"
    cls = "//"
    cle = "\n"
    result = []
    start = 0
    NO_COMMENT = 0
    BLOCK_COMMENT = 1
    LINE_COMMENT = 2
    comment = NO_COMMENT
    for n in range(2, len(ss)):
        chrs = ss[n-2:n]
        if comment == NO_COMMENT:
            if cbs in chrs:
                comment = BLOCK_COMMENT
            elif cls in chrs:
                comment = LINE_COMMENT
            if comment != NO_COMMENT:
                result.append(ss[start:n-2])
        elif comment == BLOCK_COMMENT:
            if cbe in chrs:
                start = n
                comment = NO_COMMENT
        elif comment == LINE_COMMENT:
            if cle in chrs:
                start = n-1 # Will hit when cle is chrs[0]
                comment = NO_COMMENT
    if comment == NO_COMMENT:
        result.append(ss[start:])
    return "".join(result)


def _matchForLoop(ss):
    """Match the last Verilog generate-for-loop opening statement in the string 'ss'
    NOTE: This hack only catches simple for-loops.  It's pretty easy to break this if you're trying.
    I need a proper lexer to do this generically.
    Return (loop_index, start, stop, inc)"""
    ss = decomment(ss)
    restr = r"generate\s+for\s+\(\s*(\w+)\s*=\s*([^;]+);\s*(\w+)\s*([=<>!]+)\s*([^;]+);\s*(\w+)\s*=\s*(\w+)\s*([\+\-*/]+)\s*(\w+)\)"
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
                raise SlangParsingError(f"I'm not smart enough to parse this construct; please simplify it: {ms}")
        start = groups[1].strip()
        comp_op = groups[3]
        comp_val = groups[4]
        inc_op = groups[7]
        inc_val = groups[8]
        return (loop_index, start, comp_op, comp_val, inc_op+inc_val)
    else:
        #print(f"Failed to find for-loop in the following:\n  {ss}")
        pass
    return (None, None, None, None, None)


def findForLoop(yosrc):
    # We want to match the last for-loop in the portion of the string only up to the offset
    # loop_index, start, comp, inc
    #snippet, offset = _getSourceSnippet(yosrc, size=4096)
    snippet = _getSourceFromStart(yosrc)
    return _matchForLoop(snippet)


def _split_body(bodystr):
    restr = r"(\d+)\s+"
    _match = re.search(restr, bodystr)
    if _match:
        addr = _match.groups()[0]
        remainder = bodystr[_match.end():]
        print(f"{addr}, {remainder}")
        return addr, remainder
    raise Exception(f"Missed {bodystr}")
    return None, None


def parse_rangestr(rangestr):
    restr = r"\$?\[(\d+):(\d+)\]"
    _match = re.match(restr, rangestr)
    if _match:
        first, second = _match.groups()[:2]
        return (first, second)
    return None, None


def parse_typestr(typestr):
    # E.g.:
    #   logic
    #   reg signed[7:0]
    #   reg[3:0]$[0:7]
    signed = False
    nettype = "reg"
    index_hi = None
    index_lo = None
    elem_lo = None
    elem_hi = None
    restr = r"(reg|wire|bit|logic)( signed)?(\[\d+:\d+\])?(\$\[\d+:\d+\])?"
    _match = re.match(restr, typestr)
    if _match:
        groups = _match.groups()
        nettype = groups[0]
        if groups[1] is not None:
            signed = True
        if groups[2] is not None:
            index_hi, index_lo = parse_rangestr(groups[2])
        if groups[3] is not None:
            elem_lo, elem_hi = parse_rangestr(groups[3])
    return nettype, index_hi, index_lo, signed, elem_lo, elem_hi


def format_source_yosys_style(source_file, source_line, source_column):
    #e.g. "verilog/simple/extmod.v:15.14-15.17"
    return f"{source_file}:{source_line}.{source_column}-{source_line}.{source_column}"


def _hex_string_to_ascii(hexstr):
    _bytes = len(hexstr)//2 + len(hexstr)%2 # ceil
    if len(hexstr) < 2*_bytes:
        # pad to 2 chars per byte
        hexstr = "0" + hexstr
    ss = []
    for n in range(_bytes):
        ss.append(chr(int(hexstr[2*n:2*(n+1)], 16)))
    return "".join(ss)


def slang_attrval_int_to_string(intstr):
    # "80'h6578745f692c20636c6b" -> "ext_i, clk"
    # "88'h6578745f692c2061646472" -> "ext_i, addr"
    # "24'd6515819" -> "clk"
    restr = r"^(\d+')(h|d|b)?([0-9a-fA-F]+)"
    _match = re.match(restr, intstr)
    bases = {'h': 16, 'd': 10, 'b': 2}
    if _match:
        groups = _match.groups()
        base = bases.get(groups[1], 10)
        val = groups[2]
        # slang will use base 10 (or maaaaybe 2) if the string is short, but
        # I'd rather keep it as a hex string so I don't need to do math with
        # ridiculously big integers
        if (base == 10) or (base == 2):
            val = "{:x}".format(int(val, base))
        return _hex_string_to_ascii(val)
    return None


def slang_attrval_int_to_int(intstr):
    # "32'd64" -> 64
    restr = r"^(\d+')(h|d|b)?([0-9a-fA-F]+)"
    _match = re.match(restr, intstr)
    bases = {'h': 16, 'd': 10, 'b': 2}
    if _match:
        groups = _match.groups()
        base = bases.get(groups[1], 10)
        val = groups[2]
        return int(val, base)
    return None


class SlangParsingError(Exception):
    def __init__(self, msg):
        super().__init__(msg)


class Broken(Exception):
    def __init__(self, msg):
        super().__init__(msg)


#==============================================================================
# Finder Functions
#==============================================================================
#=======================
#========== 1 ==========
#=======================
def get_modules(trace, val):
    """slang"""
    if hasattr(val, "get"):
        kind = val.get("kind", None)
        body = val.get("body", None)
        if kind == "Instance" and hasattr(body, "items"):
            return True
    return False


#=======================
#========== 2 ==========
#=======================
def get_gbnets(trace, val):
    """slang"""
    if hasattr(val, "get"):
        kind = val.get("kind", None)
        if kind in ("Net", "Variable"): # ports show up in both "Port" and "Net"
            attrs = val.get("attributes")
            if attrs is not None:
                for attr in attrs:
                    attrname = attr.get("name")
                    if attrname.startswith("ghostbus"):
                        return True
    return False


#=======================
#========== 3 ==========
#=======================
def get_instances(trace, val):
    """slang"""
    if hasattr(val, "get"):
        kind = val.get("kind", None)
        if kind == "Instance":
            return True
    return False


#==============================================================================
# Parser
#==============================================================================
class VParser():
    # Helper values
    LINETYPE_PARAM = 0
    LINETYPE_PORT  = 0
    LINETYPE_MACRO = 1

    def __init__(self, filelist, top=None, include_dirs=None, sv=False):
        self._filelist = filelist
        self._top = top
        self._include_dirs = include_dirs
        self._sv = sv
        self._resolved = False
        self.valid = self.parse()

    def parse(self):
        self._dict = None
        for filename in self._filelist:
            if not os.path.exists(filename):
                raise Exception(f"File {filename} not found")
                return False
        filestr = " ".join(self._filelist)
        scopestr = ""
        if self._top is not None:
            topstr = f" --top {self._top}"
            # FIXME this basically just does what self.getTopDict() does with the normal JSON. Use it?
            scopestr = f" --ast-json-scope {self._top}"
        else:
            topstr = ""
        if self._include_dirs is not None and len(self._include_dirs) > 0:
            incstr = " ".join([f"-I {inc}" for inc in self._include_dirs])
        else:
            incstr = ""
        # NOTE --cst-json isn't included in a release yet (as of v9.1), but was introduced in commit 805e160fac on 8/8/25
        # TODO experiment with pyslang (much more of a pain to install but could be a lot better than walking the JSON manually)
        slang_args="-q --ignore-unknown-modules --timescale=1ns/1ns --allow-toplevel-iface-ports --ast-json-source-info"
        if not SLANG_TYPE_IS_STRING:
            slang_args += " --ast-json-detailed-types"
        scmd = f'slang -DSLANG {incstr}{filestr}{topstr}{scopestr} {slang_args} --ast-json -'
        err = None
        try:
            jsfile = subprocess.check_output(scmd, shell=True).decode('latin-1')
        except subprocess.CalledProcessError as e:
            err = str(e)
        if err is not None:
            raise SlangParsingError(err)
        #print(jsfile)
        if SLANG_JSON_BUG_WORKAROUND:
            ix = jsfile.index('{')
            preamble = jsfile[:ix]
            if self._top is None:
                _top = self._extract_top(preamble)
                if _top is not None:
                    self._top = _top
            jsfile = jsfile[ix:]
        self._dict = json.loads(jsfile)
        self.find_top_module()
        self.sort_nets()
        return

    def get_modules(self):
        return self.iter_walk(do=get_modules)

    @staticmethod
    def gbnetsIterator(mod_dict):
        jb = StructWalker(mod_dict)
        _iter = jb.iter_walk(do=get_gbnets, depth=4)
        for key, val in _iter:
            gbattrs = {}
            attrs = val.get("attributes")
            for attr in attrs:
                attrname = attr.get("name")
                attrval  = attr.get("value")
                if attrname.startswith("ghostbus"):
                    # TODO put this in a different layer (it's violating encapsulation)
                    if attrname == "ghostbus_addr":
                        attrval = slang_attrval_int_to_int(attrval)
                    else:
                        attrval = slang_attrval_int_to_string(attrval)
                    gbattrs[attrname] = attrval
            gbstr = ", ".join([key for key in gbattrs.keys()])
            netname = val.get("name", None)
            _type = val.get("type", None)
            index_hi, index_lo = None, None
            elem_hi, elem_lo = None, None
            signed = False
            #if SLANG_TYPE_IS_STRING:
            if not hasattr(_type, "items"):
                nettype, index_hi, index_lo, signed, elem_lo, elem_hi = parse_typestr(_type)
            else:
                nettype = _type.get("name")
                _range = _type.get("range", None)
                elementType = _type.get("elementType", None)
                if elementType is not None:
                    elementRange = elementType.get("range", None)
                    if elementRange is not None:
                        index_hi, index_lo = parse_rangestr(elementRange)
                        if _range is not None:
                            elem_lo, elem_hi = parse_rangestr(_range)
                    else:
                        index_hi, index_lo = parse_rangestr(_range)
            source_file = val.get("source_file")
            source_line = val.get("source_line")
            source_column = val.get("source_column")
            src = format_source_yosys_style(source_file, source_line, source_column)
            _nettype = val.get("netType", None)
            # Weird; imperically, it seems slang includes a "netType" member only when
            # a vector is of type 'wire', so I'm going to use that for the default access mode
            if _nettype is not None:
                nettype = _nettype.get("name", "wire")
            index_hi = int(index_hi) if index_hi is not None else None
            index_lo = int(index_lo) if index_lo is not None else None
            index_hi_str = str(index_hi)
            index_lo_str = str(index_lo)
            elem_lo = int(elem_lo) if elem_lo is not None else None
            elem_hi = int(elem_hi) if elem_hi is not None else None
            netdict = {
                "name": netname,
                "type": nettype,
                "range": (index_hi, index_lo),
                "rangestr": (index_hi_str, index_lo_str), # TODO range str
                "attributes": gbattrs,
                "src" : src,
                "array": (elem_lo, elem_hi),
            }
            yield netdict
        return

    @staticmethod
    def get_instances(mod_dict):
        jb = StructWalker(dd)
        _iter = jb.iter_walk(do=get_instances, depth=4)
        for key, val in _iter:
            attrs = val.get("attributes", {})
            inst_dict = {
                "inst_name": key,
                "mod_name": val.get("type"),
                "attributes": attrs,
            }
            yield inst_dict
        return

    @staticmethod
    def _extract_top(preamble):
        restr = r"^Top level design units:" + "\n" + r"\s+(\w+)"
        _match = re.search(restr, preamble)
        if _match:
            topname = _match.groups()[0]
            return topname
        return None

    def find_top_module(self):
        if self._resolved:
            return
        if self._top is None:
            # Just get whatever slang says is first
            defdict = self._dict["definitions"][0]
            topname = defdict["name"]
        else:
            topname = self._top
        self.modname = topname
        design_dict = self._dict["design"]
        ddict = None
        for member in design_dict["members"]:
            kind = member["kind"]
            name = member["name"]
            if (kind == "Instance") and (name == topname):
                ddict = member
                break
        if ddict is not None:
            self._dict = ddict["body"]
            self._resolved = True
        else:
            raise SlangParsingError(f"Could not find {topname} in design.")
        return

    def getTopDict(self):
        if self._resolved:
            return self._dict
        design_dict = self._dict["design"]
        members_list = design_dict["members"]
        for mod_dict in members_list:
            if mod_dict["name"] == self._top:
                return mod_dict
        return None

    def getTopGenerator(self):
        top_dict = self.getTopDict()
        #print(strDict(top_dict, depth=1))
        members_list = top_dict["members"]
        for mod_dict in members_list:
            kind = mod_dict["kind"]
            if kind == "Instance":
                body = mod_dict["body"]
                if hasattr(body, "items"): # body is a dict, phew
                    # mod_hash in yosys is just the (sometimes mangled) module name
                    mod_hash = body["name"]
                    yield (mod_hash, mod_dict)
                else: # dammit; body is a string - gotta find the dict
                    addr, module_name = _split_body(body)
                    md = None
                    mod_hash = None
                    for md in members_list:
                        _kind = md["kind"]
                        if _kind == "Instance":
                            _body = md["body"]
                            if not hasattr(_body, "items"):
                                continue
                            if _body["addr"] == addr:
                                mod_hash = _body["name"]
                                break
                    yield (mod_hash, md)

    def getInstGenerator(self, mod_dict):
        top_dict = self.getTopDict()
        #print(strDict(top_dict, depth=1))
        members_list = top_dict["members"]
        for mod_dict in members_list:
            kind = mod_dict["kind"]
            if kind == "Instance":
                body = mod_dict["body"]
                if hasattr(body, "items"): # body is a dict, phew
                    # mod_hash in yosys is just the (sometimes mangled) module name
                    mod_hash = body["name"]
                    yield (mod_hash, mod_dict)
                else: # dammit; body is a string - gotta find the dict
                    addr, module_name = _split_body(body)
                    md = None
                    mod_hash = None
                    for md in members_list:
                        _kind = md["kind"]
                        if _kind == "Instance":
                            _body = md["body"]
                            if not hasattr(_body, "items"):
                                continue
                            if _body["addr"] == addr:
                                mod_hash = _body["name"]
                                break
                    yield (mod_hash, md)

    def isTop(self, mod_hash):
        top_dict = self.getTopDict()
        mod_dict = top_dict.get(mod_hash, None)
        if mod_dict is not None:
            for attr in mod_dict["attributes"]:
                if attr == "top":
                    return True
        return False

    def sort_nets(self):
        # FIXME - move this ghostbus stuff out of this generic file
        params = []
        ports = []
        modinsts = []
        gbstuff = []
        members = self._dict["members"]
        for member in members:
            kind = member["kind"]
            if kind == "Parameter":
                params.append(member)
            elif kind == "Port":
                ports.append(member)
            elif kind in ("UninstantiatedDef", "Instance"):
                modinsts.append(member)
            elif kind == "Net":
                attrs = member.get("attributes", [])
                for attr in attrs:
                    attrname = attr["name"]
                    if attrname.startswith("ghostbus"):
                        gbstuff.append(member)
        self.params = params
        self.ports = ports
        self.modinsts = modinsts
        self.gbstuff = gbstuff
        return True

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

    def _strToDepth(self, _entry, depth=0, indent=0):
        """RECURSIVE"""
        if depth == 0:
            return []
        l = []
        sindent = " "*indent
        if hasattr(_entry, 'items'):
            _iter = _entry.items()
        else:
            _iter = enumerate(_entry)
        for key, val in _iter:
            if hasattr(val, 'keys'):
                l.append(f"{sindent}{key} : dict size {len(val)}")
                l.extend(self._strToDepth(val, depth-1, indent+2))
            elif hasattr(val, '__len__') and not hasattr(val, 'lower'):
                l.append(f"{sindent}{key} : list size {len(val)}")
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
            return "VParser(Uninitialized)"
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
        # I have to do this dumb thing where I actually
        # walk the generator and discard everything or
        # else the function exits early and doesn't walk?
        _iter = self._walk(self._struct, [], do)
        for x in _iter:
            pass
        return True

    def iter_walk(self, do = lambda trace, val : False):
        return self._walk(self._struct, [], do)

    @classmethod
    def _walk(cls, td, trace = [], do = lambda trace, val : False):
        """RECURSIVE"""
        if hasattr(td, "items"):
            _iter = td.items()
        else:
            _iter = enumerate(td)
        for key, val in _iter:
            trace.append(key)   # Add key
            rval = do(trace, val)
            if rval:
                yield val
            if hasattr(val, 'items') or (hasattr(val, "__len__") and not hasattr(val, "lower")):
                yield from cls._walk(val, trace, do) # When this returns, we are done with this dict/list
            trace.pop() # So we can pop the key from the trace and continue the loop
        return True

    def printSummary(self):
        print("{:=^80s}".format(" " + self.modname + " "))
        self._printParams()
        self._printPorts()
        self._printModinsts()
        print("="*80)
        return

    def _printParams(self):
        print("== Params")
        for pdict in self.params:
            name = pdict["name"]
            val = pdict["value"]
            local = pdict["isLocal"]
            if local:
                ptype = "localparam"
            else:
                ptype = "parameter"
            print(f"  {ptype} {name} = {val}")
        return

    def _printPorts(self):
        print("== Ports")
        for port in self.ports:
            name = port["name"]
            _dir = port["direction"].lower()
            _type = port["type"]
            print(f"  {_dir}put {_type} {name}")
        return

    def _printModinsts(self):
        print("== Mod Insts")
        for modinst in self.modinsts:
            name = modinst["name"]
            print("  " + name)
        return


def doBrowse():
    import argparse
    parser = argparse.ArgumentParser("Browse a JSON AST from a verilog codebase")
    parser.add_argument("-d", "--depth", default=4, help="Depth to browse from the partselect.")
    parser.add_argument("-s", "--select", default=None, help="Partselect string.")
    parser.add_argument("-t", "--top", default=None, help="Explicitly specify top module for hierarchy.")
    parser.add_argument("--sv", default=False, action="store_true", help="[EXPERIMENTAL] Enable SystemVerilog parsing (requires yosys-slang).")
    parser.add_argument("files", default=None, action="append", nargs="+", help="Source files.")
    args = parser.parse_args()
    vp = VParser(args.files[0], top=args.top, sv=args.sv)
    if not vp.valid:
        return False
    print(vp.strToDepth(int(args.depth), args.select))
    return True


if __name__ == "__main__":
    doBrowse()
