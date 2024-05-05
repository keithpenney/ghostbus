#! /usr/bin/python3

# Browse a yosys-parsed verilog file as a dict

if __name__ == "__main__":
    import sys
    import instantiator
    instantiator.doBrowse(sys.argv)
