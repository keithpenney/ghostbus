# A nice use case for slang

from struct_walker import StructWalker, strStruct
from slangparse import VParser, parse_typestr

dir_dict = {
    "In": "input",
    "Out": "output",
    "InOut": "inout",
}

def _to_bool(b=False, default=True):
    if hasattr(b, "lower"):
        bs = b.strip().lower()
        if bs == "false":
            return False
        elif bs == "true":
            return True
        else:
            return default
    elif b:
        return True
    return False


def instantiate(args):
    dd = extract(args.svfile, modname=args.module)
    if args.flavor == "keef" or args.flavor == None:
        # only flavor right now
        num_params = len(dd["params"])
        module_name = dd["module_name"]
        if num_params == 0:
            print(f"{module_name} {module_name}_i (")
        else:
            for param_name, val in dd["params"]:
                print(f"localparam {param_name} = {val};")
            print(f"\n{module_name} #(")
            ss = []
            for param_name, val in dd["params"]:
                ss.append(f"  .{param_name}({param_name})")
            print(",\n".join(ss))
            print(f") {module_name}_i (", end="")
        comment = None
        for dirstr, rstr, name in dd["ports"]:
            if comment is not None:
                print(f", // {comment}")
            else:
                print()
            print(f"  .{name}({name})", end="")
            comment = f"{dirstr}{rstr}"
        if comment is not None:
            print(f", // {comment}", end="")
        print("\n);")
    return


def extract(svfile, modname=None):
    vp = VParser([svfile], top=None)
    found = False
    dd = {
        "module_name": None,
        "params": [],
        "ports": [],
    }
    for mod_hash, mod_dict in vp.get_modules():
        module_name = vp.get_module_name(mod_dict, mod_hash=mod_hash)
        if (modname is not None) and (module_name != modname):
            # keep looking
            continue
        found = True
        dd["module_name"] = module_name
        for key, param_dict in vp.getParams(mod_dict):
            isLocal = _to_bool(param_dict.get("isLocal", False))
            if isLocal:
                continue
            #print(strStruct(param_dict, depth=4))
            name = param_dict.get("name")
            value = param_dict.get("value")
            dd["params"].append((name, value))
        for key, port_dict in vp.getPorts(mod_dict):
            #print(strStruct(port_dict, depth=4))
            name = port_dict.get("name")
            _type = port_dict.get("type")
            direction = port_dict.get("direction")
            dirstr = dir_dict.get(direction, "output")
            nettype, index_hi, index_lo, signed, elem_lo, elem_hi = parse_typestr(_type)
            if None in (index_hi, index_lo):
                rstr = ""
            else:
                rstr = f" [{index_hi}:{index_lo}]"
            dd["ports"].append((dirstr, rstr, name))
        break
    if not found:
        raise Exception(f"Could not find module {args.module} in {args.svfile}")
    return dd


def main():
    import argparse
    parser = argparse.ArgumentParser("Instantiate a SystemVerilog module")
    parser.add_argument("svfile", help="SystemVerilog file (hopefully defining a module)")
    parser.add_argument("-m", "--module", default=None, help="If the file contains multiple modules, specify the one you want to instantiate")
    parser.add_argument("-f", "--flavor", default=None, help="Instantiation look & feel")
    args = parser.parse_args()
    instantiate(args)
    return 0


if __name__ == "__main__":
    exit(main())
