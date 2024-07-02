# GhostBus development makefile

THIS_DIR=.
VERILOG_DIR=$(THIS_DIR)/verilog
VGHOST_DIR=$(VERILOG_DIR)/ghost
PY_DIR=$(THIS_DIR)/py

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

TOP=foo
TEST_SOURCES=$(VERILOG_DIR)/foo.v $(VERILOG_DIR)/bar.v $(VERILOG_DIR)/baz.v
.PHONY: test
test: $(TEST_SOURCES)
	$(PYTHON) $(PY_DIR)/ghostbusser.py $^ -t $(TOP)

MAGIC_SOURCES=$(VGHOST_DIR)/foo.v $(VGHOST_DIR)/bar.v $(VGHOST_DIR)/baz.v $(VGHOST_DIR)/bif.v
.PHONY: magic
magic: $(MAGIC_SOURCES)
	$(PYTHON) $(PY_DIR)/ghostbusser.py $^ -t $(TOP)

$(AUTOGEN_DIR)/defs.vh: $(MAGIC_SOURCES)
	$(PYTHON) $(PY_DIR)/ghostbusser.py $^ -t $(TOP)

#VFLAGS_foo_tb=-DMANUAL_TEST
VFLAGS_foo_tb=-DGHOSTBUS_LIVE
foo_tb: $(AUTOGEN_DIR)/defs.vh $(VERILOG_DIR)/foo_tb.v $(MAGIC_SOURCES)
	$(VERILOG_TB)

foo.vcd: foo_tb
	$(VERILOG_SIM) +vcd $(VCD_ARGS)
