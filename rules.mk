
# Usage:
#  Populate the following:
#    GHOSTBUS_SOURCES: a list of all Verilog source files to be processed by ghostbus. This can include non-ghostbus
#                      modules, so feel free to just pass all Verilog files that can be parsed by Yosys (probably not
#                      testbenches).
#    GHOSTBUS_TOP:     The module name (not filename) to use as the "root" of the module hierarchy for Ghostbus's memory
#                      map creation.  This is typically where the ghostbus itself is instantiated.
#    GHOSTBUS_IGNORES: Any instance names you'd like to leave out of the JSON memory map.  They will still be connected
#                      to the bus.  This is mostly useful for common elements found at a fixed address (e.g. config romx).
GHOSTBUS_DIR := $(realpath $(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

AUTOGEN_DIR?=_autogen
PY_DIR=$(GHOSTBUS_DIR)/py
$(AUTOGEN_DIR)/defs.vh: $(GHOSTBUS_SOURCES)
	mkdir -p $(AUTOGEN_DIR)
	$(PYTHON) $(PY_DIR)/ghostbusser.py live $^ -t $(GHOSTBUS_TOP)

ghostbus.d: $(AUTOGEN_DIR)/defs.vh
	ls $(AUTOGEN_DIR)/ghostbus* > $@

GHOSTBUS_IGNORES?=rom
ignore_args=$(addprefix --ignore ,$(GHOSTBUS_IGNORES))

$(AUTOGEN_DIR)/regmap.json: $(GHOSTBUS_SOURCES)
	mkdir -p $(AUTOGEN_DIR)
	$(PYTHON) $(PY_DIR)/ghostbusser.py json $^ -t $(GHOSTBUS_TOP) -o $@ --flat --mangle $(ignore_args)


