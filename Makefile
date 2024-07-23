# GhostBus development makefile

THIS_DIR=.
VERILOG_DIR=$(THIS_DIR)/verilog
PY_DIR=$(THIS_DIR)/py
SCRIPTS_DIR=$(THIS_DIR)/scripts

# Safe rm
SAFERM_ROOT=$(THIS_DIR)
RM=$(SCRIPTS_DIR)/saferm.sh $(SAFERM_ROOT) -rf

PYTHON=python3
VERILOG = iverilog$(ICARUS_SUFFIX) -Wall -Wno-macro-redefinition
VG_ALL = -DSIMULATE
V_TB = -Wno-timescale
AUTOGEN_DIR=_auto
VFLAGS = ${VFLAGS_$@} -I$(AUTOGEN_DIR)
VVP_FLAGS = ${VVP_FLAGS_$@}
VVP = vvp$(ICARUS_SUFFIX) -N

VERILOG_TB = $(VERILOG) $(VG_ALL) $(V_TB) ${VFLAGS} -o $@ $(filter %v, $^)
VERILOG_SIM = cd `dirname $@` && $(VVP) `basename $<` $(VVP_FLAGS)

%_tb: %_tb.v
	$(VERILOG_TB)

%.vcd: %_tb
	$(VERILOG_SIM) +vcd $(VCD_ARGS)

GHOSTBUS_TOP=foo_tb

GHOSTBUS_SOURCES=$(VERILOG_DIR)/$(GHOSTBUS_TOP).v \
							$(VERILOG_DIR)/foo.v \
							$(VERILOG_DIR)/bar.v \
							$(VERILOG_DIR)/baz.v \
							$(VERILOG_DIR)/bif.v \
							$(VERILOG_DIR)/ext.v \
							$(VERILOG_DIR)/bof.v

include $(THIS_DIR)/rules.mk

$(AUTOGEN_DIR)/mmap.vh: $(VERILOG_DIR)/foo_tb.v $(GHOSTBUS_SOURCES)
	mkdir -p $(AUTOGEN_DIR)
	$(PYTHON) $(PY_DIR)/ghostbusser.py --map $@ -t $(GHOSTBUS_TOP) $^

.PHONY: magic
magic: $(AUTOGEN_DIR)/defs.vh

.PHONY: json
json: $(AUTOGEN_DIR)/regmap.json

#VFLAGS_foo_tb=-DMANUAL_TEST
VFLAGS_foo_tb=-DGHOSTBUS_LIVE
foo_tb:  $(VERILOG_DIR)/foo_tb.v $(GHOSTBUS_SOURCES) $(AUTOGEN_DIR)/mmap.vh $(AUTOGEN_DIR)/defs.vh
	$(VERILOG_TB)

foo.vcd: foo_tb
	$(VERILOG_SIM) +vcd $(VCD_ARGS)

.PHONY: clean
clean:
	$(RM) $(AUTOGEN_DIR) foo_tb foo.vcd
