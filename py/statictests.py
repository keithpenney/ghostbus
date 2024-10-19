
from ghostbusser import MemoryTree, WalkDict

def test_MemoryTree_orderDependencies():
    dd = {
        #before, after
        'e': 'f',
        'c': 'd',
        'b': 'c',
        'a': 'b',
        'd': 'e',
        'j': 'k',
        'l': 'm',
        'f': 'g',
        'k': 'l',
        'i': 'j',
        'g': 'h',
        'h': 'i',
    }
    ordered = MemoryTree._orderDependencies(dd, debug=True)
    print(ordered)
    return 0

def test_WalkDict():
    dd = {
        'F': {
            'A': {
            },
            'D': {
                'C': {
                    'B': {
                    }
                }
            },
            'E': {
            },
        },
        'K': {
            'I': {
                'G': {
                },
                'H': {
                },
            },
            'J': {
            }
        }
    }
    top = WalkDict(dd, key="top")
    items = []
    for key, val in top.walk():
        #print("{}".format(key), end="")
        items.append(key)
    # test the order
    rval = 0
    print(items)
    for n in range(len(items)-1):
        if items[n+1] == "top":
            break
        if ord(items[n]) >= ord(items[n+1]):
            rval = 1
    return rval

def doStaticTests():
    tests = (
        test_MemoryTree_orderDependencies,
        test_WalkDict,
    )
    rval = 0
    fails = []
    for n in range(len(tests)):
        test = tests[n]
        rr = test()
        if rr != 0:
            fails.append((n, rr))
        rval |= rr
    print(f"{len(tests)} tests run")
    if rval == 0:
        print("PASS")
    else:
        print("FAIL")
        for ntest, _rval in fails:
            print(f"  Test {ntest} returned {_rval}")
    return rval

if __name__ == "__main__":
    import sys
    sys.exit(doStaticTests())
