import re
from jbrowse import JSONBrowser, StructBrowser, strStruct


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
        if hasattr(val, "get"):
            #print(strStruct(val, depth=1))
            kind = val.get("kind", None)
            if kind == "Instance":
                instname = val.get("name", None)
                body = val.get("body", None)
                if hasattr(body, "items"):
                    modname = body["name"]
                else:
                    addr, modname = _split_body(body)
                print(f"{instname} -> {modname}")
                return True
        return False
    jb.walk(do=print_instance)
    return


def ModuleIterator(filename, show_wires=False, show_regs=False):
    jb = JSONBrowser(filename)
    def get_instance(trace, val):
        if hasattr(val, "get"):
            kind = val.get("kind", None)
            if kind == "Instance":
                return True
        return False
    _iter = jb.iter_walk(do=get_instance)
    for val in _iter:
        instname = val.get("name", None)
        body = val.get("body", None)
        if hasattr(body, "items"):
            modname = body["name"]
        else:
            addr, modname = _split_body(body)
        print(f"== Module: {instname} -> {modname} ==")
        print("  :: Ghostbus ::")
        GBIterator(val, indent=" "*4)
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
    jb = StructBrowser(dd)
    _iter = jb.walk(do=do)
    return


def WireIterator(dd, indent=""):
    jb = StructBrowser(dd)
    _iter = jb.iter_walk(do=get_wires)
    for val in _iter:
        if val is None:
            continue
        netname = val.get("name", None)
        nettype = val.get("type", None)
        print(f"{indent}{nettype} {netname}")
    return


def RegIterator(dd, indent=""):
    jb = StructBrowser(dd)
    _iter = jb.iter_walk(do=get_regs)
    for val in _iter:
        if val is None:
            continue
        netname = val.get("name", None)
        nettype = val.get("type", None)
        print(f"{indent}{nettype} {netname}")
    return


def GBIterator(dd, indent=""):
    print("GBIterator")
    jb = StructBrowser(dd)
    def get_gbnets(trace, val):
        if hasattr(val, "get"):
            kind = val.get("kind", None)
            if kind in ("Net", "Variable"):
                attrs = val.get("attributes")
                if attrs is not None:
                    for attr in attrs:
                        attrname = attr.get("name")
                        if attrname.startswith("ghostbus"):
                            return True
        return False
    _iter = jb.iter_walk(do=get_gbnets, depth=4)
    for val in _iter:
        if val is None:
            continue
        gbattrs = []
        attrs = val.get("attributes")
        for attr in attrs:
            attrname = attr.get("name")
            if attrname.startswith("ghostbus"):
                gbattrs.append(attrname)
        gbstr = ", ".join(gbattrs)
        netname = val.get("name", None)
        nettype = val.get("type", None)
        print(f"{indent}(* {gbstr} *) {nettype} {netname}")
    return


if __name__ == "__main__":
    import sys
    filename = sys.argv[1]
    #WalkAllModules(filename)
    ModuleIterator(filename)
