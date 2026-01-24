import os
from slangparse import VParser
from struct_walker import strStruct

file_dir = os.path.split(__file__)[0]
verilog_dir = os.path.join(file_dir, "../verilog")
verilog_simple_dir = os.path.join(verilog_dir, "simple")

# TODO follow this example for complete codebase parsing with slang
def testVParser():
    files = os.listdir(verilog_simple_dir)
    vfiles = []
    for file in files:
        fname, ext = os.path.splitext(file)
        if ext == ".v":
            if not fname.endswith("_tb"):
                vfiles.append(os.path.join(verilog_simple_dir, file))
    vp = VParser(vfiles, top="top", sv=True)
    for key, mod_dict in vp.get_modules():
        inst_name = mod_dict["name"] # instance name (or module name?)
        body = mod_dict["body"]
        mod_name = body["name"]
        print(f"==== Module {mod_name} ====")
        for net_dict in vp.gbnetsIterator(body):
            netname = net_dict.get("name")
            rs_l, rs_r = net_dict.get("rangestr")
            if None in (rs_l, rs_r):
                rs = ""
            else:
                rs = f"[{rs_l}:{rs_r}] "
            print(f"  Net: {rs}{netname}")
        for inst_list in vp.getInstGenerator(mod_dict):
            inst_name = inst_list[1]["name"]
            mod_name = inst_list[0]
            print(f"  Instance: {inst_name} of {mod_name}")
    return True

if __name__ == "__main__":
    testVParser()
