
from memory_map import bits
from ghostbusser import MemoryTree, WalkDict, JSONMaker

def test_bits():
    addr_bits = {
        # high address, nbits
        0xff : 8,
        0x0f : 4,
        0x08 : 4,
        0x07 : 3,
        0x04 : 3,
        0x03 : 2,
        0x02 : 2,
        0x01 : 1,
        (1<<10)-1 : 10,
    }
    fail = False
    for addr, bits_expected in addr_bits.items():
        bits_actual = bits(addr)
        if bits_actual != bits_expected:
            print(f"Addr 0x{addr:x} expected {bits_expected}, got {bits_actual}")
            fail = True
    if fail:
        return 1
    return 0

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
    rval = 0
    # Do it twice
    for n in range(2):
        print(f"Pass #{n+1}")
        items = []
        for key, val in top.walk():
            #print("{}".format(key), end="")
            items.append(key)
        # test the order
        print(items)
        for n in range(len(items)-1):
            if items[n+1] == "top":
                break
            if ord(items[n]) >= ord(items[n+1]):
                rval = 1
    return rval

def test_JSONMaker_flatten():
    ll = (
        ("foo.bumpy.baz.flop", 0, "flop"),
        ("foo.bumpy.baz.flop", 1, "baz_flop"),
        ("foo.bumpy.baz.flop", 2, "bumpy_baz_flop"),
        ("foo.bumpy.baz.flop", 3, "foo_bumpy_baz_flop"),
        ("foo.bumpy.baz.flop", 4, "foo_bumpy_baz_flop"),
        ("foo.bumpy.baz.flop", -1, "foo_bumpy_baz_flop"),
    )
    fails = []
    for m in range(len(ll)):
        a, n, y = ll[m]
        b, done = JSONMaker._flatten(a, n)
        if b != y:
            fails.append((a, n, y, b))
    if len(fails) > 0:
        print("FAIL:")
        for fail in fails:
            a, n, y, b = fail
            print(f"  {a}, {n} expected {y}, got {b}")
        return 1
    else:
        print("PASS")
        return 0

def test_JSONMaker_shortenNames():
    dd = {
        "foo.bar.baz": "foo_bar_baz",
        "zip.bar.baz": "zip_bar_baz",
        "foo.bar.bof": "bar_bof",
        "zip.bif.bof": "bif_bof",
        "fad.tap.hog": "hog",
        "cop.wop.pig": "pig",
    }
    nd = JSONMaker._shortenNames(dd)
    missing = []
    for short in dd.values():
        if short not in nd.keys():
            missing.append(short)
    if len(missing) > 0:
        print(f"FAIL: missing {missing}")
        print([key for key in nd.keys()])
        return 1
    print("PASS")
    return 0

def doStaticTests():
    tests = (
        test_bits,
        test_MemoryTree_orderDependencies,
        test_WalkDict,
        test_JSONMaker_flatten,
        test_JSONMaker_shortenNames,
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
