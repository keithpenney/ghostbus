#! python3

# GhostBus top level

import math
import re

from yoparse import VParser, srcParse, ismodule, get_modname, get_value, \
                    getUnparsedWidthRange, getUnparsedDepthRange, \
                    getUnparsedWidthAndDepthRange, getUnparsedWidth
from memory_map import MemoryRegion, Register, Memory, bits
from decoder_lb import DecoderLB, vhex

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

class enum():
    """A slightly fancy enum"""
    def __init__(self, names, base=0):
        self._strs = {}
        for n in range(len(names)):
            setattr(self, names[n], base+n)
            self._strs[base+n] = names[n]

    def __getitem__(self, item):
        return getattr(self, item)

    def str(self, val):
        return self._strs[val]


class GhostbusInterface():
    _tokens = [
        "HA",
        "ADDR",
        "PORT",
        "STROBE",
        "STROBE_W",
        "STROBE_R",
        "EXTERNAL",
    ]
    tokens = enum(_tokens, base=0)
    _attributes = {
        "ghostbus":             tokens.HA,
        "ghostbus_ha":          tokens.HA,
        "ghostbus_csr":         tokens.HA,
        "ghostbus_ram":         tokens.HA,
        "ghostbus_port":        tokens.PORT,
        "ghostbus_addr":        tokens.ADDR,
        "ghostbus_strobe":      tokens.STROBE,
        "ghostbus_write_strobe": tokens.STROBE_W,
        "ghostbus_ws":          tokens.STROBE_W,
        "ghostbus_read_strobe": tokens.STROBE_R,
        "ghostbus_rs":          tokens.STROBE_R,
        "ghostbus_ext":         tokens.EXTERNAL,
    }
    @staticmethod
    def handle_token_ha(val):
        """Allow for optional access string specifiers.
        E.g.:
            'r', 'r/o', 'R': readable
            'w', 'w/o', 'W': writeable
            'rw', 'r/w', 'RW': readable and writeable (default)
        """
        if not hasattr(val, "lower"):
            access = Register.RW
        else:
            if val.isnumeric():
                # This is probably a YOSYS-default "0000000000000001" string
                access = Register.RW
            else:
                # Interpret as an access-specifier string
                access = 0
                val = val.strip().lower().replace("/","")
                if 'w' in val:
                    access |= Register.WRITE
                if 'r' in val:
                    access |= Register.READ
        return access

    @staticmethod
    def split_strs(val):
        if hasattr(val, 'split'):
            if ',' in val:
                return [x.strip() for x in val.split(',')]
        return (val,)

    _val_decoders = {
        tokens.HA: handle_token_ha,
        tokens.ADDR: lambda x: int(x, 2),
        tokens.PORT: split_strs,
        tokens.STROBE: lambda x: True,
        tokens.STROBE_W: lambda x: str(x),
        tokens.STROBE_R: lambda x: str(x),
    }

    @classmethod
    def tokenstr(cls, token):
        return cls.tokens.str(token)

    @classmethod
    def decode_attrs(cls, attr_dict):
        rvals = {}
        for attr, attrval in attr_dict.items():
            token = cls._attributes.get(attr, None)
            if token is not None:
                rvals[token] = cls._val_decoders[token](attrval)
                # Some attributes are implied
                if token in (cls.tokens.ADDR, ):
                    rvals[cls.tokens.HA] = cls._val_decoders[cls.tokens.HA](1)
                elif token in (cls.tokens.STROBE, ):
                    # Strobes are write-only
                    rvals[cls.tokens.HA] = cls._val_decoders[cls.tokens.HA]("w")
        return rvals


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


class GhostBusser(VParser):
    # Boolean aliases for clarity
    mandatory = True
    optional = False
    _bus_info = {
        # dict key: ((acceptable names), mandatory?)
        "clk":      (("clk",),  mandatory),
        "addr":     (("addr",), mandatory),
        "din":      (("din",),  mandatory),
        "dout":     (("dout",), mandatory),
        "we":       (("we", "wen"), mandatory),
        "re":       (("re", "ren"), optional),
        "wstb":     (("wstb", "write_strobe"), optional),
        "rstb":     (("rstb", "read_strobe"), optional),
    }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._empty_bus = {}
        for key, data in self._bus_info.keys():
            self._empty_bus[key] = None
        self.memory_map = None
        self._bus = self._empty_bus.copy()
        self._bus['aw'] = None
        self._bus['dw'] = None
        self._ext_dict = {}

    def get_map(self):
        ghostmods = {}
        modtree = {}
        top_mod = None
        top_dict = self._dict["modules"]
        for module, mod_dict in top_dict.items():
            associated_strobes = {}
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
                    token_dict = GhostbusInterface.decode_attrs(attr_dict)
                    # for token, val in token_dict.items():
                    #     print("{}: Decoded {}: {}".format(netname, GhostbusInterface.tokenstr(token), val))
                    source = attr_dict.get('src', None)
                    hit = False
                    access = token_dict.get(GhostbusInterface.tokens.HA, None)
                    addr = token_dict.get(GhostbusInterface.tokens.ADDR, None)
                    write_strobe = token_dict.get(GhostbusInterface.tokens.STROBE_W, None)
                    read_strobe = token_dict.get(GhostbusInterface.tokens.STROBE_R, None)
                    exts = token_dict.get(GhostbusInterface.tokens.EXTERNAL, None)
                    if write_strobe is not None:
                        print("                            write_strobe: {} => {}".format(netname, write_strobe))
                        # Add this to the to-do list to associate when the module is done parsing
                        associated_strobes[netname] = (write_strobe, False)
                    elif read_strobe is not None:
                        print("                            read_strobe: {} => {}".format(netname, read_strobe))
                        associated_strobes[netname] = (read_strobe, True)
                    elif access is not None:
                        dw = len(net_dict['bits'])
                        initval = get_value(net_dict['bits'])
                        reg = MetaRegister(name=netname, dw=dw, meta=source, access=access)
                        reg.initval = initval
                        reg.strobe = token_dict.get(GhostbusInterface.tokens.STROBE, False)
                        # print("{} gets initval 0x{:x}".format(netname, initval))
                        if mr is None:
                            module_name = get_modname(mod_hash)
                            mr = MemoryRegion(label=module_name, hierarchy=(module_name,))
                            # print("created mr label {}".format(mr.label))
                        mr.add(width=0, ref=reg, addr=addr)
                    elif exts is not None:
                        self._handleExt(module, netname, exts, dw, source)
                    ports = token_dict.get(GhostbusInterface.tokens.PORT, None)
                    if ports is not None:
                        dw = len(net_dict['bits'])
                        self._handleBus(netname, ports, dw, source)
            # Check for RAMs
            memories = mod_dict.get("memories")
            if memories is not None:
                for memname, mem_dict in memories.items():
                    attr_dict = mem_dict["attributes"]
                    token_dict = GhostbusInterface.decode_attrs(attr_dict)
                    # for token, val in token_dict.items():
                    #     print("{}: Decoded {}: {}".format(netname, GhostbusInterface.tokenstr(token), val))
                    access = token_dict.get(GhostbusInterface.tokens.HA, None)
                    addr = token_dict.get(GhostbusInterface.tokens.ADDR, None)
                    if access is not None:
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
                for strobe_name, reg_type in associated_strobes.items():
                    associated_reg, _read = reg_type
                    # find the "MetaRegister" named 'associated_reg'
                    # Add the strobe as an associated strobe by net name
                    for start, end, register in mr.get_entries():
                        if register.name == associated_reg:
                            if _read:
                                register.read_strobes.append(strobe_name)
                            else:
                                register.write_strobes.append(strobe_name)
                ghostmods[mod_hash] = mr
        self._bus_valid = self._validateBus(self._bus)
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

    def _handleBus(self, netname, vals, dw, source):
        for val in vals:
            self._handleBusVal(netname, val, dw, source)
        return

    def _handleBusVal(self, netname, val, dw, source):
        val = val.strip().lower()
        val_map = {}
        for key, data in self._bus_info.items():
            for alias in data[0]:
                val_map[alias] = key
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
                widthstr = getUnparsedWidth(source)
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

    def _handleExt(self, module, netname, vals, dw, source):
        if self._ext_dict.get(module, None) is None:
            self._ext_dict[module] = []
        portnames = []
        instnames = []
        if ',' in vals:
            portinst = [x.strip() for x in vals.split(',')]
            for val in portinst:
                if val in self._bus_info.keys():
                    portnames.append(val)
                else:
                    instnames.append(val)
        else:
            val = vals
            if val in self._bus_info.keys():
                # It's a port name
                portnames.append(val)
            else:
                # Assume it's an inst name
                instnames.append(val)
        if len(instnames) > 0:
            if 'dout' in portnames:
                serr = "The 'dout' vector cannot be shared between multiple instances " + \
                      f"({instnames}). See: {source}"
                raise Exception()
        self._ext_dict[module].append((netname, dw, portnames, instnames, source))
        return

    def _resolveExt(self):
        self._ext_modules = {}
        for module, data in self._ext_dict:
            busses = = self._resolveExtModule(module, data)
            self._ext_modules[module] = []
            for instname, bus in busses.items():
                extinst = ExternalModule(instname, ghostbus=self._bus, extbus=bus)
                self._ext_modules[module].append(extinst)
        return

    def _resolveExtModule(self, module, data):
        ext_advice = "If there's only a " + \
                    "single external instance in this module, you must label at " + \
                    "least one net with the instance name, e.g.:\n" + \
                    '  (* ghostbus_ext="inst_name, clk" *) wire ext_clk;' + \
                    "If there is more than one external instance in this module, " + \
                    "you need to include the instance in the attribute value for " + \
                    "each net in the bus (e.g. 'clk', 'addr', 'din', 'dout', 'we')."
        module_instnames = []
        for datum in data:
            netname, dw, portnames, instnames, source = datum
            module_instnames.extend(instnames)
        inst_err = False
        busses = {}
        if len(module_instnames) == 0:
            inst_err = True
        elif len(module_instnames) == 1:
            instname = module_instnames[0]
            bus = self._empty_bus.copy()
            # Every net gets the same instname
            for datum in data:
                netname, dw, portnames, instnames, source = datum
                for portname in portnames:
                    bus[portname] = (netname, dw, source)
            busses[instname] = bus
        else:
            for instname in module_instnames:
                bus = self._empty_bus.copy()
                for datum in data:
                    netname, dw, portnames, instnames, source = datum
                    for net_instname in instnames:
                        if net_instname == instname:
                            for portname in portnames:
                                if bus[portname] is not None:
                                    inst_err = True
                                    existing_source = bus[portname][2]
                                    serr = f"Multiple nets labeled as: {instname}, " + \
                                           f"{portname}. First at {existing_source}, " + \
                                           f"second at {source}.\n" + ext_advice
                                    raise Exception(serr)
                                else:
                                    bus[portname] = (netname, dw, source)
                                if portname in ('din', 'dout'):
                                    if bus['dw'] is not None and bus['dw'] != dw:
                                        if portname == 'din':
                                            othernet = 'dout'
                                        else:
                                            othernet = 'din'
                                        o_net = bus[othernet]
                                        serr = f"Conflicting widths of nets " + \
                                               f"{netname} (width {dw}) and " + \
                                               f"{o_net} (width {bus['dw']}) both" + \
                                               f" associated with inst {instname} " +\
                                               f"of module {module}"
                                        raise Exception(serr)
                                    bus['dw'] = dw
                                elif portname == 'addr':
                                    bus['aw'] = aw
                busses[instname] = bus
        if inst_err:
            serr = "No instance referenced for external bus." + ext_advice
            raise Exception(serr)
        for instname, bus in busses.items():
            if not self._validateBus(bus):
                required_nets = []
                for key, data in self._bus_info.items():
                    required = data[1]
                    if required:
                        required_nets.append(key)
                serr = f"The external bus for instance {instname} in module " + \
                       f"{module} is not fully specified. Please instantiate " + \
                       f"all nets of the bus: {required_nets}." + 
                raise Exception(serr)
        return busses

    @classmethod
    def _validateBus(cls, bus):
        _busValid = True
        for key, data in cls._bus_info.items():
            mandatory = data[1]
            if mandatory and bus[key] is None:
                _busValid = False
        return _busValid

    def getBusDict(self):
        if not self._busValid:
            serr = ["Incomplete bus definition"]
            for key, val in self._bus.items():
                if val is None:
                    serr.append("  Missing: {}".format(key))
            raise Exception("\n".join(serr))
        dd = {}
        for key, val in self._bus.items():
            if val is not None:
                dd[key] = val[0] # Discarding the "source" part
            else:
                dd[key] = None
        return dd

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
        self.initval = 0
        self.strobe = False
        self.write_strobes = []
        self.read_strobes = []

    def copy(self):
        ref = super().copy()
        ref.initval = self.initval
        ref.strobe = self.strobe
        ref.write_strobes = self.write_strobes
        ref.read_strobes = self.read_strobes
        return ref

    def _readRangeDepth(self):
        if self._rangeStr is not None:
            return True
        if self.meta is None:
            return False
        _range = getUnparsedWidthRange(self.meta)
        if _range is not None:
            self.range = _range
        else:
            return False
        return True

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
        _pass = True
        _range, _depth = getUnparsedWidthAndDepthRange(self.meta)
        if _range is not None:
            self.range = _range
        else:
            _pass = False
        if _depth is not None:
            self.depth = _depth
        else:
            _pass = False
        return _pass

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


class ExternalModule():
    def __init__(self, name, ghostbus, extbus):
        print("Next external module: {name}")
        self.name = name
        self.ghostbus = ghostbus
        self.extbus = extbus


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

def doSubcommandLive(args):
    gb = GhostBusser(args.files[0], top=args.top) # Why does this end up as a double-wrapped list?
    mods = gb.get_map()
    bus = gb.getBusDict()
    #try:
    dec = DecoderLB(gb.memory_map, bus, csr_class=MetaRegister, ram_class=MetaMemory)
    #print(dec.GhostbusDecoding())
    dec.GhostbusMagic(dest_dir="_auto")
    #except Exception as e:
    #    print(e)
    #    return 1
    return 0

def doSubcommandMap(args):
    gb = GhostBusser(args.files[0], top=args.top) # Why does this end up as a double-wrapped list?
    mods = gb.get_map()
    bus = gb.getBusDict()
    #try:
    dec = DecoderLB(gb.memory_map, bus, csr_class=MetaRegister, ram_class=MetaMemory)
    dec.ExtraVerilogMemoryMap(args.out_file, bus)
    #except Exception as e:
    #    print(e)
    #    return 1
    return 0

def doGhostbus():
    import argparse
    parser = argparse.ArgumentParser("Ghostbus Verilog router")
    parser.set_defaults(handler=lambda args: 1)
    subparsers = parser.add_subparsers(help="Subcommands")
    parserLive = subparsers.add_parser("live", help="Generate the Ghostbus decoder logic.")
    parserLive.add_argument("files", default=[], action="append", nargs="+", help="Source files.")
    parserLive.add_argument("-t", "--top", default=None, help="Explicitly specify top module for hierarchy.")
    parserLive.set_defaults(handler=doSubcommandLive)
    parserMap = subparsers.add_parser("map", help="Generate a memory map in Verilog form for testing.")
    # TODO - How do I make this less redundant with the "subcommands" usage
    parserMap.add_argument("files", default=[], action="append", nargs="+", help="Source files.")
    parserMap.add_argument("-t", "--top", default=None, help="Explicitly specify top module for hierarchy.")
    parserMap.add_argument("-o", "--out_file", default=None, help="The filepath for Verilog memory map output.")
    parserMap.set_defaults(handler=doSubcommandMap)
    args = parser.parse_args()
    return args.handler(args)

if __name__ == "__main__":
    #testWalkDict()
    exit(doGhostbus())
