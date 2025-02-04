# Some utility functions/classes for use throughout the codebase

DEBUG_BRANCH = False # Set to True for debug branches
def feature_print(*args, **kwargs):
    if DEBUG_BRANCH:
        print(*args, **kwargs)
    return

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
        self._strs = []
        self._offset = base
        for n in range(len(names)):
            setattr(self, names[n], base+n)
            self._strs.append(names[n])
        self._items = False

    def __getitem__(self, item):
        return getattr(self, item)

    def __iter__(self):
        self._ix = 0
        #self._items = False
        return self

    def items(self):
        self._ix = 0
        self._items = True
        return self

    def __next__(self):
        if self._ix >= len(self._strs):
            self._items = False
            raise StopIteration
        ss = self._strs[self._ix]
        self._ix += 1
        if self._items:
            return (ss, getattr(self, ss))
        return getattr(self, ss)

    def str(self, val):
        return self._strs[val-self._offset]

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

def identical(ll):
    """Return True if all items in list 'll' are the same"""
    if len(ll) <= 1:
        return True
    l0 = ll[0]
    for l in ll[1:]:
        if l != l0:
            return False
    return True

def identical_or_none(ll):
    """Return True if all items in list 'll' are the same or None"""
    if len(ll) <= 1:
        return True
    l0 = ll[0]
    for l in ll[1:]:
        if l is not None:
            if l0 is None:
                l0 = l
            elif l != l0:
                return False
    return True

def get_non_none(ll):
    """Return the first instance in list ll that is not None (or None)."""
    for l in ll:
        if l is not None:
            return l
    return None

def check_consistent_offset(ll):
    offset = None
    last_item = ll[0]
    for item in ll[1:]:
        this_offset = item-last_item
        if offset is None:
            offset = this_offset
        elif offset != this_offset:
            return False
        last_item = item
    return True



