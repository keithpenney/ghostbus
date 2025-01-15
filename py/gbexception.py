# A nearly-empty Python module providing a custom Exception to many modules

from util import enum

class GhostbusException(Exception):
    def __init__(self, s):
        super().__init__("Ghostbus ERROR: " + s)

class GhostbusNameCollision(GhostbusException):
    def __init__(self, s):
        super().__init__("Ghostbus Name Collision: " + s)

class GhostbusFeatureRequest(GhostbusException):
    def __init__(self, s):
        super().__init__("Ghostbus Unsupported Feature: " + s)

class GhostbusInternalException(Exception):
    def __init__(self, s):
        super().__init__("**** Internal Ghostbus Error (broken tool) ****: " + s)

# Here I'm starting a proper user-facing error system.  Internal errors can still be sloppy.
_errs = {
    "NO_GHOSTBUS": \
        "No ghostbus found in the codebase.  Please declare one with (* ghostbus_port=NET *) for 'NET'" \
        + " in ('clk', 'addr', 'wdata', 'rdata', 'we', etc...)."
    ,"UNSPECIFIED_DOMAIN": \
        "Ghostbus host-accessible elements (CSRs, RAMs, submods, extmods) require an explicit domain" \
        + " in cases where it is ambiguous, such as when a module declares multiple busses and has no" \
        + " implied bus (the magic bus that comes in via ports)."
        + " In such a case, every CSR, RAM, submodule, and external module needs to be disambiguated" \
        + "with the (* ghostbus_domain=\"domain_name\" *) attribute which indicates the inteded domain."
    ,"DOMAIN_COLLISION": \
        "Ghostbus bus names (domains) need to be globally unique.  This means a module in which a ghostbus" \
        + " is declared (tagged with (* ghostbus_port *) attribute) can only be instantiated once." \
        + " Similarly, busses declared in separate modules need distinct names" \
        + " via, e.g. (* ghostbus_port=\"clk\", ghostbus_domain=\"foo\" *)."
    ,"UNPARSED_FOR_LOOP": \
        "Could not find the for-loop declaration within the source code.  The tool is using a hand-rolled" \
        + " hackish solution for this task, so it can only identify the simplest constructions. " \
        + " Please dumb it down."
    ,"UNKNOWN_DOMAIN": \
        "The domain specified by the host-accessible element could not be found. " \
        + " Please ensure the domain exists and is spelled correctly."
    ,"NAME_COLLISION": \
        "Multiple host-accessible elements (CSRs, RAMs, submods, extmods) or busses ended up with the" \
        + " same name.  This is most likely due to the use of aliases (which are global by construct)."
    ,"MULTIPLE_ASSOCIATION": \
        "Multiple extmods associated with the same bus.  The association only needs be made on one net" \
        + " of the bus via (* ghostbus_branch=EXTMOD_NAME *).  Alternately, it can be made on ever net" \
        + " of the bus as long as the same 'EXTMOD_NAME' is used for all nets."
    ,"SHARED_WDATA": \
        "The 'wdata' ('dout') net cannot be shared between multiple extmod (external module) instances." \
        + " Can the other nets be shared?  What was I thinking with this one?"
    ,"MULTIPLE_ADDRESSES": \
        "Multiple explicit addresses assigned to the same object (most likely a bus)."
    ,"NO_EXTMOD_INSTANCE": \
        "External module bus declared without an instance name.  Note that declaring an extmod requires" \
        + " the attribute (* ghostbus_ext=\"NET, INSTNAME\" *) with 'NET' being the bus net (one of" \
        + " ('clk', 'addr', 'wdata', 'rdata', 'we', etc...) and 'INSTNAME' being the name which will be" \
        + " used in the memory map (and associates together all the nets of an extmod bus)."
    ,"NO_TOP_SPECIFIED": \
        "The top module needs to be specified to properly build the hierarchy."
    ,"MISSING_EXTMOD": \
        "Could not find the extmod associated with a branch bus.  Please check that the extmod exists" \
        + " (in the same module as the bus) and that the name is spelled correctly."
    ,"AW_CONFLICT": \
        "The address width of a RAM, submodule, or extmod (external module) is greater than that of the" \
        + " bus, or requires more size than remains in the memory map."
    ,"DW_CONFLICT": \
        "The data width of a RAM, CSR, submodule, or extmod (external module) is greater than that of" \
        + " the bus."
    ,"INVALID_ACCESS": \
        "A wire-type net can only have read access (read-only) while a reg-type net can have both" \
        + " read and write access (write-only, read-write, or read-only)."
}

class GhostbusNewException(Exception):
    # Add errno strings as class attributes to GhostbusNewException
    # TODO - try this out
    #_errnos = enum([key for key in _errs.keys()])
    #for errno, errstr in self._errnos.items():
    #    setattr(GhostbusNewException, errstr, errno)

    def __init__(self, errno, msg=None):
        if msg is None:
            msg = self.get_errno_msg(errno)
        super().__init__("Ghostbus ERROR: " + msg)

    @staticmethod
    def get_errno_string(errno):
        return _errnos.str(errno)

    @classmethod
    def get_errno_msg(cls, errno):
        return _errs.get(cls.get_errno_string(errno))

# Add errno strings as class attributes to GhostbusNewException
_errnos = enum([key for key in _errs.keys()])
for errstr, errno in _errnos.items():
    setattr(GhostbusNewException, errstr, errno)

