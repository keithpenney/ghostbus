# A single-bus codebase
THIS_DIR := $(realpath $(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

GHOSTBUS_DIR=$(THIS_DIR)/../..

GHOSTBUS_SOURCES=$(THIS_DIR)/top.v $(THIS_DIR)/submod_foo.v $(THIS_DIR)/submod_bar.v
GHOSTBUS_TOP=top

include $(GHOSTBUS_DIR)/rules.mk

.PHONY: json
json: $(AUTOGEN_DIR)/regmap.json

.PHONY: gold
gold: $(AUTOGEN_DIR)/regmap.json
	@diff $< regmap.json.gold

.PHONY: clean
	rm -r $(AUTOGEN_DIR)
