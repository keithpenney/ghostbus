# GhostBus development makefile

THIS_DIR=.
VERILOG_DIR=$(THIS_DIR)/verilog
PY_DIR=$(THIS_DIR)/py

PYTHON=python3

TEST_SOURCES=$(VERILOG_DIR)/foo.v $(VERILOG_DIR)/bar.v $(VERILOG_DIR)/baz.v 
.PHONY: test
test:
	$(PYTHON) $(PY_DIR)/ghostbusser.py $(TEST_SOURCES)
