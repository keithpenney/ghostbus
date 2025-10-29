# SystemRDL output

from memory_map import Register

class SystemRDLMaker():
    def __init__(self, memtree, drops=()):
        self.memtree = memtree
        self._drops = drops

    def write(self, filename, path="_auto", flat=False, mangle=False, short=False):
        # TODO
        print(self.templates())

    @classmethod
    def reg_template(cls, access=Register.RW, const=False):
        """If not const, assumes that a register is only writable from one side (sw & hw) and is readable from both sides"""
        assert access in (Register.READ, Register.WRITE, Register.RW), f"access = {access}"
        hw_access = Register.accessToStr(access)
        if const:
            sw_access = "r"
            # ignore 'access' when 'const' is True
            hw_access = "r"
            name = "const"
        elif access == Register.READ:
            sw_access = "rw"
            name = "ro"
        else:
            sw_access = "r"
            name = "rw"
        ss = [
            "reg reg_{}_t #(longint unsigned DW = 32, longint RESET = 32'h00000000) {{".format(name),
            "  dw = DW;",
            "  field {",
            "    sw = {};".format(sw_access),
            "    hw = {};".format(hw_access),
            "    reset = RESET;",
            "  } data[DW-1:0];",
            "};",
        ]
        return "\n".join(ss)

    @classmethod
    def templates(cls):
        ss = []
        ss.append(cls.reg_template(const=True))
        ss.append(cls.reg_template(access=Register.READ))
        ss.append(cls.reg_template(access=Register.RW))
        return "\n".join(ss)


if __name__ == "__main__":
    sm = SystemRDLMaker(None)
    sm.write(None)
