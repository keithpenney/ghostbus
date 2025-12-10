import re
from struct_walker import JSONBrowser, StructWalker, strStruct


def find_val_by_regex(regex, trace, val):
    if re.match(regex, val):
        return True
    return False


def find_key_by_regex(regex, trace, val):
    if len(trace) == 0:
        return False
    key = trace[-1]
    if re.match(regex, key):
        return True
    return False


def find_net(netname, trace, val):
    if len(trace) < 4:
        return False
    if val == netname:
        if (trace[-1] == "text") and (trace[-2] == "name") and (trace[-4] == "declarators"):
            return True
    return False


def load_json(filepath):
    import json
    with open(filepath, 'r') as fd:
        struct = json.load(fd)
    return struct


def collectText(dd):
    text = []
    def collect(trace, val):
        if len(trace) == 0:
            return False
        if trace[-1] == "text":
            text.append(val)
        return True
    sw = StructWalker(dd)
    sw.walk(do=collect)
    return "".join(text)


def extract_range(dd, netname):
    """
    Extracting the range from the CST:
      0. Find the net in question
         trace[-1] (key) == "text", val == net name
         trace[-2] == "name"
         trace[-3] == some int index // ignore this one
         trace[-4] == "declarators"
      1. Back up to same level as "declarators", and get val associated with key "type"
         dimensions = val.get("dimensions")
         specifier = dimensions.get("specifier")
         selector = specifier.get("selector")
         left  = selector.get("left")
         range = selector.get("range")
         right = selector.get("right")
      2. Confirm range.get("kind") == "Colon"
         Assemble text in "left" and "right"
    """
    traces = []
    def get_subtrace(trace, val):
        if len(trace) < 4:
            return False
        if (val == netname) and (trace[-1] == "text") and (trace[-2] == "name") and (trace[-4] == "declarators"):
            traces.append(trace.copy())
        return False
    sw = StructWalker(dd)
    sw.walk(do=get_subtrace)
    trace = traces[0]
    _dd = None
    _l = len(trace)
    for key in trace[:-4]:
        _dd = dd[key]
    _type = _dd.get("type")
    dimensions = _type.get("dimensions")
    specifier = dimensions[0].get("specifier")
    selector = specifier.get("selector")
    left  = selector.get("left")
    _range = selector.get("range")
    if _range.get("kind") != "Colon":
        raise Exception("This don't look right")
    right = selector.get("right")
    index_left = collectText(left)
    index_right = collectText(right)
    #print(index_left)
    #print(index_right)
    return index_left, index_right


def doExtractRange(filepath, netname):
    dd = load_json(filepath)
    extract_range(dd, netname)
    return


def TestCST(filepath):
    jb = JSONBrowser(filename)
    tt = []
    def gather_text(trace, val):
        if len(trace) == 0:
            return False
        key = trace[-1]
        if key == "text":
            tt.append(val)
    jb.walk(do=gather_text)
    print("".join(tt))
    return


def findModuleDict(filepath, module_name):
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


def testFindModuleDict(filename):
    mod_dict = findModuleDict(filename, "submod_foo")
    if mod_dict is None:
        print("None")
    else:
        print(strStruct(mod_dict))
    return


if __name__ == "__main__":
    import sys
    filename = sys.argv[1]
    #TestCST(filename)
    #doExtractRange(filename, "ext_addr")
    testFindModuleDict(filename)
