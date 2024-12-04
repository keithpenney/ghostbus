# Python tool tests outside of Python scope
THIS_DIR := $(realpath $(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
PY_DIR=$(THIS_DIR)

PYTHON = python3

VERILOG = iverilog$(ICARUS_SUFFIX) -Wall -Wno-macro-redefinition -Wno-timescale
VG_ALL = -DSIMULATE
VERILOG_TB = $(VERILOG) $(VG_ALL) -o $@ $(filter %v, $^)
VVP = vvp$(ICARUS_SUFFIX) -N
VVP_FLAGS = ${VVP_FLAGS_$@}
VERILOG_CHECK = $(VVP) $< $(VVP_FLAGS)

TESTFILE=test

.PHONY: all
all: statictests mem_map_test $(TESTFILE)_check

# Python Tests
.PHONY: statictests
statictests:
	$(PYTHON) $(PY_DIR)/statictests.py

.PHONY: mem_map_test
mem_map_test:
	$(PYTHON) $(PY_DIR)/memory_map.py

$(TESTFILE)_tb.v: $(PY_DIR)/verilogger.py
	$(PYTHON) $< $(TESTFILE)_tb.v

$(TESTFILE)_tb: $(TESTFILE)_tb.v
	$(VERILOG_TB)

.PHONY: $(TESTFILE)_check
$(TESTFILE).vcd $(TESTFILE)_check: $(TESTFILE)_tb
	$(VERILOG_CHECK)

CLEANS  = $(TESTFILE).v
CLEANS += $(TESTFILE)_tb.v
CLEANS += $(TESTFILE)_tb
CLEANS += $(TESTFILE).vcd

clean:
	rm -rf $(CLEANS)
