import re
from struct_walker import JSONBrowser, StructWalker, strStruct


def _split_body(bodystr):
    restr = r"(\d+)\s+"
    _match = re.search(restr, bodystr)
    if _match:
        addr = _match.groups()[0]
        remainder = bodystr[_match.end():]
        return addr, remainder
    raise Exception(f"Missed {bodystr}")
    return None, None


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


def get_instances(trace, val):
    if len(trace) > 1:
        if trace[-2] == "cells":
            hide_name = val.get("hide_name", None)
            if hide_name == 0:
                inst_name = trace[-1]
                module_name = val.get("type", None)
                print(f"{inst_name} -> {module_name}")
    return False


def get_modules(trace, val):
    if len(trace) > 1:
        if trace[-2] == "modules":
            module_name = trace[-1]
            return True
    return False


def ModuleIterator(filename, show_wires=False, show_regs=False):
    jb = JSONBrowser(filename)
    _iter = jb.iter_walk(do=get_modules)
    for key, val in _iter:
        module_name = key
        print(f"== Module: {module_name} ==")
        print("  :: Ghostbus ::")
        GBIterator(val, indent=" "*4)
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
    jb = StructWalker(dd)
    def get_gbnets(trace, val):
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


if __name__ == "__main__":
    import sys
    filename = sys.argv[1]
    #WalkAllModules(filename)
    ModuleIterator(filename)
