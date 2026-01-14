import re
from struct_walker import JSONBrowser, StructWalker, strStruct
from slangparse import VParser, parse_typestr

#I need these JSON queries:
#  1 get each module definition (global)
#  2 get each GB reg/mem (per-module)
#    - with attributes
#  3 get each module instance (per-module)
#    - with attributes


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


#=======================
#========== 1 ==========
#=======================
def get_modules(trace, val):
    """slang"""
    if hasattr(val, "get"):
        kind = val.get("kind", None)
        body = val.get("body", None)
        if kind == "Instance" and hasattr(body, "items"):
            return True
    return False


#=======================
#========== 2 ==========
#=======================
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


#=======================
#========== 3 ==========
#=======================
def get_instances(trace, val):
    """slang"""
    if hasattr(val, "get"):
        kind = val.get("kind", None)
        if kind == "Instance":
            return True
    return False


def get_CST_module_dict(filepath, module_name):
    jb = JSONBrowser(filepath)
    def find_module(trace, val):
        #"kind": "ModuleDeclaration"
        if not hasattr(val, "get"):
            return False
        kind = val.get("kind")
        if kind != "ModuleDeclaration":
            return False
        header = val.get("header")
        header_name = header.get("name")
        #"header"->"name"->"kind": "Identifier"
        #"header"->"name"->"text": module_name
        if (header_name.get("kind") == "Identifier") and (header_name.get("text") == module_name):
            return True
        return False
    _iter = jb.iter_walk(do=find_module)
    for key, val in _iter:
        return val
    return None


def ModuleIterator(ast_filepath, cst_filepath, show_wires=False, show_regs=False):
    jb = JSONBrowser(ast_filepath)
    _iter = jb.iter_walk(do=get_modules)
    modules = []
    for key, val in _iter:
        instname = val.get("name", None)
        body = val.get("body", None)
        module_name = body["name"]
        if module_name in modules:
            continue
        modules.append(module_name)
        print(f"== Module: {module_name} ==")
        #print("  :: Ghostbus ::")
        #GBIterator(val, indent=" "*4)
        sub_cst = get_CST_module_dict(cst_filepath, module_name)
        reg_iter = VParser._gbnetsIterator(val, sub_cst)

        for dd in reg_iter:
            print(strStruct(dd))
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
    for key, val in _iter:
        if val is None:
            continue
        netname = val.get("name", None)
        nettype = val.get("type", None)
        print(f"{indent}{nettype} {netname}")
    return


def RegIterator(dd, indent=""):
    jb = StructWalker(dd)
    _iter = jb.iter_walk(do=get_regs)
    for key, val in _iter:
        if val is None:
            continue
        netname = val.get("name", None)
        nettype = val.get("type", None)
        print(f"{indent}{nettype} {netname}")
    return


def GBIterator(dd, indent=""):
    jb = StructWalker(dd)
    _iter = jb.iter_walk(do=get_gbnets, depth=4)
    for key, val in _iter:
        if val is None:
            continue
        gbattrs = {}
        attrs = val.get("attributes")
        for attr in attrs:
            attrname = attr.get("name")
            attrval  = attr.get("value")
            if attrname.startswith("ghostbus"):
                gbattrs[attrname] = attrval
        gbstr = ", ".join([key for key in gbattrs.keys()])
        netname = val.get("name", None)
        nettype = val.get("type", None)
        print(f"{indent}(* {gbstr} *) {netname}")
    return


if __name__ == "__main__":
    import sys
    ast_filename = sys.argv[1]
    cst_filename = sys.argv[2]
    #WalkAllModules(filename)
    ModuleIterator(ast_filename, cst_filename)
