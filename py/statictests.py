
from yoparse import get_modname, block_inst, autogenblk, _matchForLoop, decomment, _matchKw
from memory_map import bits
from ghostbusser import MemoryTree, WalkDict
from jsonmap import JSONMaker
from util import check_complete_indices, identical_or_none, check_consistent_offset


def test_get_modname():
    td = {
        r"$paramod$8b3f6b5606276ea5c166ba4745cb6215a6ec04e3\axi_lb" : "axi_lb",
        r"$paramod\nco_control\NDACS=s32'00000000000000000000000000000011" : "nco_control",
    }
    fail = False
    for ss, name in td.items():
        modname = get_modname(ss)
        if modname != name:
            print(f"get_modname({ss}) = {modname} != {name}")
            fail = True
    if fail:
        return 1
    return 0


def test_block_inst():
    td = {
        # yostr: (gen_block, inst_name, index)
        "gen_foo.inst_bar": ("gen_foo", "inst_bar", None),
        "gen_foo[3].inst_bar": ("gen_foo", "inst_bar", 3),
        "inst_foo": (None, None, None),
        r"$paramod$8b3f6b5606276ea5c166ba4745cb6215a6ec04e3\axi_lb" : (None, None, None),
        r"$0\baz_generator.top_baz": (None, None, None),
        r"$0\top_reg[7:0]": (None, None, None),
        r"$0\foo_generator[3].top_foo_n[3:0]": (None, None, None),
    }
    fail = False
    for ss, expret in td.items():
        ret = block_inst(ss)
        for n in range(len(ret)):
            thisfail = False
            if ret[n] != expret[n]:
                fail = True
                thisfail = True
            if thisfail:
                print(f"block_inst({ss}) = {ret} != {expret}")
    if fail:
        return 1
    return 0


def test_autogenblk():
    td = {
        "genblk0": True,
        "genblk2": True,
        "genblk4321": True,
        "genblk": False,
        "foo": False,
    }
    fail = False
    for ss, expected in td.items():
        if autogenblk(ss) != expected:
            print(f"FAIL: autogenblk({ss}) != {expected}")
            fail = True
    if fail:
        return 1
    return 0


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


def test__matchForLoop():
    dd = {
        # loop_string: (loop_index, start, comp_op, comp_val, inc_op+inc_val)
        # loop_string: (loop_index, start, compval, inc_val)
        "generate for (N=0;N<4;N=N+1)": ("N", "0", "<", "4", "+1"),
        "generate\r\n  for (N=0;N<4;N=N+1)": ("N", "0", "<", "4", "+1"),
        # Missing 'generate'
        "for (N=0;N<4;N=N+1)": (None, None, None, None, None),
        "generate for (N = 0; N < 4; N = N + 1)": ("N", "0", "<", "4", "+1"),
        "generate for (MY_LOOP_VAR=(SOME_THIS_NUMBER>>2); MY_LOOP_VAR>0; MY_LOOP_VAR=MY_LOOP_VAR-1)": ("MY_LOOP_VAR", "(SOME_THIS_NUMBER>>2)", ">", "0", "-1"),
        "generate for (boop; bop; floop)": (None, None, None, None, None),
        # Make sure we get the last match
        "generate for (N=0;N<4;N=N+1) generate for (M=1;M<M_MAX;M=M+M_INC)": ("M", "1", "<", "M_MAX", "+M_INC"),
        # TODO - Handle generates using the old "genvar" format
        #"genvar e;\nwire [254:1] evStrobe;\nassign ppsMarker = evStrobe[EVCODE_SECONDS_MARKER];\nfor (e = 1 ; e <= 254 ; e = e + 1) begin : evstr": (),
    }
    fail = False
    for ss, exp in dd.items():
        res = _matchForLoop(ss)
        thisfail = False
        for n in range(len(res)):
            if res[n] != exp[n]:
                thisfail = True
                fail = True
        if thisfail:
            print(f"FAIL: _matchForLoop({ss}) = {res} != {exp}")
    if fail:
        return 1
    return 0


def test_check_complete_indices():
    dd = (
        # Indices, is_complete
        ([4, 5, 3, 2, 1, 0], True),
        ([4, 1, 3, 2, 0], True),
        ([1, 3, 2, 4], False),
        ([0], True),
        (["0"], False),
        ([1], False),
    )
    fail = False
    for ll, exp in dd:
        res = check_complete_indices(ll)
        if res != exp:
            print(f"FAIL: check_complete_indices({ll}) = {res} != {exp}")
            fail = True
    if fail:
        return 1
    return 0


def test_decomment():
    dd = (
        ("hello", "hello"),
        ("hello // I'm a comment", "hello "),
        ("hello // I'm a comment\nwith more lines", "hello \nwith more lines"),
        ("hello /* I'm a block comment */ there", "hello  there"),
        (" generate // do this generate thing\n  for (N=0; N<8; N=N+1): branch // this is my branch",
         " generate \n  for (N=0; N<8; N=N+1): branch "),
    )
    fail = False
    for ss, exp in dd:
        res = decomment(ss)
        if res != exp:
            print(f"FAIL: decomment({ss}) = {res} != {exp}")
            fail = True
    if fail:
        return 1
    return 0

def test_identical_or_none():
    tests = (
        ((None,), True),
        ((None, None), True),
        ((1,), True),
        (("foo",), True),
        (("foo", "foo"), True),
        (("foo", None), True),
        ((None, "foo"), True),
        ((0, 0, 0, None, None, 0), True),
        ((None, 0, 0, None, None, 0), True),
        ((1, 0, 0, None, None, 0), False),
        ((0, 1, 0, 0, 0, 0), False),
        ((1, 1, 1, 1, 1, "bar"), False),
        ((1, 1, 1, 1, 1, None), True),
    )
    fails = 0
    for inlist, expected in tests:
        result = identical_or_none(inlist)
        if result != expected:
            print(f"FAIL: {inlist} expected {expected}, got {result}")
            fails += 1
    return fails


def test_check_consistent_offset():
    goodies = (
        [n for n in range(10)],
        [2*n for n in range(10)],
        [100 + 31*n for n in range(10)],
    )
    baddies = (
        (0, 0, 1, 2, 3),
        (10, 20, 30, 50),
        (0, 2, 1, 3),
    )
    fails = 0
    for goody in goodies:
        if not check_consistent_offset(goody):
            print(f"FAIL: {baddy} has consistent offset")
            fails += 1
    for baddy in baddies:
        if check_consistent_offset(baddy):
            print(f"FAIL: {baddy} has inconsistent offset")
            fails += 1
    if fails > 0:
        print(f"FAIL: {fails}/{len(goodies) + len(baddies)} failed.")
        return 1
    return 0


def test__matchKw():
    tests = (
        ("foo", None),
        ("regval", None),
        ("reg_addr", None),
        ("reg addr", "reg"),
        (" reg [15:0] reg_addr", "reg"),
        ("\twire [15:0] reg_addr", "wire"),
        ("0] reg_add", None),
        ("input_baz", None),
        (" outputt", None),
        (" output", "output"),
        ("output", "output"),
        ("\toutput.", "output"),
        ("\treg.", "reg"),
        ("wire", "wire"),
        ("wire.", "wire"),
        ("wire_", None),
        ("_wire", None),
        ("\twire", "wire"),
        ("     wire", "wire"),
        ("wire foo baz", "wire"),
    )
    fails = 0
    for arg, expected in tests:
        result = _matchKw(arg)
        if result != expected:
            print(f"FAIL: _matchKw({arg}) expected {expected}, got {result}")
            fails += 1
    return fails


def doStaticTests():
    tests = (
        test_get_modname,
        test_block_inst,
        test_autogenblk,
        test_bits,
        test_MemoryTree_orderDependencies,
        test_WalkDict,
        test_JSONMaker_flatten,
        test_JSONMaker_shortenNames,
        test__matchForLoop,
        test_check_complete_indices,
        test_decomment,
        test_identical_or_none,
        test__matchKw,
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
