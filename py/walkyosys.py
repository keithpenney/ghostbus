import re
from struct_walker import JSONBrowser, StructWalker, strStruct

#I need these JSON queries:
#  1 get each module definition (global)
#  2 get each GB reg/mem (per-module)
#    - with attributes
#  3 get each module instance (per-module)
#    - with attributes


def WalkAllModules(filename):
    jb = JSONBrowser(filename)
    def print_instance(trace, val):
        if len(trace) > 1:
            if trace[-2] == "modules":
                module_name = trace[-1]
                print(f"? -> {module_name}")
            elif trace[-2] == "cells":
                hide_name = val.get("hide_name", None)
                if hide_name == 0:
                    inst_name = trace[-1]
                    module_name = val.get("type", None)
                    print(f"{inst_name} -> {module_name}")
        return False
    jb.walk(do=print_instance)
    return


#=======================
#========== 1 ==========
#=======================
def get_modules(trace, val):
    """yosys"""
    if len(trace) > 1:
        if trace[-2] == "modules":
            module_name = trace[-1]
            return True
    return False


#=======================
#========== 2 ==========
#=======================
def get_gbnets(trace, val):
    """yosys"""
    if hasattr(val, "get"):
        if len(trace) < 2:
            return False
        kind = trace[-2]
        if kind in ("netnames", "ports", "memories"):
            attrs = val.get("attributes")
            if attrs is not None:
                for attrname in attrs.keys():
                    if attrname.startswith("ghostbus"):
                        return True
    return False


#=======================
#========== 3 ==========
#=======================
def get_instances(trace, val):
    """yosys"""
    if len(trace) > 1:
        if trace[-2] == "cells":
            hide_name = val.get("hide_name", None)
            if hide_name == 0:
                inst_name = trace[-1]
                module_name = val.get("type", None)
                return True
    return False


def ModuleIterator(filename, show_wires=False, show_regs=False):
    jb = JSONBrowser(filename)
    _iter = jb.iter_walk(do=get_modules)
    for key, val in _iter:
        module_name = key
        print(f"== Module: {module_name} ==")
        #GBIterator(val, indent=" "*4)
        #InstanceIterator(val, indent=" "*4)
        _subIter = gbnetsIterator(val)
        for dd in _subIter:
            print(strStruct(dd))
        continue
        if show_wires:
            print("  :: Wires ::")
            WireIterator(val, indent=" "*4)
        if show_regs:
            print("  :: Regs ::")
            RegIterator(val, indent=" "*4)
    return


def print_wires(trace, val):
    if hasattr(val, "get"):
        kind = val.get("kind", None)
        if kind == "Net":
            netname = val.get("name", None)
            nettype = val.get("type", None)
            print(f"{indent}{nettype} {netname}")
    return False


def print_regs(trace, val):
    if hasattr(val, "get"):
        kind = val.get("kind", None)
        if kind == "Variable":
            netname = val.get("name", None)
            nettype = val.get("type", None)
            print(f"{indent}{nettype} {netname}")
    return False


def get_wires(trace, val):
    if hasattr(val, "get"):
        kind = val.get("kind", None)
        if kind == "Net":
            return True
    return False


def get_regs(trace, val):
    if hasattr(val, "get"):
        kind = val.get("kind", None)
        if kind == "Variable":
            return True
    return False


def StructIterator(dd, do = lambda trace, val : False, indent=""):
    jb = StructWalker(dd)
    _iter = jb.walk(do=do)
    return


def WireIterator(dd, indent=""):
    jb = StructWalker(dd)
    _iter = jb.iter_walk(do=get_wires)
    for val in _iter:
        if val is None:
            continue
        netname = val.get("name", None)
        nettype = val.get("type", None)
        print(f"{indent}{nettype} {netname}")
    return


def RegIterator(dd, indent=""):
    jb = StructWalker(dd)
    _iter = jb.iter_walk(do=get_regs)
    for val in _iter:
        if val is None:
            continue
        netname = val.get("name", None)
        nettype = val.get("type", None)
        print(f"{indent}{nettype} {netname}")
    return


def GBIterator(dd, indent=""):
    print("  :: Ghostbus ::")
    jb = StructWalker(dd)
    _iter = jb.iter_walk(do=get_gbnets, depth=4)
    for key, val in _iter:
        gbattrs = []
        attrs = val.get("attributes")
        for attrname, attrval in attrs.items():
            if attrname.startswith("ghostbus"):
                gbattrs.append(attrname)
        gbstr = ", ".join(gbattrs)
        netname = key
        print(f"{indent}(* {gbstr} *) {netname}")
    return


def InstanceIterator(dd, indent=""):
    print("  :: Instances ::")
    jb = StructWalker(dd)
    _iter = jb.iter_walk(do=get_instances, depth=4)
    for key, val in _iter:
        instname = key
        attrs = val.get("attributes", {})
        print(f"{instname}: {strStruct(attrs)}")
    return


def gbnetsIterator(mod_dict):
    jb = StructWalker(mod_dict)
    _iter = jb.iter_walk(do=get_gbnets, depth=4)
    for key, val in _iter:
        gbattrs = {}
        elem_lo, elem_hi = (None, None)
        attrs = val.get("attributes")
        bits = val.get("bits") # registers
        width = val.get("width") # arrays
        size = val.get("size") # arrays
        elem_lo = val.get("start_offset") # arrays
        src = None
        for attrname, attrval in attrs.items():
            if attrname.startswith("ghostbus"):
                gbattrs[attrname] = attrval
            if attrname == "src":
                src = attrval
        if bits is not None:
            index_hi = len(bits)-1
        elif width is not None:
            index_hi = width-1
        else:
            raise YosysParsingError("Expected either 'bits' or 'width'. Found neither.")
        if width is not None:
            if elem_lo is None:
                raise YosysParsingError("Key 'width' has a value, but key 'start_offset' somehow doesn't")
            elem_hi = elem_lo + size - 1
        index_lo = 0
        index_hi_str = str(index_hi)
        index_lo_str = str(index_lo)
        netdict = {
            "name": key,
            "type": None, # TODO nettype
            "range": (index_hi, index_lo),
            "rangestr": (index_hi_str, index_lo_str), # TODO range str
            "attributes": gbattrs,
            "src" : src,
            "array": (elem_lo, elem_hi),
        }
        yield netdict
    return


if __name__ == "__main__":
    import sys
    filename = sys.argv[1]
    #WalkAllModules(filename)
    ModuleIterator(filename)
