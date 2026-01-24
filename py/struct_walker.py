# Convenient struct (nested dict/list) browsing/walking

import json
import os

DEBUG_WALK = False

def strStruct(struct, depth=-1):
    sb = StructWalker(struct)
    return sb.strToDepth(depth=depth, partSelect=None)


class StructWalker():
    _class_string_ = "StructWalker"
    def __init__(self, d):
        self._struct = d

    def _strToDepth(self, item, depth=0, indent=0):
        """RECURSIVE"""
        if depth == 0:
            return []
        l = []
        sindent = " "*indent
        if hasattr(item, "items"):
            _iter = item.items()
        else:
            _iter = enumerate(item)
        for key, val in _iter:
            if hasattr(val, 'keys'):
                l.append(f"{sindent}{key} : dict size {len(val)}")
                l.extend(self._strToDepth(val, depth-1, indent+2))
            elif hasattr(val, "__len__") and not hasattr(val, "lower"): # list
                l.append(f"{sindent}{key} : list size {len(val)}")
                l.extend(self._strToDepth(val, depth-1, indent+2))
            else:
                l.append(f"{sindent}{key} : {val}")
        return l

    def _get_class_string(self):
        return "StructWalker()"

    def strToDepth(self, depth=0, partSelect=None):
        _d = self.selectPart(partSelect)
        l = [self._get_class_string()]
        l.extend(self._strToDepth(_d, depth, indent=2))
        return '\n'.join(l)

    def __str__(self):
        return self.strToDepth(1)

    def __repr__(self):
        return self.__str__()

    def selectPart(self, partSelect = None):
        _d = self._struct
        if partSelect is not None:
            parts = partSelect.split('.')
            for nselect in range(len(parts)):
                select = parts[nselect]
                matched = False
                if hasattr(_d, "items"):
                    # It's a dict
                    try:
                        _d = _d[select]
                        matched = True
                    except KeyError:
                        pass
                else:
                    # It's a list?
                    select = int(select)
                    try:
                        _d = _d[select]
                        matched = True
                    except IndexError:
                        pass
                if not matched:
                    raise Exception(f"Failed to match part-select at: {select}")
        return _d

    def search(self, target_key):
        """Search the dict structure for all keys that match 'target_key' and return as a nested dict."""
        hitlist = []
        def _do(trace, val):
            if trace[-1] == target_key:
                tstr = '.'.join(trace)
                hitlist.append((tstr, val))
        self.walk(_do)
        return hitlist

    def walk(self, do = lambda trace, val : None, depth=-1):
        # I have to do this dumb thing where I actually
        # walk the generator and discard everything or
        # else the function exits early and doesn't walk?
        _iter = self._walk(self._struct, [], do, depth=depth)
        for x in _iter:
            pass
        return True

    def iter_walk(self, do = lambda trace, val : False, depth=-1, debug=False):
        return self._walk(self._struct, [], do, depth=depth, debug=debug)

    @classmethod
    def _walk(cls, td, trace = [], do = lambda trace, val : False, depth=-1, debug=False):
        """Depth-first recursive walk"""
        if depth == 0:
            return True
        rval = do(trace, td)
        if debug:
            print(f"  ---> rval = {rval}. trace = {trace}. len(td) = {len(td)}")
        key = None if len(trace) == 0 else trace[-1]
        if rval:
            yield (key, td)
        if hasattr(td, "items"):
            _iter = td.items()
        else:
            _iter = enumerate(td)
        for key, val in _iter:
            if DEBUG_WALK:
                if hasattr(val, "lower") or hasattr(val, "imag"):
                    vstr = str(val)
                else:
                    vstr = "[] or {}"
                print(f"{trace} {key} : {vstr}")
            trace.append(key)   # Add key
            if hasattr(val, 'items') or (hasattr(val, "__len__") and not hasattr(val, "lower")):
                yield from cls._walk(val, trace, do, depth=depth-1) # When this returns, we are done with this dict/list
            else:
                rval = do(trace, val)
                if rval:
                    yield (key, val)
            trace.pop() # So we can pop the key from the trace and continue the loop
        return True


class JSONBrowser(StructWalker):
    def __init__(self, filename):
        self._filename = filename
        self.valid = self.load()

    def load(self):
        with open(self._filename, 'r') as fd:
            struct = json.load(fd)
        self._struct = struct
        return True

    def _get_class_string(self):
        return "JSONBrowser({})".format(os.path.split(self._filename)[-1])


def doBrowse(argv):
    import argparse
    parser = argparse.ArgumentParser(description="Browse a JSON file interactively")
    parser.add_argument('filename', default=-1, help="The JSON file to parse.")
    parser.add_argument('depth', default=-1, help="The depth of a nested dict to show (-1 = All).", nargs='?')
    parser.add_argument('-s', '--select', default=None, help="A hierarchical dereference to select and use as the top when printing.")
    args = parser.parse_args()
    filename = args.filename
    depth = int(args.depth)
    partSelect = args.select
    jp = JSONBrowser(filename)
    if not jp.valid:
        return False
    print(jp.strToDepth(depth, partSelect))
    return True


if __name__ == "__main__":
    import sys
    doBrowse(sys.argv)
