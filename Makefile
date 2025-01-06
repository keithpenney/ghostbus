# GhostBus development makefile

THIS_DIR=.
VERILOG_DIR=$(THIS_DIR)/verilog
PY_DIR=$(THIS_DIR)/py
SCRIPTS_DIR=$(THIS_DIR)/scripts
PYTHON=python3

# Safe rm
SAFERM_ROOT=$(THIS_DIR)
RM=$(SCRIPTS_DIR)/saferm.sh $(SAFERM_ROOT) -rf

.PHONY: all
all: test

.PHONY: python_tests
python_tests:
	$(MAKE) -C $(PY_DIR) clean all

# Codebase Directories
VERILOG_SIMPLE_DIR=$(VERILOG_DIR)/simple
.PHONY: verilog_simple_test
verilog_simple_test:
	$(MAKE) -C $(VERILOG_SIMPLE_DIR) clean test

VERILOG_BUSTREE_DIR=$(VERILOG_DIR)/bustree
.PHONY: verilog_bustree_test
verilog_bustree_test:
	$(MAKE) -C $(VERILOG_BUSTREE_DIR) clean test

VERILOG_GENERATE_DIR=$(VERILOG_DIR)/generate
.PHONY: verilog_generate_test
verilog_generate_test:
	$(MAKE) -C $(VERILOG_GENERATE_DIR) clean test

VERILOG_TESTS  = verilog_simple_test
VERILOG_TESTS += verilog_bustree_test
VERILOG_TESTS += verilog_generate_test

.PHONY: test
test: python_tests $(VERILOG_TESTS)

.PHONY: clean
clean:
	$(MAKE) -C $(PY_DIR) clean
	$(MAKE) -C $(VERILOG_SIMPLE_DIR) clean
	$(MAKE) -C $(VERILOG_BUSTREE_DIR) clean
	$(MAKE) -C $(VERILOG_GENERATE_DIR) clean
