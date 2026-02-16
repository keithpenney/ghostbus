# A nice use case for slang

from struct_walker import StructWalker, strStruct
from slangparse import SlangParser, parse_typestr

dir_dict = {
    "In": "input",
    "Out": "output",
    "InOut": "inout",
}


class InstanceFormatter():
    # Comma at the end of the port line or the beginning
    comma_end = True

    @classmethod
    def localparam(cls, name, val, type=None):
        if type is None:
            typestr = ""
        else:
            typestr = f"{type} "
        return f"localparam {typestr}{name} = {val};\n"

    @classmethod
    def module_line_params(cls, module_name):
        return f"{module_name} #(\n"

    @classmethod
    def instance_line_params(cls, module_name):
        # Here you can pick an instance name
        return f") {module_name}_i (\n"

    @classmethod
    def module_line_noparams(cls, module_name):
        return f"{module_name} {module_name}_i (\n"

    @classmethod
    def param_line(cls, param_name, first=False, last=False):
        comma = "," if not last else ""
        return f"  .{param_name}({param_name}){comma}\n"

    @classmethod
    def port_line(cls, port_name, direction_str, range_str, first=False, last=False):
        comma = "," if not last else ""
        return f"  .{port_name}({port_name}){comma}\n"

    @classmethod
    def end_line(cls):
        return "};\n"


class FormatterKeef(InstanceFormatter):
    @classmethod
    def port_line(cls, port_name, direction_str, range_str, first=False, last=False):
        comma = "," if not last else ""
        ss = f"  .{port_name}({port_name}){comma}"
        comment = ""
        if len(direction_str) > 0:
            comment = " // " + direction_str
            if len(range_str) > 0:
                comment = comment + " " + range_str
        return ss + comment + "\n"


class FormatterImplicit(InstanceFormatter):
    @classmethod
    def port_line(cls, port_name, direction_str, range_str, first=False, last=False):
        comma = "," if not last else ""
        return f"  .{port_name}{comma}\n"


class FormatterAligned(InstanceFormatter):
    align = 24
    port_fmt = "  .{0:<" + str(align-3) + "}({0})"
    param_fmt = port_fmt

    @classmethod
    def param_line(cls, param_name, first=False, last=False):
        comma = "," if not last else ""
        return cls.param_fmt.format(param_name) + comma + "\n"

    @classmethod
    def port_line(cls, port_name, direction_str, range_str, first=False, last=False):
        comma = "," if not last else ""
        return cls.param_fmt.format(port_name) + comma + "\n"


formatter_dict = {
    "basic": InstanceFormatter,
    "implicit": FormatterImplicit,
    "aligned": FormatterAligned,
    "keef": FormatterKeef,
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
    dd = extract(args.svfile, modname=args.module, catch_slang_errors=args.allow_errors)
    # TODO permissive string matching would be nice here
    formatter = formatter_dict.get(args.flavor, InstanceFormatter)
    ss = []
    # only flavor right now
    num_params = len(dd["params"])
    module_name = dd["module_name"]
    if num_params == 0:
        ss.append(formatter.module_line_noparams(module_name))
    else:
        for param_name, val, _type in dd["params"]:
            ss.append(formatter.localparam(param_name, val, _type))
        ss.append(formatter.module_line_params(module_name))
        ddl = len(dd["params"])
        for n in range(ddl):
            param_name, val, _type = dd["params"][n]
            first = n == 0
            last = n == ddl-1
            ss.append(formatter.param_line(param_name, first=first, last=last))
        ss.append(formatter.instance_line_params(module_name))
    comment = ""
    ddl = len(dd["ports"])
    for n in range(ddl):
        dirstr, rstr, name = dd["ports"][n]
        first = n == 0
        last = n == ddl-1
        ss.append(formatter.port_line(name, dirstr, rstr, first=first, last=last))
    ss.append(formatter.end_line())
    print("".join(ss), end="")
    return


def extract(svfile, modname=None, catch_slang_errors=False):
    common_args = [
        "-DSLANG",
        "-q",
        "--ignore-unknown-modules",
        "--timescale=1ns/1ns",
        "--allow-toplevel-iface-ports",
    ]
    ast_args = common_args
    cst_args = common_args.copy()
    astout = "deleteme_ast" if catch_slang_errors else "-"
    ast_args.extend([
        "--ast-json-source-info",
        f"--ast-json {astout}",
    ])
    cstout = "deleteme_cst" if catch_slang_errors else "-"
    cst_args.extend([
        f"--cst-json {cstout}",
    ])
    vp = SlangParser([svfile], ast_args=ast_args, cst_args=cst_args, top=None, catch_slang_errors=catch_slang_errors)
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
            _type = None
            # TODO get param type!
            dd["params"].append((name, value, _type))
        for key, port_dict in vp.getPorts(mod_dict):
            #print(strStruct(port_dict, depth=4))
            name = port_dict.get("name")
            _type = port_dict.get("type")
            kind = port_dict.get("kind")
            direction = port_dict.get("direction")
            # The _type == "<error>" case happens when we use a top-level Interface without
            # supplying the definition file or using a modport
            if direction is None or _type == "<error>":
                dirstr = ""
            else:
                dirstr = dir_dict.get(direction, "output")
            if _type is None:
                rstr = ""
            else:
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
    flavor_strs = ", ".join([x for x in formatter_dict.keys()])
    parser.add_argument("-f", "--flavor", default=None, help="Instantiation look & feel ({flavor_strs})")
    parser.add_argument("-e", "--allow_errors", default=False, action="store_true", help="Tolerate slang parsing errors")
    args = parser.parse_args()
    instantiate(args)
    return 0


if __name__ == "__main__":
    exit(main())
