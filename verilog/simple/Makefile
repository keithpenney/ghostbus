# A single-bus codebase
THIS_DIR := $(realpath $(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

GHOSTBUS_DIR=$(THIS_DIR)/../..

GHOSTBUS_SOURCES=$(THIS_DIR)/top.v $(THIS_DIR)/submod_foo.v $(THIS_DIR)/submod_bar.v $(THIS_DIR)/submod_baz.v $(THIS_DIR)/extmod.v
GHOSTBUS_MODULES=$(THIS_DIR)/top.v $(THIS_DIR)/submod_foo.v $(THIS_DIR)/submod_bar.v $(THIS_DIR)/submod_baz.v
GHOSTBUS_TOP=top

.PHONY: all
all: test rule_check

SLANG?=
ifeq ($(strip $(SLANG)),)
GHOSTBUS_FLAGS=--live
else
GHOSTBUS_FLAGS=--live --slang
endif
include $(GHOSTBUS_DIR)/rules.mk

.PHONY: json
json: $(AUTOGEN_DIR)/regmap.json

.PHONY: gold
gold: $(AUTOGEN_DIR)/regmap.json
	@diff $< regmap.json.gold

.PHONY: parse
parse: $(GHOSTBUS_SOURCES)
	$(PYTHON) $(PY_DIR)/ghostbusser.py -t $(GHOSTBUS_TOP) $^

$(AUTOGEN_DIR)/defs.vh $(AUTOGEN_DIR)/regmap.json gb_testbench.vh: $(GHOSTBUS_SOURCES)
	mkdir -p $(AUTOGEN_DIR)
	$(PYTHON) $(PY_DIR)/ghostbusser.py $(GHOSTBUS_FLAGS) --json regmap.json --dest $(AUTOGEN_DIR) -t $(GHOSTBUS_TOP) $(ignore_args) $^ --map gb_testbench.vh

ICARUS_SUFFIX =
VERILOG = iverilog$(ICARUS_SUFFIX) -Wall -Wno-macro-redefinition
VG_ALL = -DSIMULATE
V_TB = -Wno-timescale
VFLAGS = ${VFLAGS_$@} -I$(AUTOGEN_DIR)
VERILOG_TB = $(VERILOG) $(VG_ALL) $(V_TB) ${VFLAGS} -o $@ $(filter %v, $^)
VVP = vvp$(ICARUS_SUFFIX) -N
VVP_FLAGS = ${VVP_FLAGS_$@}
VERILOG_CHECK = $(VVP) $< $(VVP_FLAGS)

VFLAGS_top_tb = -DGHOSTBUS_LIVE
top_tb: top_tb.v $(GHOSTBUS_SOURCES) gb_testbench.vh
	$(VERILOG_TB)

%_check: %_tb
	$(VERILOG_CHECK)

%.vcd: %_tb
	$(VERILOG_CHECK) +vcd

%_slang.json: %.v
	slang -DSLANG $^ --top $* --ignore-unknown-modules --timescale=1ns/1ns --allow-toplevel-iface-ports --ast-json - > $@

%_yosys.json: %.v
	yosys -q -p "verilog_defines -DYOSYS; read_verilog $^; proc" -p write_json > $@

top_slang.json: top.v submod_foo.v
top_yosys.json: top.v submod_foo.v

alt_top_slang.json: top.v
	slang -DSLANG $^ --top top --ast-json-scope top --ignore-unknown-modules --timescale=1ns/1ns --allow-toplevel-iface-ports --ast-json $@

SLANG_ARGS=-q --ignore-unknown-modules --timescale=1ns/1ns --allow-toplevel-iface-ports --ast-json-source-info --ast-json-detailed-types
complete_slang.json: $(GHOSTBUS_SOURCES)
	slang -DSLANG $^ --top top --ast-json-scope top $(SLANG_ARGS) --ast-json $@

complete_yosys.json: $(GHOSTBUS_SOURCES)
	yosys -q -p "verilog_defines -DYOSYS; read_verilog $^; proc" -p write_json > $@

cst_slang.json: $(GHOSTBUS_SOURCES)
	slang -DSLANG $^ --top top -q --ignore-unknown-modules --timescale=1ns/1ns --allow-toplevel-iface-ports --cst-json-mode simple-tokens --cst-json $@

.PHONY: test
test: top_check

CLEANS=top_tb gb_testbench.vh top.vcd

RM=rm -rf
.PHONY: clean
clean:
	$(RM) $(AUTOGEN_DIR)
	$(RM) $(CLEANS)
