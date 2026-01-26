import os
from slangparse import VParser as slangVParser
from yoparse import VParser as yosysVParser
from struct_walker import strStruct

file_dir = os.path.split(__file__)[0]
verilog_dir = os.path.join(file_dir, "../verilog")
verilog_simple_dir = os.path.join(verilog_dir, "simple")

SLANG=False
def testVParser():
    files = os.listdir(verilog_simple_dir)
    vfiles = []
    for file in files:
        fname, ext = os.path.splitext(file)
        if ext == ".v":
            if not fname.endswith("_tb"):
                vfiles.append(os.path.join(verilog_simple_dir, file))
    if SLANG:
        VParser = slangVParser
    else:
        VParser = yosysVParser
    vp = VParser(vfiles, top="top")
    for mod_hash, mod_dict in vp.get_modules():
        #print("==============================")
        #print(strStruct(mod_dict, 2))
        mod_name = vp.get_module_name(mod_dict, mod_hash=mod_hash)
        print(f"==== Module {mod_name} ====")
        for net_dict in vp.gbnetsIterator(mod_dict):
            netname = net_dict.get("name")
            rs_l, rs_r = net_dict.get("rangestr")
            if None in (rs_l, rs_r):
                rs = ""
            elif (rs_l == "0" and rs_r == "0"):
                rs = ""
            else:
                rs = f"[{rs_l}:{rs_r}] "
            print(f"  Net: {rs}{netname}")
        for inst_dict in vp.get_instances(mod_dict):
            #print("==============================")
            #print(strStruct(inst_dict, 3))
            inst_name = vp.get_instance_name(inst_dict)
            #mod_name = inst_list[0]
            mod_name = vp.get_instance_module_name(inst_dict)
            print(f"  Instance: {inst_name} of {mod_name}")
    return True

if __name__ == "__main__":
    testVParser()
