#! python3

# GhostBus top level

import math
import re

from yoparse import VParser, srcParse
from memory_map import MemoryRegion, Register, Memory, bits

# When Yosys generates a JSON, it follows this structure:
#   modules: {
#     mod_inst : {},
#   }
# where 'mod_inst' is a special identifier for not just every module present in the
# design, but every unique instance (uniqueness determined by module type and
# parameter values).
# For any instantiated parameterized modules (when hierarchy set), their names are
# listed as "$paramod$HASH\mod_name" where 'HASH' is a 40-character hex string
# which is probably just randomly generated as a hashmap key.

# I'll need to keep these unique identifiers internally, but replace the hash stuff
# with the hierarchy of the particular instance (which is also unique) before
# generating the memory map.

class ModuleInstance():
    def __init__(self, module_type, inst_name, instances=()):
        self.type = module_type
        self.name = inst_name
        self.instances = instances

    def __str__(self):
        instances = strDict(self.instances)
        return f"ModuleInstance({self.type}, {self.name})"

    def __repr__(self):
        return self.__str__()

    def items(self):
        return self.instances.items()

    def __len__(self):
        return self.instances.__len__()

    def __setitem__(self, key, value):
        self.instances[key] = value
        return

class WalkDict():
    def __init__(self, dd, parent=None, key=None, verbose=False):
        self._verbose = verbose
        self._dd = dd
        self._key = key
        self._parent = parent
        # Transform whole structure into a WalkDict
        for key, val in self._dd.items():
            if key is None:
                print("WARNING! key is None! val = {val}")
            if hasattr(val, "items"):
                self._dd[key] = self.__class__(val, parent=self, key=key)
        self._mark = False
        return

    def _print(self, *args, **kwargs):
        if self._verbose:
            print(*args, **kwargs)
        return

    def __len__(self):
        return self._dd.__len__()

    def get(self, item, default=None):
        return self._dd.get(item, default=default)

    def __getitem__(self, item):
        return self._dd.__getitem__(item)

    def __setitem__(self, item, value):
        return self._dd.__setitem__(item, value)

    def items(self):
        return self._dd.items()

    def reset_node(self):
        """Reset just this node"""
        self._mark = False
        return

    def reset(self):
        """Reset this branch"""
        self._mark = False
        for key, val in self._dd.items():
            if hasattr(val, "reset"):
                val.reset()
        return

    def mark(self):
        self._mark = True
        return

    def marked(self):
        return self._mark

    def walk(self):
        self.reset()
        rval = self._get_leaf()
        self._print(f"rval = {rval}")
        return iter(rval)

    def __iter__(self):
        return self

    def _get_leaf(self):
        if len(self._dd) == 0:
            if not self._mark:
                self._print("leaf returning self")
                return self
            else:
                self._print("leaf pass to parent")
                if self._parent is None:
                    self._print("leaf is done?")
                    return None
                return self._parent._get_leaf()
        unmarked_child = None
        for key, val in self._dd.items():
            if hasattr(val, "marked"):
                if not val.marked():
                    unmarked_child = val
                    break
        if unmarked_child is not None:
            self._print("parent pass to unmarked child")
            return unmarked_child._get_leaf()
        else:
            if not self._mark:
                self._print("returning self")
                return self
            elif self._parent is not None:
                self._print("pass to parent")
                return self._parent._get_leaf()
        self._print("done")
        return None

    def __next__(self):
        rval = self._get_leaf()
        if rval is None:
            raise StopIteration
        if hasattr(rval, "mark"):
            rval.mark()
        return (rval._key, rval)


class MemoryTree(WalkDict):
    def __init__(self, dd, parent=None, key=None, verbose=False, hierarchy=None, inst_hash=None):
        #super().__init__(dd, parent=parent, key=key, verbose=verbose)
        self._verbose = verbose
        self._dd = dd
        self._key = key
        self._parent = parent
        # Transform whole structure into a MemoryTree
        for key, inst_dict in self._dd.items():
            #print(f"key, inst_dict = {key}, {inst_dict}")
            inst_name = key[0]
            inst_hash = key[1]
            hier = (inst_name,)
            self._dd[key] = self.__class__(inst_dict, parent=self, key=key, inst_hash=inst_hash, hierarchy=hier)
            #if hasattr(val, "items"):
            #    self._dd[key] = self.__class__(val, parent=self, key=key)
        self._mark = False
        if inst_hash is not None:
            module_name = get_modname(inst_hash)
        else:
            module_name = None
        self._mr = MemoryRegion(label=module_name, hierarchy=hierarchy)
        self._label = None
        if hierarchy is not None:
            self._label = hierarchy[0]
        self._resolved = False

    def __str__(self):
        if self._mr._hierarchy is not None:
            label = self._mr._hierarchy[-1]
        elif self._mr.label is not None:
            label = self._mr.label
        else:
            label = "Unknown"
        return "MemoryTree({})".format(label)

    def __repr__(self):
        return self.__str__()

    @property
    def label(self):
        if self._label is None:
            return self._mr.label
        return self._label

    def resolve(self):
        if not self._resolved:
            for key, node in self.walk():
                if node is None:
                    print(f"WARNING! node is None! key = {key}")
                if hasattr(node, "memsize"):
                    if node.memsize > 0:
                        node.memory.shrink()
                        if node._parent is not None:
                            #print("Adding {} to {}".format(node.label, node._parent.label))
                            node._parent.memory.add_item(node.memory)
                    else:
                        print(f"Node {node.label} has memsize {node.memsize}")
                if hasattr(node, "mark"):
                    node.mark()
        return self._mr

    @property
    def memory(self):
        return self._mr

    @memory.setter
    def memory(self, value):
        if not isinstance(value, MemoryRegion):
            raise Exception("MemoryTree can only accept MemoryRegon instances as memory")
        self._mr = value
        return

    @property
    def memsize(self):
        return self._mr.size


def print_dict(dd, depth=-1):
    print(strDict(dd, depth=depth))


def strDict(_dict, depth=-1):
    def _strToDepth(_dict, depth=0, indent=0):
        """RECURSIVE"""
        if depth == 0:
            return []
        l = []
        sindent = " "*indent
        for key, val in _dict.items():
            if hasattr(val, 'keys'):
                l.append(f"{sindent}{key} : dict size {len(val)}")
                l.extend(_strToDepth(val, depth-1, indent+2))
            else:
                l.append(f"{sindent}{key} : {val}")
        return l
    l = []
    l.extend(_strToDepth(_dict, depth, indent=2))
    return '\n'.join(l)


def ismodule(s):
    restr = "^\$(\w+)\$"
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


def get_modname(s):
    restr = r"^\$(\w+)\$([0-9a-fA-F]+)\\(\w+)"
    _match = re.search(restr, s)
    if _match:
        modname = _match.groups()[2]
        return modname
    return s

def vhex(num, width):
    #print("width = {}".format(width))
    fmt = "{{:0{}x}}".format(width>>2)
    #print("fmt = {}".format(fmt))
    return "{}'h{}".format(width, fmt.format(num))

class GhostBusser(VParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.memory_map = None
        self._bus = {
            'clk': None,
            'addr': None,
            'din': None,
            'dout': None,
            'we': None,
            'aw': None,
            'dw': None,
        }

    def get_map(self):
        ghostmods = {}
        modtree = {}
        top_mod = None
        top_dict = self._dict["modules"]
        for module, mod_dict in top_dict.items():
            mod_hash = module
            if not hasattr(mod_dict, "items"):
                continue
            for attr in mod_dict["attributes"]:
                if attr == "top":
                    top_mod = mod_hash
            # Check for instantiated modules
            modtree[mod_hash] = {}
            cells = mod_dict.get("cells")
            if cells is not None:
                for inst_name, inst_dict in cells.items():
                    if ismodule(inst_name):
                        modtree[mod_hash][inst_name] = inst_dict["type"]
            mr = None
            # Check for regs
            netnames = mod_dict.get("netnames")
            if netnames is not None:
                for netname, net_dict in netnames.items():
                    attr_dict = net_dict["attributes"]
                    source = attr_dict.get('src', None)
                    hit = False
                    addr = None
                    for attr, val in attr_dict.items():
                        if attr.lower() in ("ghostbus_addr", "ghostbus_ha", "ghostbus_csr", "ghostbus_ram"):
                            # Found a hit
                            hit = True
                            if attr.lower() == "ghostbus_addr":
                                addr = int(val, 2)
                        elif attr.lower() in ("ghostbus_port",):
                            dw = len(net_dict['bits'])
                            self._handleBus(netname, val, dw, source)
                    if hit:
                        dw = len(net_dict['bits'])
                        reg = MetaRegister(name=netname, dw=dw, meta=source)
                        if mr is None:
                            module_name = get_modname(mod_hash)
                            mr = MemoryRegion(label=module_name, hierarchy=(module_name,))
                            print("created mr label {}".format(mr.label))
                        mr.add(width=0, ref=reg, addr=addr)
            # Check for RAMs
            memories = mod_dict.get("memories")
            if memories is not None:
                for memname, mem_dict in memories.items():
                    attr_dict = mem_dict["attributes"]
                    hit = False
                    addr = None
                    for attr, val in attr_dict.items():
                        if attr.lower().startswith("ghostbus"):
                            # Found a hit
                            hit = True
                            if attr.lower() == "ghostbus_addr":
                                addr = int(val, 2)
                    if hit:
                        source = mem_dict['attributes']['src']
                        dw = int(mem_dict["width"])
                        size = int(mem_dict["size"])
                        aw = math.ceil(math.log2(size))
                        mem = MetaMemory(name=memname, dw=dw, aw=aw, meta=source)
                        if mr is None:
                            module_name = get_modname(mod_hash)
                            mr = MemoryRegion(label=module_name, hierarchy=(module_name,))
                            print("created mr label {}".format(mr.label))
                        mr.add(width=aw, ref=mem, addr=addr)
            if mr is not None:
                ghostmods[mod_hash] = mr
        self._validateBus()
        self._top = top_mod
        #print_dict(modtree)
        modtree = self.build_modtree(modtree)
        #print("===============================================")
        #print_dict(modtree)
        memtree = self.build_memory_tree(modtree, ghostmods)
        #print("***********************************************")
        self.memory_map = memtree.resolve()
        self.memory_map.shrink()
        self.memory_map.print(4)
        return ghostmods

    def _handleBus(self, netname, val, dw, source):
        val = val.strip().lower()
        val_map = {
            # Acceptable name, dict key
            "clk": "clk",
            "addr": "addr",
            "din": "din",
            "dout": "dout",
            "we": "we",
            "wen": "we", # alias
        }
        if val not in [key for key in val_map.keys()]:
            err = "Invalid value ({}) for attribute 'ghostbus_port'.".format(val) + \
                  "  Valid values are {}".format([key for key in self._bus.keys()])
            raise Exception(err)
        busval = self._bus[val]
        if busval is None:
            self._bus[val] = (netname, source)
            # Get width of addr/data
            if val in ("addr", "din", "dout"):
                widthint = dw
                widthstr = self._getWidth(source)
                if val == "addr":
                    self._bus["aw"] = (widthint, None)
                    self._bus["aw_str"] = (widthstr, None)
                else:
                    existing_dw = self._bus["dw"]
                    if existing_dw is not None and existing_dw[0] != widthint:
                        raise Exception("Unsupported ghostbus din and dout are not the same width!")
                    self._bus["dw"] = (widthint, None)
                    self._bus["dw_str"] = (widthstr, None)
        else:
            raise Exception("'ghostbus_port={}' already defined at {}".format(val.strip().lower(), busval[1]))
        return

    def _validateBus(self):
        if None in [v for v in self._bus.values()]:
            self._busValid = False
        else:
            self._busValid = True
        return self._busValid

    def getBusDict(self):
        if not self._busValid:
            serr = ["Incomplete bus definition"]
            for key, val in self._bus.items():
                if val is None:
                    serr.append("  Missing: {}".format(key))
            raise Exception("\n".join(serr))
        dd = {}
        for key, val in self._bus.items():
            dd[key] = val[0] # Discarding the "source" part
        return dd

    @classmethod
    def _getWidth(cls, source):
        snippet, offset = MetaRegister._getSnippet(source)
        if snippet is not None:
            _rangeStr = MetaRegister._findRangeStr(snippet, offset)
            split = _rangeStr.split(':')
            if len(split) > 1:
                _range = (split[0], split[1])
            else:
                return None
        # Assume _range[1] is always '0'
        return "{}+1".format(_range[0])

    def build_modtree(self, dd):
        top = self._top
        if top is None:
            raise Exception("I don't know how to do this without top specified")
        modtree = {}
        for module, mod_dict in dd.items():
            if module == top:
                modtree[module] = {}
        if len(modtree) == 0:
            raise Exception("Could not find top: {}".format(top))
        for module, instances_dict in dd.items():
            new_mod_dict = {}
            for inst_name, inst_key in instances_dict.items():
                #new_mod_dict[inst_name] = ModuleInstance(inst_key, inst_name, dd[inst_key])
                dict_key = (inst_name, inst_key)
                new_mod_dict[dict_key] = dd[inst_key]
            dd[module] = new_mod_dict
        return ModuleInstance(top, top, dd[top])

    def build_memory_tree(self, modtree, ghostmods):
        # First build an empty dict of MemoryRegions
        # Start from leaf,
        #print("++++++++++++++++++++++++++++++++++++++++++++")
        modtree = MemoryTree(modtree, key=(self._top, self._top), hierarchy=(self._top,))
        #print("////////////////////////////////////////////")
        for key, val in modtree.walk():
            #print("{}: {}".format(key, val))
            if key is None:
                break
            inst_name, inst_hash = key
            module_name = get_modname(inst_hash)
            mr = ghostmods.get(inst_hash, None)
            hier = (inst_name,)
            if mr is not None and hasattr(val, "memory"):
                mrcopy = mr.copy()
                mrcopy.label = module_name
                mrcopy.hierarchy = hier
                val.memory = mrcopy
            else:
                print(f"no {key} in ghostmods")
                val.memory = MemoryRegion(label=module_name, hierarchy=hier)
        # If leaf is a ghostmod, add its MemoryRegion to its parent's MemoryRegion
        return modtree

class MetaRegister(Register):
    """This class expands on the Register class by including not just its
    resolved aw/dw, but also the unresolved strings used to declare aw/dw
    in the source code."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rangeStr = None
        self._depthstr = None
        self.range = (None, None)
        self.depth = ('0', '0')

    def _readRangeDepth(self):
        if self._rangeStr is not None:
            return True
        if self.meta is None:
            return False
        snippet, offset = self._getSnippet(self.meta)
        if snippet is not None:
            self._rangeStr = self._findRangeStr(snippet, offset)
            split = self._rangeStr.split(':')
            if len(split) > 1:
                self.range = (split[0], split[1])
            else:
                return False
        return True

    @classmethod
    def _getSnippet(cls, yosrc):
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

    @classmethod
    def _findRangeStr(cls, snippet, offset):
        """Start at char offset. Read backwards. Look for ']' to open a range.
        If we find the keyword 'reg' before the ']', we'll break and decide the
        reg is 1-bit."""
        grouplevel = 0
        endix = None
        rangestr = None
        for n in range(offset, -1, -1):
            char = snippet[n]
            slc = snippet[n:n+5].replace('\n', ' ').replace('.', ' ') # Room for whitespace+'r'+'e'+'g'+whitespace
            if slc == " reg ":
                rangestr = "0:0"
                break
            # Handle the oddball case where 'snippet' starts with the keyword 'reg'
            elif (n == 0) and (slc[:4] == "reg "):
                rangestr = "0:0"
                break
            elif char == ']': # walking backwards
                if grouplevel == 0:
                    endix = n
                grouplevel += 1
            elif char == '[':
                grouplevel -= 1
                if grouplevel == 0:
                    rangestr = snippet[n+1:endix]
                    break
        return rangestr

    def getInitStr(self, bus):
        # Ghostbus registers are already initialized
        return ""

# TODO - Combine this class with MetaRegister
class MetaMemory(Memory):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rangeStr = None
        self._depthStr = None
        self.range = (None, None)
        self.depth = (None, None)

    def _readRangeDepth(self):
        if self._rangeStr is not None:
            return True
        if self.meta is None:
            return False
        snippet, offset = self._getSnippet(self.meta)
        _pass = True
        if snippet is not None:
            self._rangeStr = self._findRangeStr(snippet, offset)
            split = self._rangeStr.split(':')
            if len(split) > 1:
                self.range = (split[0], split[1])
            else:
                _pass = False
            self._depthStr = self._findDepthStr(snippet, offset)
            split = self._depthStr.split(':')
            if len(split) > 1:
                self.depth = (split[0], split[1])
            else:
                _pass = False
        return _pass

    @classmethod
    def _getSnippet(cls, yosrc):
        return MetaRegister._getSnippet(yosrc)

    @classmethod
    def _findRangeStr(cls, snippet, offset):
        return MetaRegister._findRangeStr(snippet, offset)

    @classmethod
    def _findDepthStr(cls, snippet, offset):
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

    def getInitStr(self, bus, local_aw=None):
        # localparam FOO_RAM_AW = $clog2(RD);
        # wire en_foo_ram = gb_addr[8:3] == 6'b001000;
        if local_aw is None:
            local_aw = bus['aw']
        divwidth = local_aw - self.aw
        ss = (
            f"localparam {self.name.upper()}_AW = $clog2({self.depth[1]}+1);",
            f"wire en_{self.name} = {bus['addr']}[{local_aw-1}:{self.aw}] == {vhex(self.base>>self.aw, divwidth)};",
        )
        return "\n".join(ss)

class Decoder():
    def __init__(self, memregion, bus):
        self.mod = memregion
        self.bus = bus
        self.aw = self.mod.aw
        self.inst = self.mod.hierarchy[-1]
        self.name = self.mod.label
        self.base = self.mod.base
        self.submods = []
        self.rams = []
        self.csrs = []
        self.max_local = 0
        for start, stop, ref in memregion.get_entries():
            if isinstance(ref, MetaRegister):
                ref._readRangeDepth()
                self.csrs.append(ref)
            elif isinstance(ref, MetaMemory):
                ref._readRangeDepth()
                self.rams.append(ref)
            elif isinstance(ref, MemoryRegion):
                self.submods.append((start, Decoder(ref, self.bus)))
            if isinstance(ref, Register): # Should catch MetaRegister and MetaMemory
                if stop > self.max_local:
                    self.max_local = stop
        if self.max_local == 0:
            self.no_local = True
        else:
            self.no_local = False
        self.local_aw = bits(self.max_local)
        self._def_file = "defs.vh"

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
        cw = flatten_bits(csr_writeable)
        for csr in csrs:
            print("{}.{}: 0x{:x}".format(csr._domain[1], csr.name, csr._domain[0] + csr.base))
            wa = 1 if (csr.access & Register.WRITE) > 0 else 0
            csr_writeable.append(wa)
        print("RAMs:")
        ram_writeable = []
        rw = flatten_bits(ram_writeable)
        for ram in rams:
            print("{}.{}: 0x{:x}".format(ram._domain[1], ram.name, ram._domain[0] + ram.base))
            wa = 1 if (ram.access & Register.WRITE) > 0 else 0
            ram_writeable.append(wa)
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
            "integer N;",
            "initial begin",
            "  for (N=0; N<nCSRs; N=N+1) begin: CSR_Init",
        ]
        # Initialize CSR info
        for csr in csrs:
            ss.append(f"    GHOSTBUS_ADDRS[N] = {vhex(csr._domain[0] + csr.base, aw)}; // {csr._domain[1]}.{csr.name}")
            ss.append(f"    GHOSTBUS_INITVALS[N] = 0; // TODO!") # TODO
            randval = random.randint(0, (1<<csr.dw)-1) # Random number within the range of the CSR's width
            ss.append(f"    GHOSTBUS_RANDVALS[N] = {vhex(randval, dw)}; // 0 <= x <= 0x{(1<<csr.dw) - 1:x}")
        ss.append("  end;")
        # Initialize RAM info
        ss.append("  for (N=0; N<nRAMs; N=N+1) begin: RAM_Init")
        for ram in rams:
            ss.append(f"    GHOSTBUS_RAM_BASES[N] = {vhex(ram._domain[0] + ram.base, aw)}; // {ram._domain[1]}.{ram.name}")
            ss.append(f"    GHOSTBUS_RAM_WIDTHS[N] = {vhex(ram.dw, dw)}; // TODO - may not be accurate due to parameterization...")
            ss.append(f"    GHOSTBUS_RAM_DEPTHS[N] = {vhex((1<<ram.aw), aw)}; // TODO - may not be accurate due to parameterization...")
        ss.append("  end;")
        ss.append("end;")
        if False:
            print("\n".join(ss))
            return
        with open(filename, 'w') as fd:
            fd.write("\n".join(ss))
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
        ss = (
            "// Ghostbus ports",
            f",input  {self.bus['clk']}",
            f",input  [{self.bus['aw']-1}:0] {self.bus['addr']}",
            f",input  [{self.bus['dw']-1}:0] {self.bus['dout']}",
            f",output [{self.bus['dw']-1}:0] {self.bus['din']}",
            f",input  {self.bus['we']}",
        )
        return "\n".join(ss)

    def GhostbusSubmodMap(self):
        """Generate the necessary ghostbus Verilog port map for this instance
        within its parent module."""
        clk = self.bus['clk']
        addr = self.bus['addr']
        dout = self.bus['dout']
        din = self.bus['din']
        we = self.bus['we']
        ss = (
            f",.{clk}({clk})    // input",
            f",.{addr}({addr}_{self.inst})  // input [{self.bus['aw']-1}:0]",
            f",.{dout}({dout})  // input [{self.bus['dw']-1}:0]",
            f",.{din}({din}_{self.inst}) // output [{self.bus['dw']-1}:0]",
            f",.{we}({we}_{self.inst}) // input",
        )
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
        ss = (
            f"// submodule {self.inst}",
            f"wire [{self.bus['dw']-1}:0] {self.bus['din']}_{self.inst};",
            f"wire en_{self.inst} = {self.bus['addr']}[{busaw-1}:{self.aw}] == {vhex(base_rel>>self.aw, divwidth)}; // 0x{base_rel:x}-0x{end:x}",
            f"wire [{busaw-1}:0] {self.bus['addr']}_{self.inst} = {{{vhex(0, divwidth)}, {self.bus['addr']}[{self.aw-1}:0]}}; // address relative to own base (0x0)",
            f"wire {self.bus['we']}_{self.inst}={self.bus['we']} & en_{self.inst};",
        )
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
                ss.append(f"              en_{inst} ? {self.bus['din']}_{inst} :")
        ss.append(f"              {vhex(0, self.bus['dw'])};")
        return "\n".join(ss)

    def busDecoding(self):
        _ramwrites = self.ramWrites()
        if len(_ramwrites) == 0:
            ramwrites = "// No rams"
        else:
            ramwrites = _ramwrites
        _csrwrites = self.csrWrites()
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
            extraend = "  end // ram reads"
            ramreads = "// No rams"
        else:
            ramreads = _ramreads
        _csrreads = self.csrReads()
        if len(_csrreads) == 0:
            if len(_ramreads) > 0:
                midend = " else begin"
            csrreads = "// No CSRs"
        else:
            csrreads = _csrreads
        ss = []
        hasclk = False
        if len(_ramwrites) > 0 or len(_csrwrites) > 0:
            ss.append(f"always @(posedge {self.bus['clk']}) begin")
            ss.append("  // local writes")
            ss.append(f"  if (en_local & {self.bus['we']}) begin")
            ss.append("    " + ramwrites.replace("\n", "\n    "))
            ss.append("    " + csrwrites.replace("\n", "\n    "))
            ss.append(f"  end // if (en_local & {self.bus['we']})")
            hasclk = True
        if len(_ramreads) > 0 or len(_csrreads) > 0:
            if not hasclk:
                ss.append(f"always @(posedge {self.bus['clk']}) begin")
            ss.append("  // local reads")
            ss.append(f"  if (en_local & ~{self.bus['we']}) begin")
            ss.append("    " + ramreads.replace("\n", "\n    ") + midend)
            ss.append(crindent + csrreads.replace("\n", "\n"+crindent))
            ss.append(extraend)
            ss.append(f"  end // if (en_local & ~{self.bus['we']})")
        if hasclk:
            ss.append(f"end // always @(posedge {self.bus['clk']})")
        return "\n".join(ss)

    def csrWrites(self):
        if len(self.csrs) == 0:
            return ""
        ss = [
            "// CSR writes",
            f"casez ({self.bus['addr']}[{self.local_aw-1}:0])",
        ]
        for n in range(len(self.csrs)):
            csr = self.csrs[n]
            ss.append(f"  {vhex(csr.base, self.local_aw)}: {csr.name} <= {self.bus['dout']}[{csr.range[0]}:0];")
        ss.append("endcase")
        return "\n".join(ss)

    def csrReads(self):
        if len(self.csrs) == 0:
            return ""
        ss = [
            "// CSR reads",
            f"casez ({self.bus['addr']}[{self.local_aw-1}:0])",
        ]
        for n in range(len(self.csrs)):
            csr = self.csrs[n]
            ss.append(f"  {vhex(csr.base, self.local_aw)}: local_din <= {{{{{self.bus['dw']}-{csr.range[0]}+1{{1'b0}}}}, {csr.name}}};")
        ss.append("endcase")
        return "\n".join(ss)

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


def testWalkDict():
    dd = {
        'F': {
            'A': {
            },
            'D': {
                'C': {
                    'B': {
                    }
                }
            },
            'E': {
            },
        },
        'K': {
            'I': {
                'G': {
                },
                'H': {
                },
            },
            'J': {
            }
        }
    }
    top = WalkDict(dd, key="top")
    for key, val in top.walk():
        print("{}".format(key), end="")
        counter += 1
    print()
    return

def test():
    import argparse
    parser = argparse.ArgumentParser("Ghostbus Verilog router")
    parser.add_argument("files", default=[], action="append", nargs="+", help="Source files.")
    parser.add_argument("-t", "--top", default=None, help="Explicitly specify top module for hierarchy.")
    args = parser.parse_args()
    vp = GhostBusser(args.files[0], top=args.top) # Why does this end up as a double-wrapped list?
    mods = vp.get_map()
    #print(f"len(mods) = {len(mods)}")
    if False:
        for mod_hash, memoryregion in mods.items():
            print(type(memoryregion))
            #print("mod_hash = {}; type(memoryregion) = {}".format(mod_hash, type(memoryregion)))
            for start, stop, reg in memoryregion.get_entries():
                if hasattr(reg, "_readRangeDepth"):
                    reg._readRangeDepth()
                    print(f"reg.range = {reg.range}; reg.depth = {reg.depth}")
    if False:
        bus = {
            'clk': 'gb_clk',
            'addr': 'gb_addr',
            'din': 'gb_din',
            'dout': 'gb_dout',
            'we': 'gb_we',
            'aw': 12,
            'dw': 32,
        }
    else:
        bus = vp.getBusDict()
    dec = Decoder(vp.memory_map, bus)
    #print(dec.GhostbusDecoding())
    dec.GhostbusMagic(dest_dir="_auto")
    return True

def testExtras():
    import argparse
    parser = argparse.ArgumentParser("Ghostbus Verilog router")
    parser.add_argument("files", default=[], action="append", nargs="+", help="Source files.")
    parser.add_argument("-t", "--top", default=None, help="Explicitly specify top module for hierarchy.")
    args = parser.parse_args()
    gb = GhostBusser(args.files[0], top=args.top) # Why does this end up as a double-wrapped list?
    mods = gb.get_map()
    bus = gb.getBusDict()
    dec = Decoder(gb.memory_map, bus)
    dec.ExtraVerilogMemoryMap("test.vh", bus)

if __name__ == "__main__":
    #test()
    #testWalkDict()
    testExtras()
