# A Verilog-writing class

import inspect
import os

class Verilogger():
    def __init__(self, debug=False):
        self._debug = debug
        self._ss = []
        self._indent_ = 0
        self._block_indent = 2
        self._else_if = self.else_if

    def write(self, filename, dest_dir=""):
        ss = self.get()
        fname = filename
        with open(os.path.join(dest_dir, fname), "w") as fd:
            fd.write(ss + "\n")
            print(f"Wrote to {fname}")
        return

    def __getitem__(self, key):
        return self._ss.__getitem__(key)

    def __setitem__(self, key, value):
        return self._ss.__setitem__(key, value)

    def __len__(self):
        return self._ss.__len__()

    def comment(self, s):
        """Add a comment within /* */ block comment delimiters.  Never adds debug trace."""
        s = "/* " + s + "*/"
        lines = s.split('\n')
        sindent = " "*self._indent
        for line in lines:
            if len(line.strip()) > 0:
                # Only indent non-empty lines
                self._ss.append(sindent + line)
            else:
                self._ss.append(line)
        return

    @staticmethod
    def _comment(s, comment=""):
        if len(comment) > 0:
            comment = " /* " + comment + " */"
        return s + comment

    def add(self, s, comment="", depth=1):
        s = self._comment(s, comment)
        if len(s) > 0 and self._debug:
            frame = inspect.stack()[depth]
            s += f" /* {frame.function}[{frame.lineno}] */"
        lines = s.split('\n')
        sindent = " "*self._indent
        for line in lines:
            if len(line.strip()) > 0:
                # Only indent non-empty lines
                self._ss.append(sindent + line)
            else:
                self._ss.append(line)
        return

    def get(self):
        return "\n".join(self._ss)

    def indent(self, times=1):
        self._indent += int(times)*self._block_indent
        return

    def dedent(self, times=1):
        self._indent -= int(times)*self._block_indent
        return

    def initial(self, comment=""):
        self.add(f"initial begin", comment=comment, depth=2)
        self.indent()
        return

    def always(self, signal, comment="", depth=2):
        self.add(f"always {signal} begin", comment=comment, depth=depth)
        self.indent()
        return

    def always_at(self, condition, comment="", depth=3):
        return self.always(f"@({condition})", comment=comment, depth=depth)

    def always_at_clk(self, clk, posedge=True, comment=""):
        if posedge:
            edge = "posedge"
        else:
            edge = "negedge"
        return self.always_at(f"{edge} {clk}", comment=comment, depth=4)

    def end(self, comment=""):
        self.dedent()
        self.add(f"end", comment=comment, depth=2)
        return

    def _if(self, condition, comment=""):
        self.add(f"if ({condition}) begin", comment=comment, depth=2)
        self.indent()
        return

    def else_if(self, condition, comment=""):
        self.dedent()
        self.add(f"end else if ({condition}) begin", comment=comment, depth=2)
        self.indent()
        return

    def _else(self, comment=""):
        self.dedent()
        self.add(f"end else begin", comment=comment, depth=2)
        self.indent()
        return

    @property
    def _indent(self):
        return self._indent_

    @_indent.setter
    def _indent(self, val):
        if int(val) < 0:
            raise Exception(f"Negative indent {val}!")
        self._indent_ = val
        return


def test_Verilogger():
    import sys
    import os
    filename = "test_tb.v"
    if len(sys.argv) > 1:
        filename = sys.argv[1]
        modname = os.path.splitext(filename)[0]
    # Verify that Verilogger creates proper syntax in a simple test
    vl = Verilogger(debug=True)
    vl.add(f"module {modname};")
    vl.initial()
    vl.add(f"$dumpfile(\"{modname}.vcd\");")
    vl.add("$dumpvars();")
    vl.end()
    vl.add("reg clk=1'b1;")
    vl.always("#5")
    vl.add("clk <= ~clk;")
    vl.end()
    vl.add("reg [3:0] cnt=0;")
    vl.always_at_clk("clk")
    vl._if("cnt == 4'hf")
    vl.add("cnt <= 4'h0;")
    vl._else()
    vl.add("cnt <= cnt+1;")
    vl.end("cnt == 4'hf")
    vl.end("@clk")
    vl.add("wire led = cnt[3];")
    vl.initial("Stimulus")
    vl.add("#320 $display(\"PASS\");")
    vl.add("$finish(0);")
    vl.end("Stimulus")
    vl.add("endmodule")
    vl.write(filename=filename)
    return 0


if __name__ == "__main__":
    test_Verilogger()
