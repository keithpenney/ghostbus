# Helpful Ghostbus rule checker to reduce gotchas

import os
from yoparse import VParser, decomment


def warn(msg):
    print(f"WARNING: {msg}")
    return


def collect_macros(filepath):
    text = ""
    with open(filepath, 'r') as fd:
        text = fd.read()
    text = decomment(text)
    macros = []
    inmacro = False
    macro = ""
    # This will catch custom macros as well as things like `ifdef, `define, `else, `endif, etc.
    for n in range(len(text)):
        cc = text[n]
        if inmacro:
            if not (cc.isalnum() or cc == "_"):
                inmacro = False
                macros.append(macro)
                macro = ""
            else:
                macro += cc
        else:
            if cc == "`":
                inmacro = True
    # Only include macros starting with "GHOSTBUS"
    gmacs = []
    for macro in macros:
        if macro.startswith("GHOSTBUS"):
            gmacs.append(macro)
    return gmacs


def check_file(filepath):
    if not os.path.exists(filepath):
        raise Exception("Could not find file: \"{filepath}\"")
    # Get module name via yosys (rather than hand-parsing)
    vp = VParser((filepath,))
    modname = vp.getTopName()
    # Get macros from hand-parsing (yosys don't play at the token level)
    macros = collect_macros(filepath)
    pfx = f"GHOSTBUS_{modname}"
    rval = 0
    # Check for mandatory macro name
    if pfx not in macros:
        warn(f"{filepath}: missing mandatory \"{pfx}\" macro.")
        rval += 1
    # Check that all macros start with the mandatory prefix
    for macro in macros:
        if macro in (pfx, "GHOSTBUSPORTS"):
            continue
        if not macro.startswith(f"{pfx}_"):
            warn(f"{filepath}: misplaced (or mis-spelled) macro \"{macro}\" which does not begin with \"`{pfx}_\"")
            rval += 1
    return rval


def doRuleCheck():
    import argparse
    parser = argparse.ArgumentParser("A Ghostbus gotcha-killer.")
    parser.add_argument("files",    default=[], action="append", nargs="+", help="Source files.")
    args = parser.parse_args()
    print("NOTE! This script currently expects ALL files handed to it to be Ghostbus modules (not standard Verilog files with no ghostbus usage)")
    rval = 0
    for file in args.files[0]:
        rval += check_file(file)
    if rval == 0:
        print("PASS")
        return 0
    return 1


if __name__ == "__main__":
    exit(doRuleCheck())
