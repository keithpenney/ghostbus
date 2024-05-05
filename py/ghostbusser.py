#! python3

# GhostBus top level

import math

from yoparse import VParser
from memory_map import MemoryRegion, Register, Addrspace

class GhostBusser(VParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_map(self):
        ghostmods = []
        top_dict = self._dict["modules"]
        for module, mod_dict in top_dict.items():
            if not hasattr(mod_dict, "items"):
                print(f"mod_dict = {mod_dict}")
                continue
            # Check for regs
            mr = None
            for netname, net_dict in mod_dict["netnames"].items():
                attr_dict = net_dict["attributes"]
                hit = False
                addr = None
                for attr, val in attr_dict.items():
                    if attr.lower().startswith("ghostbus"):
                        # Found a hit
                        hit = True
                        if attr.lower() == "ghostbus_addr":
                            addr = int(val, 2)
                if hit:
                    dw = len(net_dict['bits'])
                    aw = 0
                    reg = Register(name=netname, dw=dw, aw=aw)
                    if mr is None:
                        mr = MemoryRegion()
                    mr.add(width=aw, ref=reg, addr=addr)
            # Check for RAMs
            for memname, mem_dict in mod_dict["memories"].items():
                attr_dict = mem_dict["attributes"]
                hit = False
                addr = None
                for attr, val in attr_dict.items():
                    if attr.lower().startswith("ghostbus"):
                        # Found a hit
                        hit = True
                        if attr.lower() == "ghostbus_addr":
                            addr = int(val, 2)
                if hit:
                    dw = int(mem_dict["width"])
                    size = int(mem_dict["size"])
                    aw = math.ceil(math.log2(size))
                    reg = Register(name=netname, dw=dw, aw=aw)
                    if mr is None:
                        mr = MemoryRegion()
                    mr.add(width=aw, ref=reg, addr=addr)
            if mr is not None:
                ghostmods.append(mr)
        return ghostmods

def test():
    import argparse
    parser = argparse.ArgumentParser("Browse a JSON AST from a verilog codebase")
    parser.add_argument("files", default=[], action="append", help="Source files.")
    args = parser.parse_args()
    vp = GhostBusser(args.files)
    mods = vp.get_map()
    print(f"len(mods) = {len(mods)}")
    for mod in mods:
        print(mod)
    return True

if __name__ == "__main__":
    test()
