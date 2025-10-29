from policy import Policy
from memory_map import MemoryRegion, Register
from gbmemory_map import ExternalModule
from util import strip_empty
from syntax import ROMX, ROMN


_DEBUG_PRINT=False
def printd(*args, **kwargs):
    if _DEBUG_PRINT:
        print(*args, **kwargs)


class JSONMaker():
    def __init__(self, memtree, drops=()):
        self.memtree = memtree
        self._drops = drops

    @classmethod
    def finalizeJSONDict(cls, dd, flat=True, mangle_names=False, short=True):
        if flat and short:
            dd = cls._shortenNames(dd)
        if mangle_names:
            dd = cls._mangleNames(dd)
        return dd

    @classmethod
    def memoryRegionToJSONDict(cls, mem, flat=True, mangle_names=False, top=True, drops=(), short=True, indent=0):
        """ Returns a dict ready for JSON-ification using our preferred memory map style:
        // Example
        {
            "regname": {
                "access": "rw",
                "addr_width": 0,
                "sign": "unsigned",
                "base_addr": 327681,
                "data_width": 1,
            },
        }
        """
        if flat:
            flavor = ROMX
        else:
            flavor = ROMN
        dd = flavor.empty()
        if flavor == ROMN:
            dd[ROMN.key_instanceof] = mem.module_name
        entries = mem.get_entries()
        #top_hierarchy = mem.hierarchy
        if top:
            # Note! Discarding top-level name in hierarcy
            top_hierarchy = []
        else:
            top_hierarchy = mem.hierarchy[1:]
        # Returns a list of entries. Each entry is (start, end+1, ref) where 'ref' is applications-specific
        #print_entries = [f"{ref[-1].name}" for ref in entries]
        #sindent = " "*indent
        #print(f"{sindent}6670 {mem.name}({mem.domain})-- {print_entries}")
        for start, stop, ref in entries:
            if isinstance(ref, MemoryRegion):
                #print(f"{sindent}6671 {ref.name}.{ref.domain} {id(ref)}")
                subdd = cls.memoryRegionToJSONDict(ref, flat=flat, mangle_names=mangle_names, top=False, drops=drops, short=False, indent=indent+2)
                #print(f"{sindent}6671 Done with {ref.name}.{ref.domain}")
                if flavor == ROMX:
                    #print(f"{sindent}Updating from subdd {ref.name} {ref.domain} id(ref) = {id(ref)}")
                    update_without_collision(dd, subdd)
                elif flavor == ROMN:
                    #dd["modules"][ref.instance_name] = subdd
                    flavor.add_module(dd, ref.instance_name, subdd)
                else:
                    raise Exception("Should never get here")
            elif isinstance(ref, ExternalModule) and ref.sub_mr is not None:
                # If this extmod is a gluemod, I need to collect its branch like a submodule
                #print(f"{sindent}6672 {ref.name} {id(ref)}")
                subdd = cls.memoryRegionToJSONDict(ref.sub_mr, flat=flat, mangle_names=mangle_names, top=False, drops=drops, short=False, indent=indent+2)
                if flavor == ROMX:
                    update_without_collision(dd, subdd)
                elif flavor == ROMN:
                    #dd["modules"][ref.label] = subdd
                    flavor.add_module(dd, ref.label, subdd)
                else:
                    raise Exception("Should never get here")
            elif isinstance(ref, Register) or isinstance(ref, ExternalModule):
                #print(f"+ [{mem.domain}] {'.'.join(top_hierarchy)}.{ref.name}")
                ref_list = (ref,)
                if Policy.aligned_for_loops and ref.isFor():
                    ref_list = ref.ref_list
                for ref in ref_list:
                    desc = None
                    if hasattr(ref, "desc") and (ref.desc is not None) and (len(ref.desc) > 0):
                        desc = str(ref.desc)
                    entry = flavor.new_entry(base = mem.base + ref.base, aw = ref.aw, dw = ref.dw,
                                             access = ref.access, signed = ref.signed, descript = desc)
                    if flavor == ROMX:
                        if hasattr(ref, "alias") and (ref.alias is not None) and (len(str(ref.alias)) != 0):
                            hier_str = str(ref.alias)
                        elif flat:
                            hierarchy = list(top_hierarchy)
                            hierarchy.append(ref.name)
                            hier_str = Policy.flatten_hierarchy(strip_empty(hierarchy))
                            #hier_str = ".".join(strip_empty(hierarchy))
                        else:
                            hier_str = ref.name
                    else: # flavor == ROMN:
                        hier_str = ref.label
                    if hier_str not in drops:
                        flavor.add_reg(dd, hier_str, entry)
            else:
                printd(f"What is this? {ref}")
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

    @classmethod
    def _mangleNames(cls, dd):
        """Replace '.' in string keys with '_'"""
        newdd = {}
        for key, val in dd.items():
            key = key.replace('.', '_')
            if hasattr(val, "items"):
                val = cls._mangleNames(val)
            newdd[key] = val
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
        dd = self.memoryRegionToJSONDict(self.memtree, flat=flat, mangle_names=mangle, drops=self._drops, short=short)
        dd = self.finalizeJSONDict(dd, flat=flat, mangle_names=mangle, short=short)
        ss = json.dumps(dd, indent=2)
        with open(filepath, 'w') as fd:
            fd.write(ss)
        return


def update_without_collision(old_dict, new_dict):
    """Calls old_dict.update(new_dict) after ensuring there are no identical keys in both dicts."""
    all_errs = []
    for key in new_dict.keys():
        if key in old_dict:
            #err = f"Memory map key {key} defined more than once." + \
            #      f" If {key} is an alias, remember that they are global," + \
            #      " so you can't use an alias in a module that gets instantiated more than once." + \
            #      f" If {key} is not an alias, ensure it is indeed only declared once per module." + \
            #      " If it's only declared once (and thus passes Verilog linting), submit a bug report."
            all_errs.append(key)
            #raise GhostbusNameCollision(err)
    if len(all_errs) > 0:
        err = f"Found duplicate entry names in the memory map:" + \
              "\n  ".join(all_errs)
        raise GhostbusNameCollision(err)
    old_dict.update(new_dict)
    return

