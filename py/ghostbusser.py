#! python3

# GhostBus top level

import math
import re

from yoparse import VParser, ismodule, get_modname, get_value, \
                    getUnparsedWidthRange, getUnparsedDepthRange, \
                    getUnparsedWidthAndDepthRange, getUnparsedWidth, \
                    YosysParsingError, getUnparsedWidthRangeType, NetTypes, \
                    block_inst, autogenblk, findForLoop
from memory_map import MemoryRegionStager, MemoryRegion, Register, Memory, bits
from gbmemory_map import GBMemoryRegionStager, GBRegister, GBMemory, ExternalModule, GenerateFor, GenerateIf
from decoder_lb import DecoderLB, BusLB, createPortBus
from gbexception import GhostbusException, GhostbusNameCollision
from util import enum, strDict, print_dict, strip_empty, deep_copy, check_complete_indices, feature_print

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
                if access == 0:
                    access = Register.UNSPECIFIED
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
                rvals[cls.tokens.HA] = Register.UNSPECIFIED
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
        # This is a map of instances within generate branches.  This should be distributed to child nodes.
        # What changes if an instance is instantiated within a generate block? The hookup auto-generated code.
        # So every node needs to know which instances are instantiated within a generate block
        self.genblock_map = {}
        # Because of the weirdness of recursive structures, each node will also keep track of whether it's
        # instantiated within a generate branch as well
        self.genblock = None
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
        verbose = False
        def printv(*args, **kwargs):
            if verbose:
                print(*args, **kwargs)

        pseudo_name_map = {} # {index_resolve_before: extmod_name}
        pseudo_index_map = {} # {index_resolve_before: index_resolve_after}
        # resolve_before means it contains the pseudo-bus domain itself
        # resolve_after means it contains the extmod that needs to get its width from the pseudo-bus domain

        # FIRST: find any pseudo-bus domains and keep track of the extmod they need to find
        for nmem in range(len(memories)):
            if memories[nmem].pseudo_domain is not None:
                # Need to find its associated extmod and make sure the extmod's memory is resolved AFTER this one
                pseudo_name_map[nmem] = memories[nmem].pseudo_domain
        # If no pseudo-bus domains, resolve the memories in any order
        if len(pseudo_name_map) == 0:
            return [n for n in range(len(memories))], {}
        # SECOND: replace the extmod name with the index of the memory in which the extmod is found
        extmod_map = {}
        for nmem in range(len(memories)):
            printv(f"||| {nmem}: {memories[nmem].label}, {memories[nmem].domain}")
            for start, stop, ref in memories[nmem].get_entries():
                printv(f" -- {start}, {stop}, {ref}")
                if isinstance(ref, ExternalModule):
                    printv(f"    # Found ExternalModule {ref.name}")
                    # Found an extmod.  Is it a value in pseudo_name_map?
                    for key, extmod_name in pseudo_name_map.items():
                        if extmod_name == ref.name:
                            printv(f"  extmod_map[{extmod_name}] = {key}, not {nmem}")
                            extmod_map[extmod_name] = key
                            # Found the dependency!
                            pseudo_index_map[key] = nmem
                            del pseudo_name_map[key]
                            break
        if len(pseudo_name_map) > 0:
            unfound = ", ".join([val for val in pseudo_name_map.values()])
            err = f"Could not find the following extmods in module {module_name}: {unfound}\n" + \
                  "These extmod names were referenced by a declared bus in the module."
            # MISSING_EXTMOD
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
        verbose = False
        def printv(*args, **kwargs):
            if verbose:
                print(*args, **kwargs)
        top_memories = []
        stepchildren = [] # (parent extmod, child bus)
        if not self._resolved:
            for key, node in self.walk():
                if node is None:
                    printd(f"WARNING! node is None! key = {key}")
                    continue
                printv(f" $$$$$$$$ Considering {key}: {node.label}")
                if node._parent is None:
                    toptag = True
                    genblock = None
                else:
                    toptag = node._parent.toptag_map[node.label]
                    genblock = node._parent.genblock_map[node.label]
                node.genblock = genblock
                if hasattr(node, "memories"):
                    # =========================================================
                    # At this point, a module with a declared bus but no implied bus will have
                    # a MemoryRegion object incorrectly associated with domain 'None'.
                    # This MemoryRegion should be found and have its domain updated accordingly.
                    # =========================================================
                    if toptag:
                        ldb = len(node.declared_busses)
                        if ldb == 1:
                            printv(f"Clobbering {node.memories[0].label}.domain from {node.memories[0].domain} to {node.declared_busses[0]}")
                            node.memories[0].domain = node.declared_busses[0]
                        elif ldb > 1:
                            for mem in node.memories:
                                if mem.domain is None and mem.size > 0:
                                    err = f"Module {node.label} declares {ldb} busses and has no implied busses." \
                                        + " In such a case, every CSR, RAM, submodule, and external module needs to be disambiguated" \
                                        + " with the (* ghostbus_domain=\"domain_name\" *) attribute which indicates the inteded domain."
                                    # UNSPECIFIED_DOMAIN
                                    raise GhostbusException(err)
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
                                        # No, what's happening here is setting the AW of the extmod from that of the fully-resolved bus
                                        # so what I need is to set the bus's base to that of the extmod.
                                        # Ok, so the extmod doesn't yet have a base, so I need to add it to a list to resolve later.
                                        stepchildren.append((ref, node.memories[mem_index])) # (parent extmod, child bus)
                                        # Here I'll give 'ref' a reference to the memory region node.memories[mem_index]
                                        # in case I need it later
                                        ref.sub_mr = node.memories[mem_index]
                                        del extmod_map[ref.name]
                                    else:
                                        printv(f" *** Can't find mem_index in extmod_map {extmod_map}")
                        if hasattr(node.memories[n], "resolve"):
                            node.memories[n].resolve()
                        node.memories[n].shrink()
                        printv(f"Shrunk {node.memories[n].label}.{node.memories[n].domain} to {node.memories[n].aw} bits")
                        if node.memories[n].empty:
                            continue
                        if not toptag and node._parent is not None:
                            added = False
                            # Here I need to get the inst->domain mapping from the parent, find the correct 'inst'
                            # that matches 'node', then add 'node' to the memory corresponding to the correct 'domain'
                            # Deliberately fail if this is not found in the map; something went wrong earlier
                            parent_domain = node._parent.domain_map[node.label]
                            for m in range(len(node._parent.memories)):
                                if node._parent.memories[m].domain == parent_domain:
                                    printv("                           Adding {} to {}".format(node.label, node._parent.label))
                                    node._parent.memories[m].add_item(node.memories[n])
                                    added = True
                            if not added:
                                # Probably an item was found referencing a new domain
                                #node._parent.memories.append(GBMemoryRegionStager(label=self._module_name,
                                #    hierarchy=self._hierarchy, domain=parent_domain))
                                #print("                     Created a new place to add {} anywhere".format(node.label))
                                toptag = True
                            # Keep track of this
                            node.parent_domain = parent_domain
                        else:
                            toptag = True # If we have no parent, we're top so might as well pretend like toptag was assigned
                            printd(f"                    {node.label} has no _parent")
                        # Add 'toptag' to each module instance listed in toptag_map
                        # For lack of a better structure, I guess we'll add the "toptag" to every domain (every MemoryRegion)
                        node.memories[n].toptag = toptag
                        if toptag:
                            top_memories.append(node.memories[n])
                else:
                    printd(f"       node {node.label} has no memories")
        for mem in self.memories:
            if hasattr(mem, "resolve"):
                mem.resolve()
        # Finalize the stitching together of child bus with parent extmod
        for parent_extmod, child_bus in stepchildren:
            if parent_extmod._base is not None:
                child_bus.base = parent_extmod._base
            else:
                raise GhostbusException("Failed to give an explicit base address to the child bus.")
        # Delete any zero-sized memories (they weren't added anyhow)
        for key, node in self.walk():
            todelete = []
            for n in range(len(node.memories)):
                node.memories[n].shrink()
                if node.memories[n].size == 0:
                    todelete.append(n)
            for n in todelete:
                del node.memories[n]
        return top_memories

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
                    # print("This node {node.label} has {len(node.memories)} domains.")
                    for mem in node.memories:
                        if mem.domain is not None:
                            if domain_memories.get(mem.domain, None) is not None:
                                err = f"Domain name {mem.domain} is declared in multiple modules " + \
                                       "or multiple instances of a single module.  Separate bus " + \
                                       "domains need to be globally unique."
                                # DOMAIN_COLLISION
                                raise GhostbusException(err)
                            domain_memories[mem.domain] = mem
        return domain_memories


class GhostBusser(VParser):
    _REFTYPE_CSR = 1
    _REFTYPE_RAM = 2
    _REFTYPE_EXT = 3
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
                    gen_block, inst, gen_index = block_inst(inst_name)
                    generate = None
                    if gen_block is not None:
                        attr_dict = inst_dict["attributes"]
                        source = attr_dict.get('src', None)
                        if autogenblk(gen_block):
                            feature_print(f"WARNING: Found potentially anonymous generate block in module {module_name}.")
                        if gen_index is None:
                            feature_print(f"Found instance {inst} inside a generate-if block {gen_block}")
                            generate = GenerateIf(gen_block)
                            inst_name = inst
                        else:
                            feature_print(f"Found instance {inst} inside a generate-for block {gen_block}, index {gen_index}")
                            generate = parseForLoop(gen_block, source)
                            if generate is None:
                                # UNPARSED_FOR_LOOP
                                raise GhostbusException(f"Failed to find for-loop for {inst} from source {source}")
                        feature_print(generate)
                    if ismodule(inst_name):
                        attr_dict = inst_dict["attributes"]
                        token_dict = GhostbusInterface.decode_attrs(attr_dict)
                        busname = token_dict.get(GhostbusInterface.tokens.BUSNAME, None)
                        toptag  = token_dict.get(GhostbusInterface.tokens.TOP, False)
                        module_info[mod_hash]["insts"][inst_name] = {"busname": busname, "toptag": toptag, "generate": generate}
                        modtree[mod_hash][inst_name] = inst_dict["type"]
            mrs = {}
            self._resetExtmods()
            self._resetGenerates()
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
                    gen_block, gen_netname, gen_index = block_inst(netname)
                    generate = None
                    if gen_block is not None:
                        if gen_index is None:
                            feature_print(f"Found CSR {gen_netname} inside a generate-if block {gen_block}")
                            generate = GenerateIf(gen_block)
                            if autogenblk(gen_block):
                                feature_print(f"WARNING: Found potentially anonymous generate block in module {module_name}.")
                            netname = gen_netname
                        else:
                            feature_print(f"Found CSR {gen_netname} inside a generate-for block {gen_block}, index {gen_index} and we'll handle it later")
                            generate = parseForLoop(gen_block, source)
                            generate._loop_index = gen_index
                            #if generate is None:
                            #    raise GhostbusException(f"Failed to find for-loop for {gen_netname}")
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
                        #print(f"New CSR: {netname}")
                        reg = GBRegister(name=netname, dw=dw, meta=source, access=access)
                        reg.initval = initval
                        reg.strobe = token_dict.get(GhostbusInterface.tokens.STROBE, False)
                        reg.alias = alias
                        reg.signed = signed
                        reg.busname = busname
                        reg.genblock = generate
                        reg.manual_addr = addr
                        if addr is not None:
                            reg.manually_assigned = True
                        if gen_block is not None and gen_index is not None:
                            # Only handling generate-for's.  generate-if's are easier
                            self._handleGenerates(self._REFTYPE_CSR, reg, source, module_name)
                        else:
                            # This may not be the best place for this step, but at least it gets done.
                            reg._readRangeDepth()
                            if mrs.get(busname, None) is None:
                                mrs[busname] = GBMemoryRegionStager(label=module_name, hierarchy=(module_name,), domain=busname)
                                printd("0: created mr label {} {} ({})".format(busname, mrs[busname].label, mod_hash))
                            mrs[busname].add(width=0, ref=reg, addr=addr)
                    elif exts is not None:
                        if generate is not None:
                            branch = generate.branch
                            if generate.isIf():
                                gen_index_str = ""
                            else:
                                gen_index_str = f"at index {gen_index} "
                            feature_print(f"  Boy howdy! I found extmod {exts} {gen_index_str}inside generate block {branch}")
                        dw = len(net_dict['bits'])
                        self._handleExtmod(module_name, netname, exts, dw, source, addr=addr, sub=subname, generate=generate)
                        if mrs.get(busname, None) is None:
                            mrs[busname] = GBMemoryRegionStager(label=module_name, hierarchy=(module_name,), domain=busname)
                            printd("1: created mr label {} {} ({})".format(busname, mrs[busname].label, mod_hash))
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
                    gen_block, gen_netname, gen_index = block_inst(memname)
                    generate = None
                    source = mem_dict['attributes']['src']
                    if gen_block is not None:
                        if autogenblk(gen_block):
                            feature_print(f"WARNING: Found potentially anonymous generate block in module {module_name}.")
                        if gen_index is None:
                            feature_print(f"Found RAM {gen_netname} inside a generate-if block {gen_block}")
                            generate = GenerateIf(gen_block)
                            memname = gen_netname
                        else:
                            feature_print(f"Found RAM {gen_netname} inside a generate-for block {gen_block}, index {gen_index} which we'll handle later")
                            #generate = parseForLoop(gen_block, source)
                            #if generate is None:
                            #    raise GhostbusException(f"Failed to find for-loop for {gen_netname}")
                    attr_dict = mem_dict["attributes"]
                    signed = net_dict.get("signed", None)
                    token_dict = GhostbusInterface.decode_attrs(attr_dict)
                    # for token, val in token_dict.items():
                    #     printd("{}: Decoded {}: {}".format(netname, GhostbusInterface.tokenstr(token), val))
                    access = token_dict.get(GhostbusInterface.tokens.HA, None)
                    addr = token_dict.get(GhostbusInterface.tokens.ADDR, None)
                    busname = token_dict.get(GhostbusInterface.tokens.BUSNAME, None)
                    if access is not None:
                        dw = int(mem_dict["width"])
                        size = int(mem_dict["size"])
                        aw = math.ceil(math.log2(size))
                        mem = GBMemory(name=memname, dw=dw, aw=aw, meta=source)
                        mem.signed = signed
                        mem.busname = busname
                        mem.genblock = generate
                        mem.manual_addr = addr
                        if addr is not None:
                            mem.manually_assigned = True
                        if gen_block is not None and gen_index is not None:
                            # Only handling generate-for's.  generate-if's are easier
                            self._handleGenerates(self._REFTYPE_RAM, mem, source, module_name)
                        else:
                            if mrs.get(busname, None) is None:
                                module_name = get_modname(mod_hash)
                                mrs[busname] = GBMemoryRegionStager(label=module_name, hierarchy=(module_name,), domain=busname)
                                printd("2: created mr label {} ({})".format(mrs[busname].label, mod_hash))
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
            generates = self._resolveGenerates()
            for ref in generates:
                # TODO - ExternalModule has no 'manual_addr', but I haven't yet figured out how to handle extmods
                #        instantiated within a generate block anyhow.
                mrs[ref.busname].add(width=ref.aw, ref=ref, addr=ref.manual_addr)
            extmods = self._resolveExtmods()
            for extmod in extmods:
                added = False
                for busname, mr in mrs.items():
                    if mr.domain == extmod.busname:
                        # I need to ensure I'm adding to the right domain!
                        mr.add(width=extmod.aw, ref=extmod, addr=extmod.base)
                        printd(f"  added {extmod.name} to MemoryRegion {mr.label} in domain {mr.domain}")
                        added = True
                if not added:
                    # UNKNOWN_DOMAIN
                    raise GhostbusException("Could not find the referenced domain {extmod.busname} for extmod {extmod.name} in module {module_name}.")
            module_info[mod_hash]["memory"] = mrs
            module_info[mod_hash]["explicit_busses"] = busnames_explicit
            module_info[mod_hash]["implicit_busses"] = busnames_implicit
        self._busValid = True
        for bus in self._ghostbusses:
            valid, msg = bus.validate()
            if not valid:
                self._busValid = False
        if len(self._ghostbusses) == 0:
            # NO_GHOSTBUS
            raise GhostbusException("No ghostbus found in codebase.")
        #print_dict(module_info)
        #self._busValid = self._top_bus.validate()
        self._top = top_mod
        #print("+++++++++++++++++++++++++++++++++++++++++++++++++")
        #print_dict(modtree, dohash=True)
        #print("+++++++++++++++++++++++++++++++++++++++++++++++++")
        modtree = self.build_modtree(modtree)
        #print("=================================================")
        #print_dict(modtree, dohash=True)
        #print("=================================================")
        memtree = self.build_memory_tree(modtree, module_info)
        self.memory_maps = memtree.resolve(verbose=False)
        print(f"Number of independent memory maps: {len(self.memory_maps)}")
        #for mmap in self.memory_maps:
        #    mmap.shrink()
        #memtree.distribute_busses()
        #self.memory_map.print(4)
        #self.memory_maps = {None: self.memory_map} # DELETEME
        ghostmods = {}
        for key, _info in module_info.items():
            mr = _info.get("memory", None)
            if mr is not None:
                ghostmods[key] = mr
        self.ghostmods = ghostmods
        return memtree

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
                                # NAME_COLLISION
                                raise GhostbusException(f"Cannot give multiple aliases to the same bus ({alias} and {bus.alias}).")
                        else:
                            bus.alias = alias
                    if extmod_name is not None:
                        if bus.extmod_name is not None:
                            if extmod_name != bus.extmod_name:
                                # MULTIPLE_ASSOCIATION
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

    # TODO DELETEME
    def _getRefByAttr(self, name, attr):
        for start, stop, ref in self.memory_map.get_entries():
            if hasattr(ref, attr):
                item = getattr(ref, attr)
                if name == getattr(ref, attr):
                    return ref
        return None

    # TODO DELETEME
    def _getRefByName(self, name):
        return self._getRefByAttr(name, 'name')

    # TODO DELETEME
    def _getRefByLabel(self, label):
        return self._getRefByAttr(label, 'label')

    # TODO DELETEME
    def findBusByName(self, busname):
        for bus in self._ghostbusses:
            if bus.name == busname:
                return bus
        return None

    def _resetExtmods(self):
        self._extmod_list = []
        return

    def _handleExtmod(self, module, netname, vals, dw, source, addr=None, sub=None, generate=None):
        block_name, extname, loop_index = block_inst(netname)
        if block_name is not None:
            feature_print(f"Extmod {extname} is instantiated within a Generate Block!")
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
                serr = "The 'dout' ('wdata') vector cannot be shared between multiple instances " + \
                      f"({instnames}). See: {source}"
                # SHARED_WDATA
                raise GhostbusException(serr)
        # print(f"netname = {netname}, dw = {dw}, portnames = {portnames}, instnames = {instnames}")
        #if generate is not None and generate.isFor():
        #    netname = f"{generate.branch}_{generate._loop_index}_{netname}"
        self._extmod_list.append((netname, dw, portnames, instnames, source, addr, sub, generate))
        return

    def _resolveExtmods(self):
        if len(self._extmod_list) == 0:
            return []
        # TODO FIXME - Here I need to combine all the extbusses from a For-Loop into a single bus
        busses = self._resolveExtmod(self._extmod_list)
        extmods = []
        for instname, data in busses.items():
            basename, bus = data
            #print(f"    instname {instname}; bus {bus.name}; bus['addr'] = {bus['addr']}; bus = {bus}")
            # Maybe I'll just sanitize the genblock bus ports names here?
            bus.deblock()
            extmod = ExternalModule(instname, extbus=bus, basename=basename)
            feature_print(f"  Resolving ExternalModule {instname}; bus.genblock = {bus.genblock}")
            extmods.append(extmod)
        return extmods

    def _resolveExtmod(self, data):
        ext_advice = "If there's only a " + \
                    "single external instance in this module, you must label at " + \
                    "least one net with the instance name, e.g.:\n" + \
                    '  (* ghostbus_ext="inst_name, clk" *) wire ext_clk;\n' + \
                    "If there is more than one external instance in this module, " + \
                    "you need to include the instance name in the attribute value for " + \
                    "each net in the bus (e.g. 'clk', 'addr', 'din', 'dout', 'we')."
        module_instnames = []
        for datum in data:
            #netname, dw, portnames, instnames, source, addr, sub, generate = datum
            generate = datum[7]
            instnames = datum[3]
            postfix = ""
            if generate is not None and generate.isFor():
                postfix = f"_{generate._loop_index}"
            for instname in instnames:
                if instname + postfix not in module_instnames:
                    module_instnames.append(instname + postfix)
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
                feature_print(f"instname = {instname}")
                base_bus = busses.get(instname, None)
                if base_bus is None:
                    bus = BusLB()
                    feature_print(f"    New bus id = {id(bus)}")
                else:
                    feature_print(f"    Got bus id = {id(bus)}")
                    bus = base_bus[1]
                this_instname = None
                for datum in data:
                    #print(f"  datum = {datum}")
                    netname, dw, portnames, instnames, source, addr, sub, generate = datum
                    postfix = ""
                    if generate is not None and generate.isFor():
                        postfix = f"_{generate._loop_index}"
                    #print(f"  :::: netname={netname}; dw={dw}; instnames={instnames}; portnames={portnames}; generate={generate}")
                    #print(f"  :::: bus.genblock = {bus.genblock}; generate={generate}")
                    rangestr = getUnparsedWidthRange(source)
                    if len(instnames) == 0 and universal_inst is not None:
                        instnames.append(universal_inst)
                    for net_instname in instnames:
                        #print(f"  net_instname = {net_instname}, net_instname+postfix = {net_instname+postfix}")
                        if net_instname+postfix == instname:
                            this_instname = net_instname
                            if sub is not None and bus.sub is None:
                                bus.sub = sub
                            if bus.genblock is not None and bus.genblock.__class__ != generate.__class__:
                                feature_print(f"%%%%%%%%%%%%%%% Wtf? {bus.genblock} != {generate}. {instname} {netname} {instnames} {portnames}")
                            bus.genblock = generate
                            for portname in portnames:
                                feature_print(f"  bus.set_port({portname}, {netname}, portwidth={dw}, rangestr={rangestr})")
                                bus.set_port(portname, netname, portwidth=dw, rangestr=rangestr, source=source)
                            if addr is not None:
                                # print(f"addr is not None: datum = {datum}")
                                errst = None
                                try:
                                    bus.base = addr
                                except GhostbusException as err:
                                    errst = str(err)
                                if errst != None:
                                    # MULTIPLE_ADDRESSES
                                    raise GhostbusException(f"{instnames}: {errst}")
                busses[instname] = (this_instname, bus) # A funny hack for block-scope extmods
        if inst_err:
            serr = "No instance referenced for external bus. " + ext_advice
            # NO_EXTMOD_INSTANCE
            raise GhostbusException(serr)
        for instname, data in busses.items():
            basename, bus = data
            valid, msg = bus.validate()
            busses[instname] = (basename, bus)
            #print_dict(busses[instname])
        return busses

    def _resetGenerates(self):
        """Get ready to handle a new module with potentitally more generate blocks."""
        self._generates = {}
        return

    def _handleGenerates(self, reftype, ref, yosrc, module_name):
        """Handle an item 'ref' of type 'reftype' instantiated inside a generate block within module 'module_name'.
        The 'yosrc' string helps us find and parse the source which is unfortunately necessary."""
        # TODO - I don't think reftype of 'ext' is ever used.  Can it be?  Currently passed to _handleExtmod()
        block_name, netname, loop_index = block_inst(ref.name)
        if block_name is None:
            raise Exception(f"Internal error. The string {ref.name} somehow got passed to _handleGenerates() even though it fails block_inst()")
        if autogenblk(block_name):
            print(f"WARNING: Found potentially anonymous generate block in module {module_name}.")
        if self._generates.get(block_name) is None:
            self._generates[block_name] = {"module_name": module_name, "source": yosrc, "csrs": {}, "rams": {}, "exts": {}}
        if self._generates[block_name]["source"] is None:
            self._generates[block_name]["source"] = yosrc
        refstrs = {self._REFTYPE_CSR: "csrs", self._REFTYPE_RAM: "rams", self._REFTYPE_EXT: "exts"}
        refstr = refstrs[reftype]
        if self._generates[block_name][refstr].get(netname) is not None:
            self._generates[block_name][refstr][netname]["indices"].append(int(loop_index))
            self._generates[block_name][refstr][netname]["refs"].append(ref)
        else:
            self._generates[block_name][refstr][netname] = {"indices": [int(loop_index)], "refs": [ref]}
        return

    def _resolveGenerates(self):
        # TODO: find any other instances and use the greatest `Unrolled_AW` for each instance
        """
          0. Ensure all indicies are numeric, sequential, and complete
          1. Ensure the length of the indicies for each csr in the branch is identical
          2. Use the yosrc to find the for-loop parameters
          3. Calculate the size of the resulting objects. `Unrolled_AW = element_AW + clog2(len(indicies))`
          4. Return items to be added to the memory map
        """
        results = []
        for block_name, block_info in self._generates.items():
            forloop = parseForLoop(block_name, block_info["source"])
            if forloop is None:
                # UNPARSED_FOR_LOOP
                raise GhostbusException(f"Failed to find for-loop around {block_info['source']}")
            loop_len = None
            for reftype in ("csrs", "rams", "exts"): # TODO again, 'exts' is probably unused
                for netname, netdict in block_info[reftype].items():
                    indices = netdict["indices"]
                    refs = netdict["refs"]
                    ref = refs[0]
                    if not check_complete_indices(indices):
                        raise GhostbusInternalException(f"Did not find all indices for {ref.name} in {block_info['module_name']}")
                    if loop_len is None:
                        loop_len = len(indices)
                    elif len(indices) != loop_len:
                        err = f"Somehow I'm getting inconsistent number of loops through {block_name} in {block_info['module_name']}" \
                            + f" ({len(indices)} != {loop_len})"
                        raise GhostbusInternalException()
                    aw = ref.aw
                    new_aw = aw + bits(loop_len) - 1 # I'm pretty sure it's -1
                    ref.block_aw = aw
                    ref.aw = new_aw
                    #ref.aw = new_aw
                    #ref.ref_list = refs
                    ref.name = netname
                    forloop.loop_len = loop_len
                    ref.genblock = forloop
                    if hasattr(ref, "_readRangeDepth"):
                        # I need to call reg._readRangeDepth() on the resulting GBRegister or GBMemory objects
                        ref._readRangeDepth()
                    results.append(ref)
                    feature_print(f"Generate Loop {block_name} of len {loop_len}: {ref.name} now has AW {ref.aw}")
        return results

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
            # NO_TOP_SPECIFIED
            raise GhostbusException("I don't know how to do this without top specified")
        modtree = {}
        for module, mod_dict in dd.items():
            if module == top:
                modtree[module] = {}
        if len(modtree) == 0:
            # NO_TOP_SPECIFIED
            raise GhostbusException("Could not find top: {}".format(top))
        nested = False
        dd_keys = [key for key in dd.keys()]
        for module in dd_keys:
            instances_dict = dd[module]
            #print(f"    Processing: {module}")
            instance_keys = [key for key in instances_dict.keys()]
            #if len(instances_dict) == 0:
            #    print("      Empty instances_dict!")
            for inst_name in instance_keys:
                inst_key = instances_dict[inst_name]
                dict_key = (inst_name, inst_key)
                inst = dd.get(inst_key, None)
                #print(f"      Instance key: {dict_key}; dd[inst_key] = {inst}")
                del instances_dict[inst_name]
                if inst is None:
                    print(f"WARNING: Unknown module {inst_key}. Treating as black box.")
                else:
                    # Update memory in-place
                    #cp = deep_copy(inst)
                    #print(f"        Adding dict entry {dict_key}: {cp}")
                    #dd[module][dict_key] = cp
                    dd[module][dict_key] = inst
        return deep_copy(dd[top])

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
            memtree_node.genblock_map = {inst_name: insts[inst_name]["generate"] for inst_name in insts.keys()}
            mrs = instdict.get("memory")
            busses_explicit = instdict.get("explicit_busses", [])
            # NOTE: Redundant 'declared_busses' is currently stored and used in both the node and each of its
            #       memory instances.  I'd like to make store it only at the node.
            memtree_node.declared_busses = busses_explicit
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
                #print(f"no {key} in ghostmods")
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
    def memoryRegionToJSONDict(cls, mem, flat=True, mangle_names=False, top=True, drops=(), short=True):
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
                subdd = cls.memoryRegionToJSONDict(ref, flat=flat, mangle_names=mangle_names, top=False, drops=drops, short=False)
                if flat:
                    update_without_collision(dd, subdd)
                else:
                    dd[ref.name] = subdd
            elif isinstance(ref, ExternalModule) and ref.sub_mr is not None:
                # If this extmod is a gluemod, I need to collect its branch like a submodule
                subdd = cls.memoryRegionToJSONDict(ref.sub_mr, flat=flat, mangle_names=mangle_names, top=False, drops=drops, short=False)
                if flat:
                    update_without_collision(dd, subdd)
                else:
                    dd[ref.name] = subdd
            elif isinstance(ref, Register) or isinstance(ref, ExternalModule):
                # FIXME HACK! Make up your damn mind, Keef!  Are you unrolling ExternalModules before, or AFTER adding to the memory map!?!?!
                if isinstance(ref, ExternalModule):
                    copies = (ref,)
                else:
                    copies = ref.unroll()
                for ref in copies:
                    if ref.signed is not None and ref.signed:
                        signstr = "signed"
                    else:
                        signstr = "unsigned"
                    entry = {
                        "access": Register.accessToStr(ref.access),
                        "addr_width": ref.aw,
                        "sign": signstr,
                        #"base_addr": mem.base + start,
                        "base_addr": mem.base + ref.base,
                        "data_width": ref.dw,
                    }
                    if hasattr(ref, "alias") and (ref.alias is not None) and (len(str(ref.alias)) != 0):
                        hier_str = str(ref.alias)
                    elif flat:
                        hierarchy = list(top_hierarchy)
                        hierarchy.append(ref.name)
                        printd(f"{mem.name}: {mem.hierarchy}, {ref.name}: hierarchy = {hierarchy}")
                        if short or not mangle_names:
                            hier_str = ".".join(strip_empty(hierarchy))
                        else:
                            hier_str = "_".join(strip_empty(hierarchy))
                    else:
                        hier_str = ref.name
                    if hier_str not in drops:
                        dd[hier_str] = entry
            else:
                printd(f"What is this? {ref}")
        if flat and short:
            dd = cls._shortenNames(dd)
        return dd


    @classmethod
    def _shortenNames(cls, dd):
        """Replace hierarchical names with the shortest version that remains unique for each."""
        namedict = {}
        # First pass: {short: longs}
        conflicts = []
        for key in dd.keys():
            short = key.split('.')[-1]
            if namedict.get(short) is None:
                namedict[short] = [key]
            else:
                namedict[short].append(key)
                conflicts.append(short)
        # Second pass: handle conflicts
        longmap = {}
        for short in conflicts:
            longs = namedict.get(short)
            if longs is None:
                # Already handled
                continue
            n = 1
            newshortlist = None
            while True:
                # No one gets to stay short (otherwise we couldn't predict which one is correct)
                newshorts = []
                isdone = False
                for long in longs:
                    newshort, isdone = cls._flatten(long, n)
                    longmap[newshort] = long
                    newshorts.append(newshort)
                good = True
                for newshort in newshorts:
                    if newshorts.count(newshort) > 1:
                        good = False
                if good:
                    newshortlist = newshorts
                    break
                if isdone:
                    raise GhostbusNameCollision(f"Could not disambiguate {longs}")
                n += 1
            if newshortlist is None:
                raise Exception("How did this happen?")
            del namedict[short]
            for newshort in newshorts:
                namedict[newshort] = [longmap[newshort]]
        newdd = {}
        for short, longs in namedict.items():
            newdd[short] = dd[longs[0]]
        return newdd

    @staticmethod
    def _flatten(ss, n=0):
        """Change 'a.b.c.d' to 'd' if n==0, 'c_d' if n==1, 'b_c_d' if n==2, 'a_b_c_d' if n >= 3"""
        subs = ss.split('.')
        done = False
        if n > len(subs) - 1:
            done = True
            n = len(subs)-1
        n = -(n+1)
        return '_'.join(subs[n:]), done

    def write(self, filename, path="_auto", flat=False, mangle=False, short=False):
        import os
        import json
        if path is not None:
            filepath = os.path.join(path, filename)
        else:
            filepath = filename
        ss = json.dumps(self.memoryRegionToJSONDict(self.memtree, flat=flat, mangle_names=mangle, drops=self._drops, short=short), indent=2)
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


def parseForLoop(branch_name, yosrc):
    loop_index, start, comp_op, comp_val, inc = findForLoop(yosrc)
    if loop_index is None:
        return None
    return GenerateFor(branch_name, loop_index, start, comp_op, comp_val, inc)


def handleGhostbus(args):
    try:
        gb = GhostBusser(args.files[0], top=args.top, include_dirs=args.include) # Why does this end up as a double-wrapped list?
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
            dec = DecoderLB(memtree, gbusses, gbportbus, debug=args.debug)
            if args.live:
                dec.GhostbusMagic(dest_dir=args.dest)
            if args.map is not None:
                dec.ExtraVerilogTestbench(args.map, gbusses)
        if args.json is not None:
            # JSON
            if trim:
                gb.trim_hierarchy()
            single_bus = True
            if len(gb.memory_maps) > 1:
                single_bus = False
            for mem_map in gb.memory_maps:
                busname = mem_map.domain
                jm = JSONMaker(mem_map, drops=args.ignore)
                if busname is None or single_bus:
                    filename = str(args.json)
                else:
                    import os
                    fname, ext = os.path.splitext(args.json)
                    filename = fname + f".{busname}" + ext
                jm.write(filename, path=args.dest, flat=args.flat, mangle=args.mangle, short=args.short)
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
    parser.add_argument("-I", "--include", default=[], action="append", help="Directories to search for `include files.")
    parser.add_argument("--dest",   default="_autogen", help="Directory name for auto-generated files.")
    parser.add_argument("--map",    default=None, help="[experimental] Filename for a generated memory map in Verilog form for testing.")
    parser.add_argument("--json",   default=None, help="Filename for a generated memory map as a JSON file.")
    parser.add_argument("--flat",   default=False, action="store_true", help="Yield a flat JSON, rather than hierarchical.")
    parser.add_argument("--notrim", default=False, action="store_true", help="Disable trimming common root from register hierarchy.")
    parser.add_argument("--mangle", default=False, action="store_true", help="Names are hierarchically qualified and joined by '_'.")
    parser.add_argument("--short",  default=False, action="store_true", help="Names are maximally shortened (remaining unique).")
    parser.add_argument("--debug",  default=False, action="store_true", help="Append debug trace comments to generated code.")
    parser.add_argument("--ignore", default=[], action="append", help="Register names to drop from the JSON.")
    parser.add_argument("files",    default=[], action="append", nargs="+", help="Source files.")
    args = parser.parse_args()
    return handleGhostbus(args)


if __name__ == "__main__":
    #testWalkDict()
    exit(doGhostbus())
