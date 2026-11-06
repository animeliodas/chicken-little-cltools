"""Extract the script-function table (name -> native handler) registered via 0x5daaa0.
Writes CLTools/docs/script_functions.txt"""
import os, struct
from re_helper import Img, BASE, HERE

im = Img()
REG = 0x5daaa0
rows = []
for c in im.calls_to(REG):
    # walk back over the argument pushes: push func ; preceded by push name
    pushes = []
    a = c - 1
    # decode backward window
    for start in range(c - 40, c):
        ins = list(im.md.disasm(im.d[start - BASE:c - BASE], start))
        if ins and ins[-1].address + ins[-1].size == c and all(i.mnemonic in ("push", "mov", "add", "lea", "xor") for i in ins[-3:]):
            pushes = [i for i in ins if i.mnemonic == "push"]
            break
    if len(pushes) < 2:
        continue
    try:
        func = int(pushes[-1].op_str, 16)
        name_va = int(pushes[-2].op_str, 16)
        name = im.cstr(name_va, 80)
    except ValueError:
        continue
    real = im.thunk_target(func) or func
    rows.append((name, func, real))
rows.sort()
out = os.path.join(HERE, "docs", "script_functions.txt")
with open(out, "w") as f:
    f.write("# Chicken Little script API: name, ILT thunk, native handler (Chick.exe Steam build)\n")
    for n, t, r in rows:
        f.write(f"{n:48s} 0x{t:06x}  0x{r:06x}\n")
print(len(rows), "functions ->", out)
