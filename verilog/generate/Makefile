# A codebase with generate-if and generate-for blocks
THIS_DIR := $(realpath $(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

GHOSTBUS_DIR=$(THIS_DIR)/../..

GHOSTBUS_SOURCES=$(THIS_DIR)/top.v $(THIS_DIR)/submod_foo.v $(THIS_DIR)/submod_bar.v $(THIS_DIR)/submod_baz.v
GHOSTBUS_TOP=top

include $(GHOSTBUS_DIR)/rules.mk

.PHONY: json
json: $(AUTOGEN_DIR)/regmap.json

.PHONY: gold
gold: $(AUTOGEN_DIR)/regmap.json
	@diff $< regmap.json.gold

.PHONY: parse
parse: $(GHOSTBUS_SOURCES)
	$(PYTHON) $(PY_DIR)/ghostbusser.py -t $(GHOSTBUS_TOP) $^

$(AUTOGEN_DIR)/defs.vh $(AUTOGEN_DIR)/regmap.json memory_map.vh: $(GHOSTBUS_SOURCES)
	mkdir -p $(AUTOGEN_DIR)
	$(PYTHON) $(PY_DIR)/ghostbusser.py --live --json regmap.json --dest $(AUTOGEN_DIR) -t $(GHOSTBUS_TOP) --flat --mangle $(ignore_args) $^ --map memory_map.vh

ICARUS_SUFFIX =
VERILOG = iverilog$(ICARUS_SUFFIX) -Wall -Wno-macro-redefinition
VG_ALL = -DSIMULATE
V_TB = -Wno-timescale
VFLAGS = ${VFLAGS_$@} -I$(AUTOGEN_DIR)
VERILOG_TB = $(VERILOG) $(VG_ALL) $(V_TB) ${VFLAGS} -o $@ $(filter %v, $^)
VVP = vvp$(ICARUS_SUFFIX) -N
VVP_FLAGS = ${VVP_FLAGS_$@}
VERILOG_CHECK = $(VVP) $< $(VVP_FLAGS)

# memory_map.vh

VFLAGS_top_tb = -DGHOSTBUS_LIVE
top_tb: top_tb.v $(GHOSTBUS_SOURCES) memory_map.vh
	$(VERILOG_TB)

VVP_FLAGS_top_check=+vcd
%_check: %_tb
	$(VERILOG_CHECK)

VFLAGS_top_tb_manual = -DHAND_ROLLED
top_tb_manual: top_tb.v $(GHOSTBUS_SOURCES)
	$(VERILOG_TB)

top_check_manual: top_tb_manual
	$(VERILOG_CHECK)

.PHONY: test
test: top_check_manual

CLEANS=top_tb memory_map.vh

RM=rm -rf
.PHONY: clean
clean:
	$(RM) $(AUTOGEN_DIR)
	$(RM) $(CLEANS)
