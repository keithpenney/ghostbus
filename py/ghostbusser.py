#! python3

# GhostBus top level

import math

from yoparse import VParser
from memory_map import MemoryRegion, Register, Addrspace

def print_dict(dd, depth=-1):
    print(strDict(dd, depth=depth))


def strDict(_dict, depth=-1):
    def _strToDepth(_dict, depth=0, indent=0):
        """RECURSIVE"""
        if depth == 0:
            return []
        l = []
        sindent = " "*indent
        for key, val in _dict.items():
            if hasattr(val, 'keys'):
                l.append(f"{sindent}{key} : dict size {len(val)}")
                l.extend(_strToDepth(val, depth-1, indent+2))
            else:
                l.append(f"{sindent}{key} : {val}")
        return l
    l = []
    l.extend(_strToDepth(_dict, depth, indent=2))
    return '\n'.join(l)


class GhostBusser(VParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_map(self):
        ghostmods = []
        modtree = {}
        top_dict = self._dict["modules"]
        for module, mod_dict in top_dict.items():
            if not hasattr(mod_dict, "items"):
                continue
            # Check for instantiated modules
            modtree[module] = {}
            cells = mod_dict.get("cells")
            if cells is not None:
                for inst_name, inst_dict in cells.items():
                    modtree[module][inst_name] = inst_dict["type"]
            mr = None
            # Check for regs
            netnames = mod_dict.get("netnames")
            if netnames is not None:
                for netname, net_dict in netnames.items():
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
            memories = mod_dict.get("memories")
            if memories is not None:
                for memname, mem_dict in memories.items():
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
        print_dict(modtree)
        modtree = build_modtree(modtree)
        print_dict(modtree)
        return ghostmods

def build_modtree(dd):
    # I don't know how to do this...
    return dd

def test():
    import argparse
    parser = argparse.ArgumentParser("Ghostbus Verilog router")
    parser.add_argument("files", default=[], action="append", nargs="+", help="Source files.")
    args = parser.parse_args()
    vp = GhostBusser(args.files[0]) # Why does this end up as a double-wrapped list?
    mods = vp.get_map()
    print(f"len(mods) = {len(mods)}")
    for mod in mods:
        print(mod)
    return True

if __name__ == "__main__":
    test()
