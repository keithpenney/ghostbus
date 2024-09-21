#! python3

# GhostBus top level

import math
import re

from yoparse import VParser, srcParse, ismodule, get_modname, get_value, \
                    getUnparsedWidthRange, getUnparsedDepthRange, \
                    getUnparsedWidthAndDepthRange, getUnparsedWidth, \
                    YosysParsingError, getUnparsedWidthRangeType, NetTypes
from memory_map import MemoryRegionStager, MemoryRegion, Register, Memory, bits
from decoder_lb import DecoderLB, BusLB, vhex
from gbexception import GhostbusException, GhostbusNameCollision
from util import enum, strDict, print_dict, strip_empty

# TODO: Multi-ghostbus hierarchy parsing
#   1. If nbusses > 1:
#       All instantiated modules must be tagged with the "ghostbus_name" attribute.
#       Raise Exception if any are not tagged or if the attribute value does not match
#       any names in 'busnames'
#   2. If nbusses > 1:
#       Tag all instantiated modules with the particular ghostbus that is to be routed
#       into them.
#       This attribute must be inherited throughout the hiearchy
#       2a. The auto-generated hookup code for these modules should reflect the net names
#           of the named bus
#   3. Break off branches of the MemoryTree including the "bustop" level and isolate the
#       bus domains.
#       3a. Also delete any CSRs that don't have the same bus domain.
#   4. Each of these MemoryTree branches should make its own JSON relative to base 0.
#   5. An external tool can combine the JSONs and ensure the resulting memory map reflects
#       the hand-wired combination of the ghostbusses.

# DONE: Permissive CSR access defaults
#   If a detected CSR is of net "wire", assume it's read-only.
#   If a detected CSR is of net "reg", assume it's read/write.

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

import random
# I need a unique value that's not None that's basically impossible to collide
# with anything the user might pass to an attribute. This scheme makes it dang
# near impossible to do accidentally and also quite a pain to do intentionally
class Unique():
    def __init__(self):
        self.val = random.randint(-(1<<31), (1<<31)-1)

UNASSIGNED = Unique()

class GhostbusInterface():
    _tokens = [
        "HA",
        "ADDR",
        "PORT",
        "STROBE",
        "STROBE_W",
        "STROBE_R",
        "EXTERNAL",
        "ALIAS",
        "BUSNAME",
        "SUB",
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
        "ghostbus_alias":       tokens.ALIAS,
        "ghostbus_name":        tokens.BUSNAME,
        # HACK ALERT! I really want to remove this one
        "ghostbus_sub":         tokens.SUB,
    }

    # NOTE! This is only callable via the _val_decoders dict below
    #       Changed from @staticmethod for compatibility with Python <3.10
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
                #access = Register.RW
                access = Register.UNSPECIFIED
            else:
                # Interpret as an access-specifier string
                access = 0
                val = val.strip().lower().replace("/","")
                if 'w' in val:
                    access |= Register.WRITE
                if 'r' in val:
                    access |= Register.READ
        return access

    # NOTE! This is only callable via the _val_decoders dict below
    #       Changed from @staticmethod for compatibility with Python <3.10
    def split_strs(val):
        if hasattr(val, 'split'):
            if ',' in val:
                return [x.strip() for x in val.split(',')]
        return (val,)

    _val_decoders = {
        tokens.HA:       handle_token_ha,
        tokens.ADDR:     lambda x: int(x, 2),
        tokens.PORT:     split_strs,
        tokens.STROBE:   lambda x: True,
        tokens.STROBE_W: lambda x: str(x),
        tokens.STROBE_R: lambda x: str(x),
        tokens.EXTERNAL: split_strs,
        tokens.ALIAS:    lambda x: str(x),
        tokens.BUSNAME:  lambda x: x,
        tokens.SUB:      lambda x: x,
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
        if rvals.get(cls.tokens.ADDR) is not None:
            # Only imply HA if not an ExternalModule
            if rvals.get(cls.tokens.EXTERNAL) is None:
                rvals[cls.tokens.HA] = cls._val_decoders[cls.tokens.HA](1)
        elif rvals.get(cls.tokens.STROBE) is not None:
            # Strobes are write-only
            rvals[cls.tokens.HA] = cls._val_decoders[cls.tokens.HA]("w")
        return rvals


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
        self._mr = GBMemoryRegionStager(label=module_name, hierarchy=hierarchy)
        self._label = None
        if hierarchy is not None:
            self._label = hierarchy[0]
        self._resolved = False
        self._bus_distributed = False

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
                        if hasattr(node.memory, "resolve"):
                            node.memory.resolve()
                        node.memory.shrink()
                        if node._parent is not None:
                            #print("Adding {} to {}".format(node.label, node._parent.label))
                            node._parent.memory.add_item(node.memory)
                    else:
                        #print(f"Node {node.label} has memsize {node.memsize}")
                        pass
                if hasattr(node, "mark"):
                    node.mark()
        if hasattr(self._mr, "resolve"):
            self._mr.resolve()
        return self._mr

    def distribute_busses(self):
        if self._bus_distributed:
            return
        # For any module with declared busses, make sure all instantiated submodules specify their
        # bus domain (if they don't, give them the default).
        for key, node in self.walk():
            if node is None:
                print(f"WARNING! node is None! key = {key}")
            if hasattr(node, "memory"):
                if len(node.memory.declared_busses) > 0:
                    # This MemoryRegion(Stager) has declared busses, so each instantiated
                    # ghostmod needs to have the ghostbus_name
                    print(f"Looking at {node.memory.name}")
                    if hasattr(node.memory, "named_bus_insts"):
                        print(f"  node.memory.named_bus_insts = {node.memory.named_bus_insts}")
                    for (start, end, submod) in node.memory.map:
                        if isinstance(submod, MemoryRegion):
                            submod_name = submod.hierarchy[-1]
                        else:
                            submod_name = submod.name
                        if submod.busname == UNASSIGNED:
                            submod.busname = node.memory.named_bus_insts.get(submod_name, None)
                            if submod.busname is None:
                                print(f"Submodule {submod.name} has no busname; connecting to the default bus.")
                        if submod.busname is not None:
                            print(f"Submodule {submod.name} wants busname {submod.busname}")
                            if submod.busname not in node.memory.declared_busses:
                                err = f"Submodule {submod.name} wants busname {submod.busname}, which is " + \
                                      f"not declared in module {node.memory.name}."
                                raise GhostbusException(err)
                else:
                    # Make sure all busnames are assigned
                    if node.memory.busname == UNASSIGNED:
                        node.memory.busname = None
                    for (start, end, submod) in node.memory.map:
                        submod.busname = None
            else:
                print("node {node} has no memory")
            if hasattr(node, "mark"):
                node.mark()
        # Finally assign default busname to remaining MemoryRegion instances
        for key, node in self.walk():
            if hasattr(node, "memory"):
                if not hasattr(node.memory, "busname"):
                    node.memory.busname = None
            if hasattr(node, "mark"):
                node.mark()
        # For some damn reason the top doesn't show up in the walk?
        if self.memory.busname == UNASSIGNED:
            self.memory.busname = None
        self._bus_distributed = True
        return

    @property
    def memory(self):
        return self._mr

    @memory.setter
    def memory(self, value):
        if not isinstance(value, MemoryRegion):
            raise GhostbusException("MemoryTree can only accept MemoryRegon instances as memory")
        self._mr = value
        return

    @property
    def memsize(self):
        return self._mr.size


class GhostBusser(VParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.memory_map = None
        #self._top_bus = BusLB()
        self._ghostbusses = []
        self.memory_maps = {}
        self._ext_dict = {}

    def get_map(self):
        ghostmods = {}
        modtree = {}
        top_mod = None
        top_dict = self._dict["modules"]
        handledExtModules = []
        # Keep track of where a ghostbus is instantiated
        bustops = {}
        multibus_dict = {}
        for mod_hash, mod_dict in top_dict.items():
            associated_strobes = {}
            module_name = get_modname(mod_hash)
            if not hasattr(mod_dict, "items"):
                continue
            for attr in mod_dict["attributes"]:
                if attr == "top":
                    top_mod = mod_hash
            # Check for instantiated modules
            modtree[mod_hash] = {}
            multibus_dict[mod_hash] = {"insts": {}}
            cells = mod_dict.get("cells")
            if cells is not None:
                for inst_name, inst_dict in cells.items():
                    if ismodule(inst_name):
                        attr_dict = inst_dict["attributes"]
                        token_dict = GhostbusInterface.decode_attrs(attr_dict)
                        busname = token_dict.get(GhostbusInterface.tokens.BUSNAME, None)
                        if busname is not None:
                            print(f"Harumph! Instance {inst_name} in {module_name} hooks up to bus {busname}.")
                            multibus_dict[mod_hash]["insts"][inst_name] = busname
                        modtree[mod_hash][inst_name] = inst_dict["type"]
            mr = None
            # Check for regs
            netnames = mod_dict.get("netnames")
            entries = []
            bustop = False
            busnames_explicit = []
            busnames_implicit = []
            if netnames is not None:
                for netname, net_dict in netnames.items():
                    attr_dict = net_dict["attributes"]
                    token_dict = GhostbusInterface.decode_attrs(attr_dict)
                    # for token, val in token_dict.items():
                    #     print("{}: Decoded {}: {}".format(netname, GhostbusInterface.tokenstr(token), val))
                    source = attr_dict.get('src', None)
                    signed = net_dict.get("signed", None)
                    hit = False
                    access = token_dict.get(GhostbusInterface.tokens.HA, None)
                    addr = token_dict.get(GhostbusInterface.tokens.ADDR, None)
                    write_strobe = token_dict.get(GhostbusInterface.tokens.STROBE_W, None)
                    read_strobe = token_dict.get(GhostbusInterface.tokens.STROBE_R, None)
                    exts = token_dict.get(GhostbusInterface.tokens.EXTERNAL, None)
                    alias = token_dict.get(GhostbusInterface.tokens.ALIAS, None)
                    busname = token_dict.get(GhostbusInterface.tokens.BUSNAME, None)
                    if write_strobe is not None:
                        # print("                            write_strobe: {} => {}".format(netname, write_strobe))
                        # Add this to the to-do list to associate when the module is done parsing
                        associated_strobes[netname] = (write_strobe, False)
                    elif read_strobe is not None:
                        # print("                            read_strobe: {} => {}".format(netname, read_strobe))
                        associated_strobes[netname] = (read_strobe, True)
                    elif access is not None:
                        dw = len(net_dict['bits'])
                        initval = get_value(net_dict['bits'])
                        reg = MetaRegister(name=netname, dw=dw, meta=source, access=access)
                        reg.initval = initval
                        reg.strobe = token_dict.get(GhostbusInterface.tokens.STROBE, False)
                        reg.alias = alias
                        reg.signed = signed
                        reg.busname = busname
                        # print("{} gets initval 0x{:x}".format(netname, initval))
                        if mr is None:
                            mr = GBMemoryRegionStager(label=module_name, hierarchy=(module_name,))
                            # print("created mr label {}".format(mr.label))
                        if addr is not None:
                            reg.manually_assigned = True
                        # This may not be the best place for this step, but at least it gets done.
                        reg._readRangeDepth()
                        mr.add(width=0, ref=reg, addr=addr)
                    elif exts is not None:
                        dw = len(net_dict['bits'])
                        if module_name not in handledExtModules:
                            self._handleExt(module_name, netname, exts, dw, source, addr=addr)
                    ports = token_dict.get(GhostbusInterface.tokens.PORT, None)
                    subname = token_dict.get(GhostbusInterface.tokens.SUB, None)
                    if subname is not None:
                        print(f"  stepchild: {netname} subname = {subname}")
                    if ports is not None:
                        bustop = True
                        dw = len(net_dict['bits'])
                        # print(f"     About to _handleBus for {mod_hash}")
                        self._handleBus(netname, ports, dw, source, busname)
                        if busname not in busnames_explicit:
                            busnames_explicit.append(busname)
            # Check for RAMs
            memories = mod_dict.get("memories")
            if memories is not None:
                for memname, mem_dict in memories.items():
                    attr_dict = mem_dict["attributes"]
                    signed = net_dict.get("signed", None)
                    token_dict = GhostbusInterface.decode_attrs(attr_dict)
                    # for token, val in token_dict.items():
                    #     print("{}: Decoded {}: {}".format(netname, GhostbusInterface.tokenstr(token), val))
                    access = token_dict.get(GhostbusInterface.tokens.HA, None)
                    addr = token_dict.get(GhostbusInterface.tokens.ADDR, None)
                    busname = token_dict.get(GhostbusInterface.tokens.BUSNAME, None)
                    if access is not None:
                        source = mem_dict['attributes']['src']
                        dw = int(mem_dict["width"])
                        size = int(mem_dict["size"])
                        aw = math.ceil(math.log2(size))
                        mem = MetaMemory(name=memname, dw=dw, aw=aw, meta=source)
                        mem.signed = signed
                        mem.busname = busname
                        if mr is None:
                            module_name = get_modname(mod_hash)
                            mr = GBMemoryRegionStager(label=module_name, hierarchy=(module_name,))
                            print("created mr label {}".format(mr.label))
                        if addr is not None:
                            mem.manually_assigned = True
                        # This may not be the best place for this step, but at least it gets done.
                        mem._readRangeDepth()
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
                mr.bustop = bustop
                ghostmods[mod_hash] = mr
                # Any ghostmod has an implied ghostbus coming in
                if None not in busnames_implicit:
                    busnames_implicit.append(None)
            multibus_dict[mod_hash]["explicit_busses"] = busnames_explicit
            multibus_dict[mod_hash]["implicit_busses"] = busnames_implicit
            if bustop:
                # There are two cases where we could have a multi-bus module:
                #   Case 0: Two or more busses are declared in the same module
                #   Case 1: A single bus is declared inside a ghostmod (the ghostbus coming into the
                #           ghostmod is the other bus).
                bustops[module_name] = True
                nbusses = len(busnames_implicit) + len(busnames_explicit)
                plural = ""
                if nbusses > 1:
                    plural = "s"
                print(f"^^^^^^^^^^^^^^^^^^^^^ Module {module_name} contains {nbusses} bus instantiation{plural}!")
            handledExtModules.append(module_name)
        self._busValid = True
        for bus in self._ghostbusses:
            valid = bus.validate()
            if not valid:
                self._busValid = False
        #print_dict(multibus_dict)
        #self._busValid = self._top_bus.validate()
        self._top = top_mod
        self._resolveExt(ghostmods)
        #print_dict(modtree)
        modtree = self.build_modtree(modtree)
        #print("===============================================")
        #print_dict(modtree)
        memtree = self.build_memory_tree(modtree, ghostmods, multibus_dict)
        #print("***********************************************")
        self.memory_map = memtree.resolve()
        self.check_memory_tree(memtree)
        memtree.distribute_busses()
        self.memory_map.shrink()
        self.memory_map.print(4)
        self.memory_maps = {None: self.memory_map} # DELETEME
        self.splitMemoryMap()
        return ghostmods

    @classmethod
    def getMultiBusRegion(cls, memregion, busname=None):
        if busname in memregion.declared_busses:
            return memregion
        for start, stop, ref in memregion.get_entries():
            if isinstance(ref, MemoryRegion):
                if busname in ref.declared_busses:
                    return ref
                else:
                    newref = cls.getMultiBusRegion(ref, busname)
                    if newref is not None:
                        return newref
        return None

    def splitMemoryMap(self):
        # Start with empty self.memory_maps
        memory_maps = {}
        # For each bus domain in the global list:
        for bus in self._ghostbusses:
            busname = bus.name
            print(f"  Building a map of {bus.name}")
            #   0. Make a copy of the memory map
            mmap = self.memory_map.copy()
            # HACK ALERT! I added application-specific attributes, but the copy is incomplete
            # TODO - Just subclass MemoryRegion already and add the damn app-specific attrs
            #mmap.declared_busses = self.memory_map.declared_busses
            #mmap.implicit_busses = self.memory_map.implicit_busses
            #mmap.named_bus_insts = self.memory_map.named_bus_insts
            #   1. Find the MemoryRegion where the bus is declared
            region = self.getMultiBusRegion(mmap, busname)
            if region is None:
                print(f"  Can't find where {busname} is declared")
                continue
            else:
                print(f"  {busname} is declared at {region.name}")
            #   2. For every instance declared in this region:
            delete_addrs = []
            for (start, stop, ref) in region.map:
                # If inst.busdomain != target_busdomain:
                if hasattr(ref, 'busname') and ref.busname != busname:
                    # delete the branch
                    print(f"    I'm gonna chop off this {ref.busname} branch starting at {ref.name}!")
                    delete_addrs.append(start)
                elif not hasattr(ref, 'busname') and isinstance(ref, MemoryRegion):
                    print(f"    Why {ref.name} has no busname?")
                else:
                    print(f"    I guess {ref.name} stays?")
            for addr in delete_addrs:
                region.remove(addr)
            #   3. Append the copy to self.memory_maps
            region.shrink()
            memory_maps[busname] = region
        for busname, _map in memory_maps.items():
            print(f"=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+ {busname} +=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=")
            #print(_map)
            _map.print(4)
        self.memory_maps = memory_maps
        return

    def trim_hierarchy(self):
        for busname, mem_map in self.memory_maps.items():
            mem_map.trim_hierarchy()
        return

    def _handleBus(self, netname, vals, dw, source, busname=None):
        rangestr = getUnparsedWidthRange(source)
        for val in vals:
            hit = False
            for bus in self._ghostbusses:
                if bus.name == busname:
                    print(f"&&&&&&&&&&&&&&&&&&& _handleBus: adding {netname} to bus {busname} from source {source}")
                    bus.set_port(val, netname, portwidth=dw, rangestr=rangestr, source=source)
                    hit = True
            if not hit:
                print(f"&&&&&&&&&&&&&&&&&&& _handleBus: New bus {busname}; adding {netname}")
                newbus = BusLB(busname)
                newbus.set_port(val, netname, portwidth=dw, rangestr=rangestr, source=source)
                self._ghostbusses.append(newbus)
        return

    def _handleExt(self, module, netname, vals, dw, source, addr=None):
        if self._ext_dict.get(module, None) is None:
            self._ext_dict[module] = []
        portnames = []
        instnames = []
        allowed_ports = BusLB._alias_keys
        if len(vals) > 1:
            for val in vals:
                if BusLB.allowed_portname(val):
                    portnames.append(val)
                else:
                    if val not in instnames:
                        instnames.append(val)
        else:
            val = vals[0]
            if BusLB.allowed_portname(val):
                # It's a port name
                portnames.append(val)
            else:
                # Assume it's an inst name
                if val not in instnames:
                    instnames.append(val)
        if len(instnames) > 1:
            if 'dout' in portnames:
                serr = "The 'dout' vector cannot be shared between multiple instances " + \
                      f"({instnames}). See: {source}"
                raise GhostbusException(serr)
        # print(f"netname = {netname}, dw = {dw}, portnames = {portnames}, instnames = {instnames}")
        self._ext_dict[module].append((netname, dw, portnames, instnames, source, addr))
        return

    def _getRefByAttr(self, name, attr):
        for start, stop, ref in self.memory_map.get_entries():
            if hasattr(ref, attr):
                item = getattr(ref, attr)
                if name == getattr(ref, attr):
                    return ref
        return None

    def _getRefByName(self, name):
        return self._getRefByAttr(name, 'name')

    def _getRefByLabel(self, label):
        return self._getRefByAttr(label, 'label')

    def _resolveExt(self, ghostmods):
        #self._ext_modules = {}
        #ghostbus = self._top_bus
        ghostbus = self.getBusDict()
        for module, data in self._ext_dict.items():
            busses = self._resolveExtModule(module, data)
            #self._ext_modules[module] = []
            for instname, bus in busses.items():
                print(bus.name)
                print(bus)
                extinst = ExternalModule(instname, ghostbus=ghostbus, extbus=bus)
                added = False
                for mod_hash, mr in ghostmods.items():
                    if mr.label == module:
                        mr.add(width=bus['aw'], ref=extinst, addr=extinst.base)
                        added = True
                if not added:
                    serr = f"Ext module somehow references a non-existant module {module}?"
                    raise GhostbusException(serr)
        return

    def _resolveExtModule(self, module, data):
        ext_advice = "If there's only a " + \
                    "single external instance in this module, you must label at " + \
                    "least one net with the instance name, e.g.:\n" + \
                    '  (* ghostbus_ext="inst_name, clk" *) wire ext_clk;\n' + \
                    "If there is more than one external instance in this module, " + \
                    "you need to include the instance in the attribute value for " + \
                    "each net in the bus (e.g. 'clk', 'addr', 'din', 'dout', 'we')."
        module_instnames = []
        for datum in data:
            #netname, dw, portnames, instnames, source, addr = datum
            instnames = datum[3]
            for instname in instnames:
                if instname not in module_instnames:
                    module_instnames.append(instname)
        inst_err = False
        busses = {}
        universal_inst = None
        if len(module_instnames) == 1:
            universal_inst = module_instnames[0]
        if len(module_instnames) == 0:
            inst_err = True
        else:
            # print(f"len(module_instnames) = {len(module_instnames)}")
            for instname in module_instnames:
                # print(f"instname = {instname}")
                bus = busses.get(instname, None)
                if bus is None:
                    print("    New bus")
                    bus = BusLB()
                else:
                    print("    Got bus")
                    pass
                print(f"len(data) = {len(data)}")
                for datum in data:
                    print(f"  datum = {datum}")
                    netname, dw, portnames, instnames, source, addr = datum
                    rangestr = getUnparsedWidthRange(source)
                    if len(instnames) == 0 and universal_inst is not None:
                        instnames.append(universal_inst)
                    for net_instname in instnames:
                        if net_instname == instname:
                            for portname in portnames:
                                print(f"  instname = {instname}, netname = {netname}, portname = {portname}")
                                bus.set_port(portname, netname, portwidth=dw, rangestr=rangestr, source=source)
                            if addr is not None:
                                # print(f"addr is not None: datum = {datum}")
                                errst = None
                                try:
                                    bus.base = addr
                                except GhostbusException as err:
                                    errst = str(err)
                                if errst != None:
                                    raise GhostbusException(f"{instnames}: {errst}")
                busses[instname] = bus
        if inst_err:
            serr = "No instance referenced for external bus." + ext_advice
            raise GhostbusException(serr)
        for instname, bus in busses.items():
            valid = bus.validate()
            busses[instname] = bus
            #print_dict(busses[instname])
        return busses

    def getBusDict(self, busname=None):
        if len(self._ghostbusses) == 1:
            return self._ghostbusses[0]
        for bus in self._ghostbusses:
            if bus.name == busname:
                return bus
        return None

    def getBusDicts(self):
        return self._ghostbusses

    def build_modtree(self, dd):
        top = self._top
        if top is None:
            raise GhostbusException("I don't know how to do this without top specified")
        modtree = {}
        for module, mod_dict in dd.items():
            if module == top:
                modtree[module] = {}
        if len(modtree) == 0:
            raise GhostbusException("Could not find top: {}".format(top))
        nested = False
        dd_keys = [key for key in dd.keys()]
        for module in dd_keys:
            instances_dict = dd[module]
            # print(f"               Processing: {module}")
            instance_keys = [key for key in instances_dict.keys()]
            for inst_name in instance_keys:
                inst_key = instances_dict[inst_name]
                dict_key = (inst_name, inst_key)
                # print(f"                   Instance key: {dict_key}")
                inst = dd.get(inst_key, None)
                del instances_dict[inst_name]
                if inst is None:
                    print(f"Is this a Xilinx primitive? {inst_key}")
                else:
                    # Update memory in-place
                    dd[module][dict_key] = inst
        return dd[top]

    def build_memory_tree(self, modtree, ghostmods, multibus_dict={}):
        # First build an empty dict of MemoryRegions
        # Start from leaf,
        #print("++++++++++++++++++++++++++++++++++++++++++++")
        memtree = MemoryTree(modtree, key=(self._top, self._top), hierarchy=(self._top,))
        #print("////////////////////////////////////////////")
        #print_dict(multibus_dict)
        for key, val in memtree.walk():
            #print("{}: {}".format(key, val))
            if key is None:
                break
            inst_name, inst_hash = key
            module_name = get_modname(inst_hash)
            mr = ghostmods.get(inst_hash, None)
            hier = (inst_name,)
            if mr is not None and hasattr(val, "memory"):
                if hasattr(mr, "resolve"):
                    mr.resolve()
                mrcopy = mr.copy()
                mrcopy.label = module_name
                mrcopy.hierarchy = hier
                val.memory = mrcopy
            else:
                #print(f"no {key} in ghostmods")
                val.memory = GBMemoryRegion(label=module_name, hierarchy=hier)
            _busdict = multibus_dict.get(inst_hash, None)
            print(f"  Handling {inst_hash}")
            if _busdict is not None:
                busses_implicit = _busdict.get("implicit_busses", [])
                busses_explicit = _busdict.get("explicit_busses", [])
                insts = _busdict.get("insts", {})
                del multibus_dict[inst_hash]
            else:
                busses_implicit = ()
                busses_explicit = ()
                insts = ()
            val.memory.declared_busses = busses_explicit
            val.memory.implicit_busses = busses_implicit
            val.memory.named_bus_insts = insts
            if len(val.memory.declared_busses) > 0:
                val.memory.bustop = True
        print(f"  #### Remaining multibus_dict: {multibus_dict}")
        return memtree

    def check_memory_tree(self, memtree):
        for key, val in memtree.walk():
            if key is None:
                break
            if hasattr(val, "memory"):
                if not hasattr(val.memory, "declared_busses"):
                    print(f"@@@ {val.memory.name} has no declared_busses")
            else:
                print(f"### val {val} has no memory!")
        return


class MetaRegister(Register):
    """This class expands on the Register class by including not just its
    resolved aw/dw, but also the unresolved strings used to declare aw/dw
    in the source code."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #self._rangeStr = None
        #self._depthstr = None
        self.range = (None, None)
        self.depth = ('0', '0')
        self.initval = 0
        self.strobe = False
        self.write_strobes = []
        self.read_strobes = []
        self.alias = None
        self.signed = None
        self.manually_assigned = False
        self.net_type = None
        self.busname = UNASSIGNED

    def copy(self):
        ref = super().copy()
        ref.range = self.range
        ref.depth = self.depth
        ref.initval = self.initval
        ref.strobe = self.strobe
        ref.write_strobes = self.write_strobes
        ref.read_strobes = self.read_strobes
        ref.alias = self.alias
        ref.signed = self.signed
        ref.manually_assigned = self.manually_assigned
        ref.net_type = self.net_type
        ref.busname = self.busname
        if ref.access == ref.UNSPECIFIED:
            raise Exception(f"copy of {self.name} with access {self.access} results in UNSPECIFIED ref!")
        return ref

    def _readRangeDepth(self):
        #if self._rangeStr is not None:
        #    return True
        if self.meta is None:
            return False
        _range, _net_type = getUnparsedWidthRangeType(self.meta) # getUnparsedWidthRange(self.meta)
        if _range is not None:
            print(f"))))))))))))))))))))))) {self.name} self.range = {_range}")
            self.range = _range
            self.net_type = _net_type
            # Apply default access assumptions
            if self.access == self.UNSPECIFIED and _net_type is not None:
                if _net_type == NetTypes.reg:
                    self.access = self.RW
                elif _net_type == NetTypes.wire:
                    self.access = self.READ
            elif (self.access & self.WRITE):
                if _net_type == NetTypes.wire:
                    err = f"Cannot have write access to net {self.name} of 'wire' type." + \
                          f" See: {self.meta}"
                    raise GhostbusException(err)
            elif self.access == self.UNSPECIFIED:
                # Can't leave the access unspecified
                self.access = self.RW
                raise Exception(f"Can't leave the access unspecified: {self.name}")
        else:
            raise Exception(f"Couldn't find _range of {self.name}")
            return False
        return True


# TODO - Combine this class with MetaRegister
class MetaMemory(Memory):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #self._rangeStr = None
        self._depthStr = None
        self.range = (None, None)
        self.depth = (None, None)
        self.alias = None
        self.signed = None
        self.manually_assigned = False
        self.busname = UNASSIGNED
        # TODO - Is there any reason why this wouldn't be so? Maybe ROM?
        self.access = self.RW

    def _readRangeDepth(self):
        #if self._rangeStr is not None:
        #    return True
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

    def copy(self):
        ref = super().copy()
        ref.range = self.range
        ref.depth = self.depth
        ref.alias = self.alias
        ref.signed = self.signed
        ref.manually_assigned = self.manually_assigned
        ref.busname = self.busname
        ref.access = self.access
        return ref


class GBMemoryRegion(MemoryRegion):
    def __init__(self, addr_range=(0, (1<<24)), label=None, hierarchy=None):
        super().__init__(addr_range=addr_range, label=label, hierarchy=hierarchy)
        self.bustop = False
        self.declared_busses = ()
        self.implicit_busses = ()
        self.named_bus_insts = ()
        self.busname = UNASSIGNED

    def copy(self):
        cp = super().copy()
        cp.bustop = self.bustop
        cp.declared_busses = self.declared_busses
        cp.implicit_busses = self.implicit_busses
        cp.named_bus_insts = self.named_bus_insts
        cp.busname = self.busname
        return cp


class GBMemoryRegionStager(MemoryRegionStager):
    def __init__(self, addr_range=(0, (1<<24)), label=None, hierarchy=None):
        super().__init__(addr_range=addr_range, label=label, hierarchy=hierarchy)
        self.bustop = False
        self.declared_busses = ()
        self.implicit_busses = ()
        self.named_bus_insts = ()
        self.busname = UNASSIGNED

    def copy(self):
        cp = super().copy()
        cp.bustop = self.bustop
        cp.declared_busses = self.declared_busses
        cp.implicit_busses = self.implicit_busses
        cp.named_bus_insts = self.named_bus_insts
        cp.busname = self.busname
        return cp


class ExternalModule():
    def __init__(self, name, ghostbus, extbus):
        size = 1<<extbus.aw
        if extbus.aw > ghostbus.aw:
            serr = f"{name} external bus has greater address width {extbus['aw']}" + \
                   f" than the ghostbus {ghostbus['aw']}"
            raise GhostbusException(serr)
        if extbus.dw > ghostbus.dw:
            serr = f"{name} external bus has greater data width {extbus['dw']}" + \
                   f" than the ghostbus {ghostbus['dw']}"
            raise GhostbusException(serr)
        self.signed = None
        self.name = name
        self.inst = name # alias
        self.ghostbus = ghostbus
        self.extbus = extbus
        self.access = self.extbus.access
        self.busname = UNASSIGNED
        self.manually_assigned = False
        if self.base is None:
            print(f"New external module: {name}; size = 0x{size:x}")
        else:
            self.manually_assigned = True
            print(f"New external module: {name}; size = 0x{size:x}; base = 0x{self.base:x}")

    def getDoutPort(self):
        return self.extbus['dout']

    def getDinPort(self):
        return self.extbus['din']

    @property
    def dw(self):
        return self.extbus.dw

    @property
    def aw(self):
        return self.extbus.aw

    @property
    def base(self):
        return self.extbus.base

    @base.setter
    def base(self, ignore_val):
        # Ignoring this. Can only set via the bus
        # Need a setter here for reasons...
        return


class JSONMaker():
    # TODO - I need to make one JSON for every ghostbus in the design, which will each
    #        specify the regmap of its own tree relative to its own base (0)
    #        Then a separate tool can merge the JSONs into a complete memory map. This
    #        is outside the scope of this tool because it is not aware of how the
    #        individual ghostbusses are assigned (paged) globally
    def __init__(self, memtree, drops=()):
        self.memtree = memtree
        self._drops = drops

    @classmethod
    def memoryRegionToJSONDict(cls, mem, flat=True, mangle_names=False, top=True, drops=()):
        """ Returns a dict ready for JSON-ification using our preferred memory map style:
        // Example
        {
            "regname": {
                "access": "rw",
                "addr_width": 0,
                "sign": "unsigned",
                "base_addr": 327681,
                "data_width": 1,
                "global": false
            },
        }
        """
        dd = {}
        entries = mem.get_entries()
        if top:
            # Note! Discarding top-level name in hierarcy
            top_hierarchy = []
        else:
            top_hierarchy = mem.hierarchy[1:]
        # Returns a list of entries. Each entry is (start, end+1, ref) where 'ref' is applications-specific
        for start, stop, ref in entries:
            if isinstance(ref, MemoryRegion):
                subdd = cls.memoryRegionToJSONDict(ref, flat=flat, mangle_names=mangle_names, top=False, drops=drops)
                if flat:
                    update_without_collision(dd, subdd)
                else:
                    dd[ref.name] = subdd
            elif isinstance(ref, Register) or isinstance(ref, ExternalModule):
                if ref.signed is not None and ref.signed:
                    signstr = "signed"
                else:
                    signstr = "unsigned"
                entry = {
                    "access": Register.accessToStr(ref.access),
                    "addr_width": ref.aw,
                    "sign": signstr,
                    "base_addr": mem.base + start,
                    "data_width": ref.dw,
                }
                if hasattr(ref, "alias") and (ref.alias is not None) and (len(str(ref.alias)) != 0):
                    hier_str = str(ref.alias)
                elif flat:
                    hierarchy = list(top_hierarchy)
                    hierarchy.append(ref.name)
                    if mangle_names:
                        hier_str = "_".join(strip_empty(hierarchy))
                    else:
                        hier_str = ".".join(strip_empty(hierarchy))
                else:
                    hier_str = ref.name
                if hier_str not in drops:
                    dd[hier_str] = entry
            else:
                print(f"What is this? {ref}")
        return dd


    def write(self, filename, path="_auto", flat=False, mangle=False):
        import os
        import json
        if path is not None:
            filepath = os.path.join(path, filename)
        else:
            filepath = filename
        ss = json.dumps(self.memoryRegionToJSONDict(self.memtree, flat=flat, mangle_names=mangle, drops=self._drops), indent=2)
        with open(filepath, 'w') as fd:
            fd.write(ss)
        return


def update_without_collision(old_dict, new_dict):
    """Calls old_dict.update(new_dict) after ensuring there are no identical keys in both dicts."""
    for key in new_dict.keys():
        if key in old_dict:
            raise GhostbusNameCollision("Memory map key {} defined more than once.".format(key))
    old_dict.update(new_dict)
    return


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

def handleGhostbus(args):
    try:
        gb = GhostBusser(args.files[0], top=args.top) # Why does this end up as a double-wrapped list?
    except YosysParsingError as err:
        print("ERROR: (Yosys Parsing Error; message follows)")
        print(err)
        return 1
    trim = not args.notrim
    mods = gb.get_map()
    #bus = gb.getBusDict()
    gbusses = gb.getBusDicts()
    try:
        if args.live or (args.map is not None):
            dec = DecoderLB(gb.memory_map, gbusses, csr_class=MetaRegister, ram_class=MetaMemory, ext_class=ExternalModule)
            if args.live:
                dec.GhostbusMagic(dest_dir=args.dest)
            if args.map is not None:
                dec.ExtraVerilogMemoryMap(args.map, gbusses)
        if args.json is not None:
            # JSON
            if trim:
                gb.trim_hierarchy()
            single_bus = True
            if len(gb.memory_maps) > 1:
                single_bus = False
            for busname, mem_map in gb.memory_maps.items():
                jm = JSONMaker(mem_map, drops=args.ignore)
                if busname is None or single_bus:
                    filename = str(args.json)
                else:
                    import os
                    fname, ext = os.path.splitext(args.json)
                    filename = fname + f".{busname}" + ext
                jm.write(filename, path=args.dest, flat=args.flat, mangle=args.mangle)
    except GhostbusException as e:
        print(e)
        return 1
    return 0

def doGhostbus():
    import argparse
    parser = argparse.ArgumentParser("Ghostbus Verilog bus generator")
    #parser.set_defaults(handler=lambda args: 1)
    parser.add_argument("--live",   default=False, action="store_true", help="Generate the Ghostbus decoder logic (.vh) files.")
    parser.add_argument("-t", "--top", default=None, help="Explicitly specify top module for hierarchy.")
    parser.add_argument("--dest",   default="_autogen", help="Directory name for auto-generated files.")
    parser.add_argument("--map",    default=None, help="[experimental] Filename for a generated memory map in Verilog form for testing.")
    parser.add_argument("--json",   default=None, help="Filename for a generated memory map as a JSON file.")
    parser.add_argument("--flat",   default=False, action="store_true", help="Yield a flat JSON, rather than hierarchical.")
    parser.add_argument("--notrim", default=False, action="store_true", help="Disable trimming common root from register hierarchy.")
    parser.add_argument("--mangle", default=False, action="store_true", help="Names are hierarchically qualified and joined by '_'.")
    parser.add_argument("--ignore", default=[], action="append", help="Register names to drop from the JSON.")
    parser.add_argument("files",    default=[], action="append", nargs="+", help="Source files.")
    args = parser.parse_args()
    return handleGhostbus(args)


if __name__ == "__main__":
    #testWalkDict()
    exit(doGhostbus())
