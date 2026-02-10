#! /usr/bin/python3

# Use slang parsing to generate automatic instantiation for a verilog module

import os
import subprocess
import json
import re
from util import enum
from struct_walker import StructWalker, strStruct

_net_keywords = ('reg', 'wire', 'input', 'output', 'inout')
NetTypes = enum(_net_keywords, base=0)
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


# TODO SLANGIFY
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
    if False: # _match
        groups = _match.groups()
        gen_block, inst = groups[:2]
        imatch = re.match(reindex, gen_block)
        if imatch:
            gen_block, index = imatch.groups()
            index = int(index)
    return gen_block, inst, index


# TODO SLANGIFY
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


def _split_body(bodystr):
    restr = r"(\d+)\s+"
    _match = re.search(restr, bodystr)
    if _match:
        addr = _match.groups()[0]
        remainder = bodystr[_match.end():]
        #print(f"{addr}, {remainder}")
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


def collectText(dd):
    text = []
    def collect(trace, val):
        if len(trace) == 0:
            return False
        if trace[-1] == "text":
            text.append(val)
        return True
    sw = StructWalker(dd)
    sw.walk(do=collect)
    return "".join(text)


def extract_range(dd, netname):
    """
    Extracting the range from the CST:
      0. Find the net in question
         trace[-1] (key) == "text", val == net name
         trace[-2] == "name"
         trace[-3] == some int index // ignore this one
         trace[-4] == "declarators"
      1. Back up to same level as "declarators", and get val associated with key "type"
         dimensions = val.get("dimensions")
         specifier = dimensions.get("specifier")
         selector = specifier.get("selector")
         left  = selector.get("left")
         range = selector.get("range")
         right = selector.get("right")
      2. Confirm range.get("kind") == "Colon"
         Assemble text in "left" and "right"
    """
    traces = []
    def get_subtrace(trace, val):
        if len(trace) < 4:
            return False
        if (val == netname) and (trace[-1] == "text") and (trace[-2] == "name") and (trace[-4] == "declarators"):
            # Normal nets
            traces.append((0, trace.copy()))
        elif (val == netname) and (trace[-1] == "text") and (trace[-2] == "name"):
            # Ports
            traces.append((1, trace.copy()))
        return False
    sw = StructWalker(dd)
    sw.walk(do=get_subtrace)
    if len(traces) == 0:
        print(f"    WARNING: Found no range for: {netname}")
        return None, None
    matchtype, trace = traces[0]
    #print(trace)
    _dd = dd
    if matchtype == 0:
        offset = -4
    elif matchtype == 1:
        offset = -3
    for key in trace[:offset]:
        _dd = _dd[key]
    if matchtype == 0:
        # Normal nets
        newdd = _dd["type"]["dimensions"][0]["specifier"]["selector"]
    elif matchtype == 1:
        # Ports
        newdd = _dd["header"]["dataType"]["dimensions"][0]["specifier"]["selector"]
    else:
        return None, None
    left = newdd.get("left")
    _range = newdd.get("range")
    if _range.get("kind") != "Colon":
        raise Exception("This don't look right")
    right = newdd.get("right")
    index_left = collectText(left)
    index_right = collectText(right)
    return index_left, index_right


def extract_depth(dd, netname):
    """
    Extracting the range from the CST:
      0. Find the net in question
         trace[-1] (key) == "text", val == net name
         trace[-2] == "name"
         trace[-3] == some int index // ignore this one
         trace[-4] == "declarators"
      1. Back up to same level as "name", and get val associated with key "dimensions"
      2. Take the zero-th element, because we're not supporting any higher dimensions
         dd = dimensions[0]
         specifier = dd.get("specifier")
         selector = specifier.get("selector")
         left  = selector.get("left")
         range = selector.get("range")
         right = selector.get("right")
      2. Confirm range.get("kind") == "Colon"
         Assemble text in "left" and "right"
    """
    traces = []
    def get_subtrace(trace, val):
        if len(trace) < 4:
            return False
        if (val == netname) and (trace[-1] == "text") and (trace[-2] == "name") and (trace[-4] == "declarators"):
            # Normal nets
            traces.append((0, trace.copy()))
        elif (val == netname) and (trace[-1] == "text") and (trace[-2] == "name"):
            # Ports
            traces.append((1, trace.copy()))
        return False
    sw = StructWalker(dd)
    sw.walk(do=get_subtrace)
    if len(traces) == 0:
        print(f"    WARNING: Found no range for: {netname}")
        return None, None
    matchtype, trace = traces[0]
    #print(trace)
    _dd = dd
    if matchtype == 0:
        offset = -2
    elif matchtype == 1:
        offset = -3
    for key in trace[:offset]:
        _dd = _dd[key]
    if matchtype == 0:
        # Normal nets
        newdd = _dd["dimensions"][0]["specifier"]["selector"]
    elif matchtype == 1:
        # Ports
        newdd = _dd["header"]["dataType"]["dimensions"][0]["specifier"]["selector"]
    else:
        return None, None
    left = newdd.get("left")
    _range = newdd.get("range")
    if _range.get("kind") != "Colon":
        raise Exception("This don't look right")
    right = newdd.get("right")
    index_left = collectText(left)
    index_right = collectText(right)
    return index_left, index_right


class SlangParsingError(Exception):
    def __init__(self, msg):
        super().__init__(msg)


class Broken(Exception):
    def __init__(self, msg):
        super().__init__(msg)


#==============================================================================
# Finder Functions
#==============================================================================
def get_modules(trace, val):
    """slang"""
    if hasattr(val, "get"):
        kind = val.get("kind", None)
        body = val.get("body", None)
        if kind == "Instance" and hasattr(body, "items"):
            return True
    return False


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


def get_instances(trace, val):
    """slang"""
    if hasattr(val, "get"):
        kind = val.get("kind", None)
        if kind == "Instance":
            return True
    return False


def get_ports(trace, val):
    if hasattr(val, "get"):
        kind = val.get("kind", None)
        if kind == "Port":
            return True
    return False


def get_params(trace, val):
    if hasattr(val, "get"):
        kind = val.get("kind", None)
        if kind == "Parameter":
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

    # Default value for attributes without one
    default_attrval = 1

    def __init__(self, filelist, top=None, include_dirs=None, sv=False):
        for filename in filelist:
            if not os.path.exists(filename):
                raise Exception(f"File {filename} not found")
                return None
        self._filelist = filelist
        self._top = top
        self._top_hash = None
        self._include_dirs = include_dirs
        self._resolved = False
        self.ast = None
        self.ast_walker = None
        self.cst = None
        self.cst_walker = None
        self.cst_dict = {}
        self.valid = self.parse()
        self._getTopHash()

    def _slang_cmd(self, ast=True):
        filestr = " ".join(self._filelist)
        scopestr = ""
        if self._top is not None:
            topstr = f" --top {self._top}"
            if ast:
                scopestr = f" --ast-json-scope {self._top}"
        else:
            topstr = ""
        if self._include_dirs is not None and len(self._include_dirs) > 0:
            incstr = " ".join([f"-I {inc}" for inc in self._include_dirs])
        else:
            incstr = ""
        # NOTE --cst-json isn't included in a release yet (as of v9.1), but was introduced in commit 805e160fac on 8/8/25
        # TODO experiment with pyslang (much more of a pain to install but could be a lot better than walking the JSON manually)
        slang_args="-q --ignore-unknown-modules --timescale=1ns/1ns --allow-toplevel-iface-ports"
        if ast:
            slang_args += " --ast-json-source-info"
            if not SLANG_TYPE_IS_STRING:
                slang_args += " --ast-json-detailed-types"
        if ast:
            jscmd = "--ast-json"
        else:
            jscmd = "--cst-json"
        scmd = f'slang -DSLANG {incstr}{filestr}{topstr}{scopestr} {slang_args} {jscmd} -'
        return scmd

    def create_ast(self):
        err = None
        scmd = self._slang_cmd(ast=True)
        try:
            jsfile = subprocess.check_output(scmd, shell=True).decode('latin-1')
        except subprocess.CalledProcessError as e:
            err = str(e)
        if err is not None:
            raise SlangParsingError(err)
        dd = json.loads(jsfile)
        self.ast = dd
        self.ast_walker = StructWalker(dd)
        return

    def create_cst(self):
        err = None
        scmd = self._slang_cmd(ast=False)
        try:
            jsfile = subprocess.check_output(scmd, shell=True).decode('latin-1')
        except subprocess.CalledProcessError as e:
            err = str(e)
        if err is not None:
            raise SlangParsingError(err)
        dd = json.loads(jsfile)
        self.cst = dd
        self.cst_walker = StructWalker(dd)
        return

    def parse(self):
        self.create_ast()
        self.create_cst()
        self._resolved = True
        #self.find_top_module()
        #self.sort_nets()
        return

    def get_modules(self):
        """Returns iterator.
        Usage example:
            for mod_name, mod_dict in parser.get_modules():
                for net_dict in parser.gbnetsIterator(mod_dict):
                    netname = net_dict.get("name")
                    # etc
                for inst_dict in parser.get_instances(mod_dict):
        """
        for key, mod_dict in self._get_modules_iter():
            mod_hash = int(mod_dict["body"]["addr"])
            yield (mod_hash, mod_dict)

    def _get_modules_iter(self):
        return self.ast_walker.iter_walk(do=get_modules)

    @classmethod
    def get_module_name(cls, mod_dict, mod_hash=None):
        """Note: mod_hash is not used but is needed to preserve a unifiied API with the yosys version"""
        body = mod_dict["body"]
        mod_name = body["name"]
        return mod_name

    @classmethod
    def get_instances(cls, mod_dict):
        this_mod_name = cls.get_module_name(mod_dict)
        jb = StructWalker(mod_dict)
        _iter = jb.iter_walk(do=get_instances, depth=4)
        for trace, val in _iter:
            #print(f"1234: trace = {trace};\n *val = {strStruct(val, depth=1)}")
            inst_name = val.get("name")
            body = val.get("body")
            if hasattr(body, "items"): # body is a dict, phew
                # mod_hash in yosys is just the (sometimes mangled) module name
                mod_name = body["name"]
                addr = int(body["addr"])
            else: # dammit; body is a string - gotta find the dict
                addr, mod_name = _split_body(body)
                addr = int(addr)
            if mod_name == this_mod_name:
                # skip this weird little slang thing where it returns its own instance
                continue
            attrs = val.get("attributes", {})
            inst_dict = {
                "inst_name": inst_name,
                "inst_hash": addr,
                "mod_name": mod_name,
                "attributes": attrs,
                "source": None,
            }
            yield inst_dict
        return

    def gbnetsIterator(self, sub_ast):
        module_name = self.get_module_name(sub_ast)
        sub_cst = self.get_CST_module_dict(module_name)
        return self._gbnetsIterator(sub_ast, sub_cst)

    @staticmethod
    def _gbnetsIterator(sub_ast, sub_cst):
        module_name = sub_ast.get("name")
        #sub_cst_walker = StructWalker(sub_cst)
        sub_ast_walker = StructWalker(sub_ast)
        _iter = sub_ast_walker.iter_walk(do=get_gbnets, depth=4)
        for key, val in _iter:
            gbattrs = {}
            attrs = val.get("attributes")
            for attr in attrs:
                attrname = attr.get("name")
                attrval  = attr.get("value")
                if attrname.startswith("ghostbus"):
                    # TODO put this in a different layer (it's violating encapsulation)
                    # Why not just include all attributes?
                    if attrname == "ghostbus_addr":
                        attrval = slang_attrval_int_to_int(attrval)
                    else:
                        attrval = slang_attrval_int_to_string(attrval)
                    if attrval is None:
                        attrval = self.default_attrval
                    gbattrs[attrname] = attrval
            netname = val.get("name", None)
            _type = val.get("type", None)
            initval = val.get("initializer", {}).get("constant", 0)
            index_hi, index_lo = None, None
            elem_hi, elem_lo = None, None
            signed = False
            if not hasattr(_type, "items"):
                nettype, index_hi, index_lo, signed, elem_lo, elem_hi = parse_typestr(_type)
            else:
                nettype = _type.get("name")
                _drange = _type.get("range", None)
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
            if index_hi is not None and index_lo is not None:
                index_hi_str, index_lo_str = extract_range(sub_cst, netname)
            else:
                index_hi_str, index_lo_str = (None, None)
            elem_lo = int(elem_lo) if elem_lo is not None else None
            elem_hi = int(elem_hi) if elem_hi is not None else None
            if None in (elem_hi, elem_lo):
                array = None
                array_str = (None, None)
            else:
                array = (elem_hi, elem_lo)
                array_str = extract_depth(sub_cst, netname)
            netdict = {
                "name": netname,
                "type": nettype,
                "range": (index_hi, index_lo),
                "range_str": (index_hi_str, index_lo_str),
                "attributes": gbattrs,
                "src" : src,
                "depth": array,
                "depth_str": array_str,
                "initval": initval,
                "signed": False, # TODO Dammit. I can't find this in the AST.  Do I really need to dig into the CST for this one?
            }
            yield netdict
        return

    @staticmethod
    def get_instance_name(inst_dict):
        inst_name = inst_dict["inst_name"]
        return inst_name

    @staticmethod
    def get_instance_module_name(inst_dict):
        return inst_dict["mod_name"]

    @staticmethod
    def _extract_top(preamble):
        # TODO DEPRECATE?
        restr = r"^Top level design units:" + "\n" + r"\s+(\w+)"
        _match = re.search(restr, preamble)
        if _match:
            topname = _match.groups()[0]
            return topname
        return None

    def _get_CST_module_dict(self, module_name):
        def find_module(trace, val):
            if not hasattr(val, "get"):
                return False
            kind = val.get("kind")
            if kind != "ModuleDeclaration":
                return False
            header = val.get("header")
            header_name = header.get("name")
            if (header_name.get("kind") == "Identifier") and (header_name.get("text") == module_name):
                return True
            return False
        _iter = self.cst_walker.iter_walk(do=find_module)
        for key, val in _iter:
            return val
        return None

    def get_CST_module_dict(self, module_name):
        if module_name in self.cst_dict.keys():
            return self.cst_dict[module_name]
        mod_dict = self._get_CST_module_dict(module_name)
        if mod_dict is not None:
            self.cst_dict[module_name] = mod_dict
        return mod_dict

    def find_top_module(self):
        # TODO DEPRECATE?
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
        _dict = self.ast_walker.selectPart()
        if self._resolved:
            return _dict
        design_dict = _dict["design"]
        members_list = design_dict["members"]
        for mod_dict in members_list:
            if mod_dict["name"] == self._top:
                return mod_dict
        return None

    def getTopGenerator(self):
        top_dict = self.getTopDict()
        #print(strStruct(top_dict, depth=1))
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
        # TODO DEPRECATE/delete this in favor of 'get_instances'
        top_dict = self.getTopDict()
        #print("================================")
        #print(strStruct(top_dict, depth=2))
        members_list = top_dict["body"]["members"]
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

    def isTop(self, module_name):
        top_dict = self.getTopDict()
        mod_dict = top_dict.get(module_name, None)
        if mod_dict is not None:
            for attr in mod_dict["attributes"]:
                if attr == "top":
                    return True
        return False

    def _getTopHash(self):
        if self._top_hash is None and self._top is not None:
            top_dict = self.getTopDict()
            self._top_hash = int(top_dict["body"]["addr"])
        return self._top_hash

    @classmethod
    def getPorts(cls, mod_dict):
        jb = StructWalker(mod_dict)
        return jb.iter_walk(do=get_ports, depth=4)

    @classmethod
    def getParams(cls, mod_dict):
        jb = StructWalker(mod_dict)
        return jb.iter_walk(do=get_params, depth=4)

    def getTopName(self):
        return self.modname

    def __str__(self):
        return "VParser(Uninitialized)"

    def __repr__(self):
        return self.__str__()

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
    parser = argparse.ArgumentParser("Parse a Verilog/SystemVerilog Design")
    parser.add_argument("-d", "--depth", default=4, help="Depth to browse from the partselect.")
    parser.add_argument("-s", "--select", default=None, help="Partselect string.")
    parser.add_argument("-t", "--top", default=None, help="Explicitly specify top module for hierarchy.")
    parser.add_argument("files", default=None, action="append", nargs="+", help="Source files.")
    args = parser.parse_args()
    vp = VParser(args.files[0], top=args.top, sv=True)
    #print(vp.strToDepth(int(args.depth), args.select))
    for key, mod_dict in vp.get_modules():
        name = mod_dict["name"]
        body = mod_dict["body"]
        print(f"key = {key}; name = {name}")
        #print([key for key in mod_dict["body"].keys()])
        for net_dict in vp.gbnetsIterator(body):
            netname = net_dict.get("name")
            print(f"  netname = {netname}")
            # etc
        #for inst_dict in vp.get_instances(mod_dict):
        for inst_dict in vp.getInstGenerator(mod_dict):
            inst_name = inst_dict["inst_name"]
            mod_name = inst_dict["mod_name"]
            print(f"  {inst_name} of {mod_name}")
    return True


if __name__ == "__main__":
    doBrowse()
