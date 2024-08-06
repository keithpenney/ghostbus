# GhostBus development makefile

THIS_DIR=.
TOP_DIR=$(THIS_DIR)/../..
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

RTEFI_CLIENT_LIST = hello.v mem_gateway.v
include $(BADGER_DIR)/rules.mk
CLEAN+=$(RTEFI_CLEAN)

I2C_DIR=$(PERIPH_DRIVERS_DIR)/i2cbridge
include $(I2C_DIR)/i2cbridge_rules.mk
I2C_CHUNK_SOURCES=$(addprefix $(I2C_DIR)/, $(filter-out dpram.v, $(I2CBRIDGE_V)))

MARBLE_DIR=$(PROJECTS_DIR)/test_marble_family
VERILOG_SOURCES=$(MARBLE_DIR)/mmc_mailbox.v \
								$(HOMELESS_DIR)/fake_dpram.v \
								$(BADGER_DIR)/tests/spi_gate.v \
								$(DSP_DIR)/dpram.v \
								$(BADGER_DIR)/mem_gateway.v \
								$(FPGA_FAMILY_DIR)/xilinx/xilinx7_clocks.v \
								$(SERIAL_IO_DIR)/gmii_to_rgmii.v \
								$(THIS_DIR)/i2c_chunk_gb.v

VERILOG_SOURCES+=$(I2C_CHUNK_SOURCES)

# Grr... I hate vpath
vpath %.v   $(DSP_DIR)

VERILOG_SOURCES+=$(RTEFI_V)

GHOSTBUS_SOURCES=$(VERILOG_SOURCES)
GHOSTBUS_TOP=$(TOP)
GHOSTBUS_IGNORES=rom
include $(GHOSTBUS_DIR)/rules.mk

ghostbus.d: $(AUTOGEN_DIR)/defs.vh
	ls $(AUTOGEN_DIR)/ghostbus* > $@

config_romx.v: $(AUTOGEN_DIR)/regmap.json
	$(PYTHON) $(BUILD_DIR)/build_rom.py --placeholder_rev -v $@ -j $< -d "Ghostbus Test"

.PHONY: magic
magic: $(AUTOGEN_DIR)/defs.vh

.PHONY: json
json: $(AUTOGEN_DIR)/regmap.json

# vivado synth without ghostbus magic
marble_nomagic.bit: $(THIS_DIR)/Marble.xdc $(THIS_DIR)/timing.xdc $(TOP_SOURCE) $(VERILOG_SOURCES)
	$(VIVADO_SYNTH) $(HARDWARE) $(TOP) "$(SYNTH_OPT)" $^

# vivado synth with ghostbus magic
marble.bit: $(THIS_DIR)/Marble.xdc $(THIS_DIR)/timing.xdc $(TOP_SOURCE) config_romx.v $(VERILOG_SOURCES) $(AUTOGEN_DIR)/defs.vh ghostbus.d
	$(VIVADO_SYNTH) $(HARDWARE) $(TOP) "$(SYNTH_OPT) -DGHOSTBUS_LIVE" $^

# This is broken
marble_top_lint: marble_top.v
	$(VERILATOR_LINT)

#include $(BUILD_DIR)/bottom_rules.mk
CLEAN += *.pyc
CLEAN += config_romx.v
CLEAN_DIRS += $(DEPDIR) $(IPX_DIR) $(AUTOGEN_DIR) __pycache__

.PHONY: clean
clean:
	$(RM) $(CLEAN)
	$(RM) $(CLEAN_DIRS)
