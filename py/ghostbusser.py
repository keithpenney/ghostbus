#! python3

# GhostBus top level

import math
import re

from yoparse import VParser, ismodule, get_modname, get_value, \
                    getUnparsedWidthRange, getUnparsedDepthRange, \
                    getUnparsedWidthAndDepthRange, getUnparsedWidth, \
                    YosysParsingError, getUnparsedWidthRangeType, NetTypes
from memory_map import MemoryRegionStager, MemoryRegion, Register, Memory, bits
from gbmemory_map import GBMemoryRegionStager, GBRegister, GBMemory, ExternalModule
from decoder_lb import DecoderLB, BusLB, createPortBus
from gbexception import GhostbusException, GhostbusNameCollision
from util import enum, strDict, print_dict, strip_empty, deep_copy

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
    def __init__(self, name=None):
        self._name = name
        self.val = random.randint(-(1<<31), (1<<31)-1)

    def __str__(self):
        if self._name is not None:
            return self._name
        return f"Unique({self.val})"

    def __repr__(self):
        return self.__str__()

UNASSIGNED  = Unique("UNASSIGNED")

_DEBUG_PRINT=False
def printd(*args, **kwargs):
    if _DEBUG_PRINT:
        print(*args, **kwargs)

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
        "TOP",
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
        "ghostbus_domain":      tokens.BUSNAME,
        # HACK ALERT! I really want to remove this one
        "ghostbus_sub":         tokens.SUB,
        "ghostbus_branch":      tokens.SUB,
        # This one will hopefully be rarely needed.
        # It is to be added to a module instantiation and means "No ghostbusses pass through the top-level ports of this module"
        "ghostbus_top":         tokens.TOP,
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
        tokens.TOP:      lambda x: True,
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
        self.parent_domain = None
        self.memories = []
        self.domain_map = {}
        self.toptag_map = {}
        # Transform whole structure into a MemoryTree
        for key, inst_dict in self._dd.items():
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
        self._module_name = module_name
        self._hierarchy = hierarchy
        #self._mr = GBMemoryRegionStager(label=module_name, hierarchy=hierarchy)
        self._label = None
        if hierarchy is not None:
            self._label = hierarchy[0]
        self._resolved = False
        self._bus_distributed = False

    def get_memory_by_domain(self, domain):
        for memory in self.memories:
            if memory.domain == domain:
                return memory
        return None

    def __str__(self):
        if self._hierarchy is not None:
            label = self._hierarchy[-1]
        elif self._label is not None:
            label = self._label
        else:
            label = "Unknown"
        return "MemoryTree({})".format(label)

    def items(self):
        return self._dd.items()

    def keys(self):
        return self._dd.keys()

    def __repr__(self):
        return self.__str__()

    @property
    def label(self):
        return self._label

    @classmethod
    def _getMemoryOrder(cls, memories, module_name=None):
        """Look for pseudo-bus domains. They need to be resolved first and then attribute their
        resulting address width to their mating extmod.
        So we order the memories to place the pseudo-bus domains first.
        Returns nmems, extmod_map
        where extmod_map = {'extmod_name': index of memory associated with the extmod}
        """
        pseudo_name_map = {} # {index_resolve_before: extmod_name}
        pseudo_index_map = {} # {index_resolve_before: index_resolve_after}
        # resolve_before means it contains the pseudo-bus domain itself
        # resolve_after means it contains the extmod that needs to get its width from the pseudo-bus domain

        # FIRST: find any pseudo-bus domains and keep track of the extmod they need to find
        for nmem in range(len(memories)):
            if memories[nmem].pseudo_domain is not None:
                # Need to find its associated extmod and make sure the extmod's memory is resolved AFTER this one
                pseudo_name_map[nmem] = memories[nmem].pseudo_domain # KEEF
        # If no pseudo-bus domains, resolve the memories in any order
        if len(pseudo_name_map) == 0:
            return [n for n in range(len(memories))], {}
        # SECOND: replace the extmod name with the index of the memory in which the extmod is found
        extmod_map = {}
        for nmem in range(len(memories)):
            print(f"||| {nmem}: {memories[nmem].label}, {memories[nmem].domain}")
            for start, stop, ref in memories[nmem].get_entries():
                print(f" -- {start}, {stop}, {ref}")
                if isinstance(ref, ExternalModule):
                    print(f"    # Found ExternalModule {ref.name}")
                    # Found an extmod.  Is it a value in pseudo_name_map?
                    for key, extmod_name in pseudo_name_map.items():
                        if extmod_name == ref.name:
                            print(f"  extmod_map[{extmod_name}] = {key}, not {nmem}")
                            extmod_map[extmod_name] = key
                            # Found the dependency!
                            pseudo_index_map[key] = nmem
                            del pseudo_name_map[key]
                            break
        if len(pseudo_name_map) > 0:
            unfound = ", ".join([val for val in pseudo_name_map.values()])
            err = f"Could not find the following extmods in module {module_name}: {unfound}\n" + \
                  "These extmod names were referenced by a declared bus in the module."
            raise GhostbusException(err)
        # THIRD: sort the indices
        nmems = cls._orderDependencies(pseudo_index_map)
        # FOURTH: add any remaining indices to the end of the list
        for n in range(len(memories)):
            if n not in nmems:
                nmems.append(n)
        return nmems, extmod_map

    @staticmethod
    def _orderDependencies(depend_dict, debug=False):
        """Each entry in 'depend_dict' needs to be {ref_before, ref_after} where 'ref_before' and
        'ref_after' can be any type but they imply that 'ref_before' needs to come before 'ref_after'
        in the resulting list."""
        # First, don't worry about order, just get all entries in uniquely
        def _p(*args, **kwargs):
            if debug:
                print(*args, **kwargs)
        ordered = []
        for ref_before, ref_after in depend_dict.items():
            if ref_after not in ordered:
                ordered.append(ref_after)
            if ref_before not in ordered:
                ordered.append(ref_before)
        _p(f"    Starting with {ordered}")
        # Then for each entry in the list, make sure it respects all the rules
        npass = 0
        while True:
            moved = False
            for n in range(len(ordered)):
                this = ordered[n]
                # Check for any rules about 'this' being before anything
                after = depend_dict.get(this, None)
                if after is not None:
                    after_index = ordered.index(after)
                    if after_index < n:
                        # Need to move
                        ordered.pop(after_index)
                        ordered.insert(n+1, after)
                        moved = True
                        break
                # Check for any rules about 'this' being before anything
                before = None
                for _before, after in depend_dict.items():
                    if after == this:
                        before = _before
                        break
                if before is not None:
                    before_index = ordered.index(before)
                    if before_index > n:
                        # Need to move
                        ordered.pop(before_index)
                        ordered.insert(n, before)
                        moved = True
                        break
            _p(f"    pass {npass}: {ordered}")
            npass += 1
            if not moved:
                break
        return ordered

    def resolve(self, verbose=False):
        """Walk the hierarchy dict from leaf to trunk, resolving the size in memory of every node
        and nesting MemoryRegion instances to complete the hierarchy.
        This is also where bus domains get resolved.  For a node of the tree, if there exist multiple
        bus domains declared there (len(node.memories) > 1), all CSRs/RAMs declared in such a node
        need to 'pick a team'.  If they are tagged as belonging to an explicit domain, they get assigned
        to that.  Otherwise, they get assigned to the 'default' domain.  If a default domain (None) does
        not exist and some CSRs/RAMs/ExtMods/Ghostbusses lack an explicit domain attribute, it should
        be an error.
        This is also where we associate a pseudo-bus with its extmod.  A pseudo-bus is actually a branch
        of a parent bus tree but the connection between the parent and child is out-of-scope for Ghostbus
        (i.e. its made explicit in Verilog).  The primary use case that comes to mind is clock domain
        crossing.  To do this via Ghostbus, an external bus is conjured like any normal extmod but instead
        of it getting its address space explicitly from its 'addr' port width, it gets just enough space
        assigned to it that is required by its associated pseudo-bus.  This is the logic that needs to
        take place here before fully resolving the memory map.
        """
        def printv(*args, **kwargs):
            if verbose:
                print(*args, **kwargs)
        if not self._resolved:
            for key, node in self.walk():
                if node is None:
                    print(f"WARNING! node is None! key = {key}")
                printv(f" $$$$$$$$ Considering {key}: {node.label}")
                if hasattr(node, "memories"):
                    #if node.memsize > 0:
                    nmems, extmod_map = self._getMemoryOrder(node.memories, module_name=node.label)
                    printv(" *** Parsing in this order:", end="")
                    for nmem in nmems:
                        printv(f" {node.memories[nmem].hierarchy}.{node.memories[nmem].domain},", end="")
                    printv()
                    printv(f" *** {node.label}: len(node.memories) = {len(node.memories)}; len(extmod_map) = {len(extmod_map)}")
                    for n in nmems:
                        printv(f":::{node.memories[n].label}.{node.memories[n].domain}:::")
                        if len(extmod_map) > 0:
                            # Look for extmods
                            for start, stop, ref in node.memories[n].get_entries():
                                printv(f" -- {start}, {stop}, {ref}")
                                if isinstance(ref, ExternalModule):
                                    printv(f"    # Found ExternalModule {ref.name}")
                                    mem_index = extmod_map.get(ref.name, None)
                                    if mem_index is not None:
                                        printv(f"mem_index = {mem_index} Found an associated memory {node.memories[mem_index].label} for extmod {ref.name}")
                                        aw = node.memories[mem_index].aw
                                        printv(f"Setting {ref.name}.aw to {aw} (from {node.memories[mem_index].label}.{node.memories[mem_index].domain})")
                                        ref.aw = aw
                                        # Here I need to give 'ref' a reference to the memory region node.memories[mem_index]
                                        ref.sub_mr = node.memories[mem_index]
                                        del extmod_map[ref.name]
                                    else:
                                        printv(f" *** Can't find mem_index in extmod_map {extmod_map}")
                        if hasattr(node.memories[n], "resolve"):
                            node.memories[n].resolve()
                        node.memories[n].shrink()
                        printv(f"Shrunk {node.memories[n].label}.{node.memories[n].domain} to {node.memories[n].aw} bits")
                        if node._parent is not None:
                            added = False
                            # Here I need to get the inst->domain mapping from the parent, find the correct 'inst'
                            # that matches 'node', then add 'node' to the memory corresponding to the correct 'domain'
                            # Deliberately fail if this is not found in the map; something went wrong earlier
                            parent_domain = node._parent.domain_map[node.label]
                            toptag = node._parent.toptag_map[node.label]
                            for m in range(len(node._parent.memories)):
                                if node._parent.memories[m].domain == parent_domain:
                                    printv("                           Adding {} to {}".format(node.label, node._parent.label))
                                    node._parent.memories[m].add_item(node.memories[n])
                                    added = True
                            if not added:
                                node._parent.memories.append(GBMemoryRegionStager(label=self._module_name,
                                    hierarchy=self._hierarchy, domain=parent_domain))
                                printv("                     Created a new place to add {} anywhere".format(node.label))
                            # Keep track of this
                            node.parent_domain = parent_domain
                        else:
                            toptag = True # If we have no parent, we're top so might as well pretend like toptag was assigned
                            printd(f"                    {node.label} has no _parent")
                        # Add 'toptag' to each module instance listed in toptag_map
                        # For lack of a better structure, I guess we'll add the "toptag" to every domain (every MemoryRegion)
                        for n in range(len(node.memories)):
                            node.memories[n].toptag = toptag
                else:
                    printd(f"       node {node.label} has no memories")
        for mem in self.memories:
            if hasattr(mem, "resolve"):
                mem.resolve()
        return self.memories

    def print(self):
        print("Walking:")
        for key, node in self.walk():
            if node._parent is not None:
                print(f"  {node._parent.label}.{node.label}")
            else:
                print(f"  {node.label}")
        print("Done walking")

    def get_domains(self):
        """For a multi-domain codebase, one or more nodes of the global MemoryTree will have more than
        one 'memory' (a GBMemoryRegionStager instance) in the node. This is a node at which additional
        busses are declared (representing their own domains)."""
        domain_memories = {mem.domain: mem for mem in self.memories}
        for key, node in self.walk():
            if hasattr(node, "memories"):
                if len(node.memories) > 1:
                    print("This node {node.label} has {len(node.memories)} domains.")
                    for mem in node.memories:
                        if mem.domain is not None:
                            if domain_memories.get(mem.domain, None) is not None:
                                err = f"Domain name {mem.domain} is declared in multiple modules " + \
                                       "or multiple instances of a single module.  Separate bus " + \
                                       "domains need to be globally unique."
                                raise GhostbusException(err)
                            domain_memories[mem.domain] = mem
        return domain_memories


class GhostBusser(VParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.memory_map = None
        self._ghostbusses = []
        self.memory_maps = {}
        self._ext_dict = {}

    def digest(self):
        modtree = {}
        top_mod = None
        top_dict = self._dict["modules"]
        handledExtModules = []
        module_info = {}
        for mod_hash, mod_dict in top_dict.items():
            associated_strobes = {}
            module_name = get_modname(mod_hash)
            if not hasattr(mod_dict, "items"):
                raise Exception(f"mod_dict has no 'items' attr: {mod_hash}, {mod_dict}")
                continue
            for attr in mod_dict["attributes"]:
                if attr == "top":
                    top_mod = mod_hash
            # Check for instantiated modules
            modtree[mod_hash] = {}
            module_info[mod_hash] = {"insts": {}}
            cells = mod_dict.get("cells")
            if cells is not None:
                for inst_name, inst_dict in cells.items():
                    if ismodule(inst_name):
                        attr_dict = inst_dict["attributes"]
                        token_dict = GhostbusInterface.decode_attrs(attr_dict)
                        busname = token_dict.get(GhostbusInterface.tokens.BUSNAME, None)
                        toptag  = token_dict.get(GhostbusInterface.tokens.TOP, False)
                        module_info[mod_hash]["insts"][inst_name] = {"busname": busname, "toptag": toptag}
                        modtree[mod_hash][inst_name] = inst_dict["type"]
            mrs = {}
            # Check for regs
            netnames = mod_dict.get("netnames")
            entries = []
            bustop = False
            busnames_explicit = []
            busnames_implicit = []
            busname_to_subname_map = {}
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
                    subname = token_dict.get(GhostbusInterface.tokens.SUB, None)
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
                        reg = GBRegister(name=netname, dw=dw, meta=source, access=access)
                        reg.initval = initval
                        reg.strobe = token_dict.get(GhostbusInterface.tokens.STROBE, False)
                        reg.alias = alias
                        reg.signed = signed
                        reg.busname = busname
                        # print("{} gets initval 0x{:x}".format(netname, initval))
                        if mrs.get(busname, None) is None:
                            mrs[busname] = GBMemoryRegionStager(label=module_name, hierarchy=(module_name,), domain=busname)
                            printd("0: created mr label {} {} ({})".format(busname, mrs[busname].label, mod_hash))
                        if addr is not None:
                            reg.manually_assigned = True
                        # This may not be the best place for this step, but at least it gets done.
                        reg._readRangeDepth()
                        mrs[busname].add(width=0, ref=reg, addr=addr)
                    elif exts is not None:
                        dw = len(net_dict['bits'])
                        if module_name not in handledExtModules:
                            self._handleExt(module_name, netname, exts, dw, source, addr=addr, sub=subname)
                            if mrs.get(busname, None) is not None:
                                printd("1: created mr label {} {} ({})".format(busname, mrs[busname].label, mod_hash))
                                mrs[busname] = GBMemoryRegionStager(label=module_name, hierarchy=(module_name,), domain=busname)
                    ports = token_dict.get(GhostbusInterface.tokens.PORT, None)
                    if subname is not None:
                        busname_to_subname_map[busname] = subname
                    if ports is not None:
                        bustop = True
                        dw = len(net_dict['bits'])
                        # printd(f"     About to _handleBus for {mod_hash}")
                        self._handleBus(netname, ports, dw, source, busname, alias=alias, extmod_name=subname)
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
                    #     printd("{}: Decoded {}: {}".format(netname, GhostbusInterface.tokenstr(token), val))
                    access = token_dict.get(GhostbusInterface.tokens.HA, None)
                    addr = token_dict.get(GhostbusInterface.tokens.ADDR, None)
                    busname = token_dict.get(GhostbusInterface.tokens.BUSNAME, None)
                    if access is not None:
                        source = mem_dict['attributes']['src']
                        dw = int(mem_dict["width"])
                        size = int(mem_dict["size"])
                        aw = math.ceil(math.log2(size))
                        mem = GBMemory(name=memname, dw=dw, aw=aw, meta=source)
                        mem.signed = signed
                        mem.busname = busname
                        if mrs.get(busname, None) is None:
                            module_name = get_modname(mod_hash)
                            mrs[busname] = GBMemoryRegionStager(label=module_name, hierarchy=(module_name,), domain=busname)
                            printd("1: created mr label {} ({})".format(mrs[busname].label, mod_hash))
                        if addr is not None:
                            mem.manually_assigned = True
                        # This may not be the best place for this step, but at least it gets done.
                        mem._readRangeDepth()
                        mrs[busname].add(width=aw, ref=mem, addr=addr)
            for busname, mr in mrs.items():
                for strobe_name, reg_type in associated_strobes.items():
                    associated_reg, _read = reg_type
                    # find the "GBRegister" named 'associated_reg'
                    # Add the strobe as an associated strobe by net name
                    for start, end, register in mr.get_entries():
                        if register.name == associated_reg:
                            if _read:
                                register.read_strobes.append(strobe_name)
                            else:
                                register.write_strobes.append(strobe_name)
                subname = busname_to_subname_map.get(busname, None)
                if subname is not None:
                    mr.pseudo_domain = subname
                mr.bustop = bustop
                # Any ghostmod has an implied ghostbus coming in
                if None not in busnames_implicit:
                    busnames_implicit.append(None)
            module_info[mod_hash]["memory"] = mrs
            module_info[mod_hash]["explicit_busses"] = busnames_explicit
            module_info[mod_hash]["implicit_busses"] = busnames_implicit
            handledExtModules.append(module_name)
        self._busValid = True
        for bus in self._ghostbusses:
            valid, msg = bus.validate()
            if not valid:
                self._busValid = False
        if len(self._ghostbusses) == 0:
            raise GhostbusException("No ghostbus found in codebase.")
        #print_dict(module_info)
        #self._busValid = self._top_bus.validate()
        self._top = top_mod
        self._resolveExt(module_info)
        modtree = self.build_modtree(modtree)
        memtree = self.build_memory_tree(modtree, module_info)
        self.memory_maps = memtree.resolve(verbose=False)
        #for mmap in self.memory_maps:
        #    mmap.shrink()
        #memtree.distribute_busses()
        #self.memory_map.print(4)
        #self.memory_maps = {None: self.memory_map} # DELETEME
        #self.splitMemoryMap() # TODO - Hopefully this step can be eliminated
        ghostmods = {}
        for key, _info in module_info.items():
            mr = _info.get("memory", None)
            if mr is not None:
                ghostmods[key] = mr
        self.ghostmods = ghostmods
        return memtree

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
            if bus.sub is not None:
                print(f"  Skipping {busname} since it's not a top bus")
                continue
            print(f"  Building a map of {bus.name}")
            #   0. Make a copy of the memory map
            mmap = self.memory_map.copy()
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
            #   3. Unstage and re-resolve to ensure memory is tightly packed
            #print(region)
            region.unstage()
            region.resolve()
            region.shrink()
            #   4. Append the copy to self.memory_maps
            memory_maps[busname] = region
        for busname, _map in memory_maps.items():
            print(f"=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+ {busname} +=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=")
            #print(_map)
            _map.print(4)
        self.memory_maps = memory_maps
        return

    def trim_hierarchy(self):
        for mem_map in self.memory_maps:
            mem_map.trim_hierarchy()
        return

    def _handleBus(self, netname, ports, dw, source, busname=None, alias=None, extmod_name=None):
        rangestr = getUnparsedWidthRange(source)
        for port in ports:
            hit = False
            for bus in self._ghostbusses:
                if bus.name == busname:
                    #print(f"&&&&&&&&&&&&&&&&&&& _handleBus: adding {netname} to bus {busname} from source {source}")
                    bus.set_port(port, netname, portwidth=dw, rangestr=rangestr, source=source)
                    hit = True
                    # TODO - How is 'alias' used for a bus? Is it even needed?
                    if alias is not None:
                        if bus.alias is not None:
                            if alias != bus.alias:
                                raise GhostbusException(f"Cannot give multiple aliases to the same bus ({alias} and {bus.alias}).")
                        else:
                            bus.alias = alias
                    if extmod_name is not None:
                        if bus.extmod_name is not None:
                            if extmod_name != bus.extmod_name:
                                raise GhostbusException(f"Cannot give multiple extmod_names to the same bus ({extmod_name} and {bus.extmod_name}).")
                        else:
                            bus.extmod_name = extmod_name
            if not hit:
                #print(f"&&&&&&&&&&&&&&&&&&& _handleBus: New bus {busname}; adding {netname}")
                newbus = BusLB(busname)
                newbus.set_port(port, netname, portwidth=dw, rangestr=rangestr, source=source)
                newbus.alias = alias
                newbus.extmod_name = extmod_name
                self._ghostbusses.append(newbus)
        return

    def _handleExt(self, module, netname, vals, dw, source, addr=None, sub=None):
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
            if 'dout' in portnames or 'wdata' in portnames:
                serr = "The 'dout' vector cannot be shared between multiple instances " + \
                      f"({instnames}). See: {source}"
                raise GhostbusException(serr)
        # print(f"netname = {netname}, dw = {dw}, portnames = {portnames}, instnames = {instnames}")
        self._ext_dict[module].append((netname, dw, portnames, instnames, source, addr, sub))
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

    def findBusByName(self, busname):
        for bus in self._ghostbusses:
            if bus.name == busname:
                return bus
        return None

    def _resolveExt(self, module_info):
        #self._ext_modules = {}
        #ghostbus = self._top_bus
        ghostbus = self.getBusDict()
        special_mod_hash = None # FIXME
        special_busname = None # FIXME
        for module, data in self._ext_dict.items():
            busses = self._resolveExtModule(module, data)
            #self._ext_modules[module] = []
            for instname, bus in busses.items():
                extinst = ExternalModule(instname, ghostbus=ghostbus, extbus=bus)
                print(f"  Resolving ExternalModule {instname}")
                #if bus.sub is not None:
                #    print(f"######################## {extinst.name}. I need to get my 'AW' from a ghostbus named {bus.sub}")
                #    sub_bus = self.findBusByName(bus.sub)
                #    if sub_bus is not None:
                #        print(f"$$$$$$$$$$$$$$$$$ Found the sub_bus {sub_bus.name}")
                #        extinst.sub_bus = sub_bus
                #        extinst.sub_mr = GBMemoryRegionStager(label=sub_bus.name, hierarchy=(sub_bus.name,))
                #    else:
                #        print(f"$$$$$$$$$$$$$$$$$ Failed to find {bus.sub} in {self._ghostbusses}")
                added = False
                for mod_hash, infodict in module_info.items():
                    mrs = infodict.get("memory", None)
                    if len(mrs) == 0:
                        continue
                    for busname, mr in mrs.items():
                        if mr.label == module and mr.domain == extinst.busname:
                            # I need to not just ensure I'm adding to the right module, but also the right domain!
                            mr.add(width=extinst.aw, ref=extinst, addr=extinst.base)
                            special_mod_hash = mod_hash
                            special_busname = busname
                            print(f"  added {extinst.name} to MemoryRegion {mr.label} in domain {mr.domain}")
                            added = True
                            break
                if not added:
                    serr = f"Ext module somehow references a non-existant module {module}?"
                    print(f"module_info.keys() = {[x for x in module_info.keys()]}")
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
                    #print("    New bus")
                    bus = BusLB()
                else:
                    #print("    Got bus")
                    pass
                #print(f"len(data) = {len(data)}")
                for datum in data:
                    #print(f"  datum = {datum}")
                    netname, dw, portnames, instnames, source, addr, sub = datum
                    rangestr = getUnparsedWidthRange(source)
                    if len(instnames) == 0 and universal_inst is not None:
                        instnames.append(universal_inst)
                    if sub is not None and bus.sub is None:
                        bus.sub = sub
                    for net_instname in instnames:
                        if net_instname == instname:
                            for portname in portnames:
                                #print(f"  instname = {instname}, netname = {netname}, portname = {portname}")
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
            valid, msg = bus.validate()
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
                    print(f"WARNING: Unknown module {inst_key}. Treating as black box.")
                else:
                    # Update memory in-place
                    cp = deep_copy(inst)
                    dd[module][dict_key] = cp
        return dd[top]

    def build_memory_tree(self, modtree, module_info):
        """First build a MemoryTree() as a dict of MemoryRegions.
        @params:
            dict modtree:
              Mapping of {(verilog_inst_name, yosys_inst_hash) : some_dict } TODO
            dict module_info:
              Mapping of {yosys_inst_hash : instance_dict}
              where `instance_dict` is:
                { 'insts' : {}, // Module instances instantiated within `yosys_inst_name`
                  'explicit_busses' : [], // Ghostbusses explicitly declared within `yosys_inst_name`
                  'implicit_busses' : [], // Ghostbusses allowed in via macro magic (should only be one) in `yosys_inst_name`
                  'memory': GBMemoryRegionStager
                }
        """
        # Start from leaf,
        # (ExternalModule instance).
        memtree = MemoryTree(modtree, key=(self._top, self._top), hierarchy=(self._top,))
        #print_dict(module_info)
        nodes_visited = 0
        for key, memtree_node in memtree.walk():
            nodes_visited += 1
            if key is None:
                break
            inst_name, inst_hash = key
            instdict = module_info.get(inst_hash, None)
            if instdict is None:
                #print("instdict is None!")
                continue
            module_name = get_modname(inst_hash)
            hier = (inst_name,)
            insts = instdict.get("insts")
            printd(f"{module_name} declares insts: {[key for key in insts.keys()]}")
            memtree_node.domain_map = {inst_name: insts[inst_name]["busname"] for inst_name in insts.keys()}
            memtree_node.toptag_map = {inst_name: insts[inst_name]["toptag"] for inst_name in insts.keys()}
            mrs = instdict.get("memory")
            busses_explicit = instdict.get("explicit_busses", [])
            if len(mrs) > 0:
                #if mr is not None and hasattr(memtree_node, "memory"):
                for busname, mr in mrs.items():
                    #if hasattr(mr, "resolve"):
                    #    if not mr.resolve():
                    #        raise Exception(f"    {mr.name} resists resolving. Care to explain?")
                    mrcopy = mr.copy()
                    mrcopy.label = module_name
                    mrcopy.hierarchy = hier
                    #memtree_node.memory = mrcopy
                    printd(f"                                   {memtree_node.label}.memories.append({mrcopy.label})")
                    memtree_node.memories.append(mrcopy)
                for n in range(len(memtree_node.memories)):
                    # TODO - Should I instead of telling all domains about all busses, distribute each bus only to its domain?
                    memtree_node.memories[n].declared_busses = busses_explicit
                    # I shouldn't need this step below, it should be handled in Ghostbusser.digest()
                    #if len(busses_explicit) > 0:
                    #    memtree_node.memories[n].bustop = True
            else:
                printd(f"no {key} in ghostmods")
                #memtree_node.memory = GBMemoryRegionStager(label=module_name, hierarchy=hier)
                memtree_node.memories.append(GBMemoryRegionStager(label=module_name, hierarchy=hier))
        #print(f"Done building: visited {nodes_visited} nodes")
        return memtree


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
        #top_hierarchy = mem.hierarchy
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
            elif isinstance(ref, ExternalModule) and ref.sub_mr is not None:
                # If this extmod is a gluemod, I need to collect its branch like a submodule
                subdd = cls.memoryRegionToJSONDict(ref.sub_mr, flat=flat, mangle_names=mangle_names, top=False, drops=drops)
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
                    printd(f"{mem.name}: {mem.hierarchy}, {ref.name}: hierarchy = {hierarchy}")
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
            err = f"Memory map key {key} defined more than once." + \
                  f" If {key} is an alias, remember that they are global," + \
                  " so you can't use an alias in a module that gets instantiated more than once." + \
                  f" If {key} is not an alias, ensure it is indeed only declared once per module." + \
                  " If it's only declared once (and thus passes Verilog linting), submit a bug report."
            raise GhostbusNameCollision(err)
    old_dict.update(new_dict)
    return


def handleGhostbus(args):
    try:
        gb = GhostBusser(args.files[0], top=args.top) # Why does this end up as a double-wrapped list?
    except YosysParsingError as err:
        print("ERROR: (Yosys Parsing Error; message follows)")
        print(err)
        return 1
    trim = not args.notrim
    memtree = gb.digest()
    #bus = gb.getBusDict()
    gbusses = gb.getBusDicts()
    gbportbus = createPortBus(gbusses)
    try:
        if args.live or (args.map is not None):
            dec = DecoderLB(memtree, gbusses, gbportbus)
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
            for mem_map in gb.memory_maps:
                busname = None # TODO FIXME
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
