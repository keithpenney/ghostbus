# Some utility functions/classes for use throughout the codebase

def strDict(_dict, depth=-1, dohash=False):
    def _strToDepth(_dict, depth=0, indent=0):
        """RECURSIVE"""
        if depth == 0:
            return []
        l = []
        sindent = " "*indent
        for key, val in _dict.items():
            hs = ""
            if dohash:
                hs = f": {id(val)}"
            if hasattr(val, 'keys'):
                l.append(f"{sindent}{key} : dict size {len(val)}{hs}")
                l.extend(_strToDepth(val, depth-1, indent+2))
            else:
                l.append(f"{sindent}{key} : {val}{hs}")
        return l
    l = []
    l.extend(_strToDepth(_dict, depth, indent=2))
    return '\n'.join(l)


def print_dict(dd, depth=-1, dohash=False):
    print(strDict(dd, depth=depth, dohash=dohash))


class enum():
    """A slightly fancy enum"""
    def __init__(self, names, base=0):
        self._strs = {}
        for n in range(len(names)):
            setattr(self, names[n], base+n)
            self._strs[base+n] = names[n]

    def __getitem__(self, item):
        return getattr(self, item)

    def str(self, val):
        return self._strs[val]

    def get(self, item):
        if hasattr(self, item):
            return getattr(self, item)
        return None

def strip_empty(ll):
    """Remove the empty items from list 'll'"""
    result = []
    for entry in ll:
        if entry != "":
            result.append(entry)
    return result

def deep_copy(dd):
    cp = {}
    for key, val in dd.items():
        if hasattr(val, "items"):
            cp[key] = deep_copy(val)
        elif hasattr(val, "copy"):
            cp[key] = val.copy()
        else:
            cp[key] = val
    return cp

def check_complete_indices(ll):
    """Ensure that the list 'll' is identical to [x for x in range(len(ll))]
    """
    llc = ll.copy()
    llc.sort()
    comp = [x for x in range(len(llc))]
    for n in range(len(llc)):
        if comp[n] != llc[n]:
            return False
    return True

