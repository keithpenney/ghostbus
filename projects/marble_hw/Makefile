# GhostBus development makefile

THIS_DIR=.
TOP_DIR=$(THIS_DIR)/../../
# NOTE! Simlink this!
BEDROCK_DIR=$(TOP_DIR)/bedrock

include $(BEDROCK_DIR)/dir_list.mk
include $(BUILD_DIR)/top_rules.mk

HARDWARE=marble

PY_DIR=$(TOP_DIR)/py
SCRIPTS_DIR=$(TOP_DIR)/scripts

# Safe rm
SAFERM_ROOT=$(THIS_DIR)
RM=$(SCRIPTS_DIR)/saferm.sh $(SAFERM_ROOT) -rf

AUTOGEN_DIR=_auto
VFLAGS_DEP += $(AUTOGEN_DIR)

TOP=marble_top
TOP_SOURCE=$(THIS_DIR)/$(TOP).v

RTEFI_CLIENT_LIST = hello.v lb_gateway.v
include $(BADGER_DIR)/rules.mk

MARBLE_DIR=$(PROJECTS_DIR)/test_marble_family
VERILOG_SOURCES=$(MARBLE_DIR)/mmc_mailbox.v \
								$(HOMELESS_DIR)/fake_dpram.v \
								$(BADGER_DIR)/tests/spi_gate.v \
								$(DSP_DIR)/dpram.v \
								$(BADGER_DIR)/mem_gateway.v \
								$(FPGA_FAMILY_DIR)/xilinx/xilinx7_clocks.v \
								$(SERIAL_IO_DIR)/gmii_to_rgmii.v

# Grr... I hate vpath
vpath %.v   $(DSP_DIR)

VERILOG_SOURCES+=$(RTEFI_V)

$(AUTOGEN_DIR)/defs.vh: $(TOP_SOURCE) $(VERILOG_SOURCES)
	mkdir -p $(AUTOGEN_DIR)
	$(PYTHON) $(PY_DIR)/ghostbusser.py live $^ -t $(TOP)

ghostbus.d: $(AUTOGEN_DIR)/defs.vh
	ls $(AUTOGEN_DIR)/ghostbus* > $@

$(AUTOGEN_DIR)/mmap.vh: $(VERILOG_DIR)/foo_tb.v $(VERILOG_SOURCES)
	mkdir -p $(AUTOGEN_DIR)
	$(PYTHON) $(PY_DIR)/ghostbusser.py map $^ -t $(TOP) -o $@

.PHONY: magic
magic: $(AUTOGEN_DIR)/defs.vh

# FIXME
VFLAGS_foo_tb=-DGHOSTBUS_LIVE
foo_tb:  $(VERILOG_DIR)/foo_tb.v $(VERILOG_SOURCES) $(AUTOGEN_DIR)/mmap.vh $(AUTOGEN_DIR)/defs.vh
	$(VERILOG_TB)

# vivado synth without ghostbus magic
marble_nomagic.bit: $(THIS_DIR)/Marble.xdc $(THIS_DIR)/timing.xdc $(TOP_SOURCE) $(VERILOG_SOURCES)
	$(VIVADO_SYNTH) $(HARDWARE) $(TOP) "$(SYNTH_OPT)" $^

# vivado synth with ghostbus magic
marble.bit: $(THIS_DIR)/Marble.xdc $(THIS_DIR)/timing.xdc $(TOP_SOURCE) $(VERILOG_SOURCES) $(AUTOGEN_DIR)/defs.vh ghostbus.d
	$(VIVADO_SYNTH) $(HARDWARE) $(TOP) "$(SYNTH_OPT) -DGHOSTBUS_LIVE" $^

marble_top_lint: marble_top.v
	$(VERILATOR_LINT)


.PHONY: clean
clean:
	$(RM) $(AUTOGEN_DIR)
