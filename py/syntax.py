
# Weird dependency, but I need a shared definition of register access and I don't
# want to create yet another class
from memory_map import Register
from gbexception import GhostbusInternalException

class _JSONMemoryMap():
    READ = Register.READ
    WRITE = Register.WRITE
    RW = Register.RW
    UNSPECIFIED = Register.UNSPECIFIED

    key_access = "access"
    key_aw = "addr_width"
    key_dw = "data_width"
    key_sign = "sign"
    key_base = "base_addr"

    @classmethod
    def accessToStr(cls, access):
        return Register.accessToStr(access)

    @classmethod
    def signToStr(cls, signed=False):
        if signed:
            return "signed"
        return "unsigned"

    @classmethod
    def new_entry(cls, base=0, access=READ, aw=0, dw=0, signed=False):
        entry = {
            cls.key_access: cls.accessToStr(access),
            cls.key_aw: aw,
            cls.key_sign: cls.signToStr(signed),
            cls.key_base: base,
            cls.key_dw: dw,
        }
        return entry


class ROMN(_JSONMemoryMap):
    key_regs = "regs"
    key_modules = "modules"
    key_instanceof = "instanceof"

    @classmethod
    def empty(cls):
        return {cls.key_regs: {}, cls.key_modules: {}, cls.key_instanceof: ""}

    @classmethod
    def add_module(cls, dd, module_name, module_dict):
        dd[cls.key_modules][module_name] = module_dict
        return

    @classmethod
    def add_reg(cls, dd, reg_name, reg_dict):
        dd[cls.key_regs][reg_name] = reg_dict
        return


class ROMX(_JSONMemoryMap):
    @classmethod
    def empty(cls):
        return {}

    @classmethod
    def add_module(cls, dd, module_name, module_dict):
        raise GhostbusInternalException("ROMX syntax does not track modules")
        return

    @classmethod
    def add_reg(cls, dd, reg_name, reg_dict):
        dd[reg_name] = reg_dict
        return
