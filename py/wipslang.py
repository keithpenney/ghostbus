
import slangparse

def main():
    import argparse
    parser = argparse.ArgumentParser("Just doing some exploration with slang")
    parser.add_argument("file", help="SystemVerilog source file.")
    parser.add_argument("-t", "--top", default=None, help="Explicitly specify top module for hierarchy.")
    args = parser.parse_args()
    vp = slangparse.VParser([args.file,], top=args.top)
    vp.printSummary()
    return

if __name__ == "__main__":
    main()
