# Usage:
#  Populate the following:
#    GHOSTBUS_SOURCES: a list of all Verilog source files to be processed by ghostbus. This can include non-ghostbus
#                      modules, so feel free to just pass all Verilog files that can be parsed by Yosys (probably not
#                      testbenches).
#    GHOSTBUS_TOP:     The module name (not filename) to use as the "root" of the module hierarchy for Ghostbus's memory
#                      map creation.  This is typically where the ghostbus itself is instantiated.
#    GHOSTBUS_IGNORES: Any instance names you'd like to leave out of the JSON memory map.  They will still be connected
#                      to the bus.  This is mostly useful for common elements found at a fixed address (e.g. config romx).
#    GHOSTBUS_INCLUDES: A list of directories to search for include files.
#    GHOSTBUS_MODULES: This list should only include Verilog source files which do contain ghostbus magic.  This list is
#                      used only by the optional 'rule_check' convenience target.

GHOSTBUS_DIR := $(realpath $(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

AUTOGEN_DIR?=_autogen
PY_DIR=$(GHOSTBUS_DIR)/py
PYTHON?=python3

GHOSTBUS_IGNORES?=rom
GHOSTBUS_FLAGS=--live --flat --mangle --debug
ignore_args=$(addprefix --ignore ,$(GHOSTBUS_IGNORES))
gb_includes=$(addprefix -I ,$(GHOSTBUS_INCLUDES))

$(AUTOGEN_DIR)/defs.vh $(AUTOGEN_DIR)/regmap.json: $(GHOSTBUS_SOURCES)
	mkdir -p $(AUTOGEN_DIR)
	$(PYTHON) $(PY_DIR)/ghostbusser.py $(GHOSTBUS_FLAGS) --json regmap.json --dest $(AUTOGEN_DIR) -t $(GHOSTBUS_TOP) $(gb_includes) $(ignore_args) $^

ghostbus.d: $(AUTOGEN_DIR)/defs.vh
	ls $(AUTOGEN_DIR)/ghostbus* > $@

.PHONY: rule_check
rule_check: $(GHOSTBUS_MODULES)
	$(PYTHON) $(PY_DIR)/rule_check.py $^
