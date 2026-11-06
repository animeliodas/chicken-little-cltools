"""Print Ghidra pseudocode (from `rea decompile-all`) for addresses: py -3 scripts/dec.py 0x6aa6a0 [0x...]"""
import os, sys
D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dump", "decomp", "functions")
for a in sys.argv[1:]:
    p = os.path.join(D, f"0x{int(a, 16):x}.c")
    if not os.path.exists(p):
        print(f"// {a}: no function file"); continue
    for line in open(p, encoding="utf-8", errors="replace"):
        if line.startswith("// ") and not line.startswith("// name"):
            continue
        print(line, end="")
