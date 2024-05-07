# GhostBus development makefile

THIS_DIR=.
VERILOG_DIR=$(THIS_DIR)/verilog
VGHOST_DIR=$(VERILOG_DIR)/ghost
PY_DIR=$(THIS_DIR)/py

PYTHON=python3

TEST_SOURCES=$(VERILOG_DIR)/foo.v $(VERILOG_DIR)/bar.v $(VERILOG_DIR)/baz.v 
.PHONY: test
test: $(TEST_SOURCES)
	$(PYTHON) $(PY_DIR)/ghostbusser.py $^

MAGIC_SOURCES=$(VGHOST_DIR)/foo.v $(VGHOST_DIR)/bar.v $(VGHOST_DIR)/baz.v 
.PHONY: magic
magic: $(MAGIC_SOURCES)
	$(PYTHON) $(PY_DIR)/ghostbusser.py $^

