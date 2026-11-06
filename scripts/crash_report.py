"""Print crash reports stored by the recorder (recordings/*.json): registers, stack, return addresses."""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))
from re_helper import Img  # noqa: E402

im = Img()
for p in sorted(glob.glob(os.path.join(HERE, "recordings", "*.json"))):
    m = json.load(open(p))
    c = m.get("crash")
    if not c:
        continue
    st = [int(x, 16) for x in c["stack"]]
    rets = []
    for i, v in enumerate(st):
        if 0x401000 <= v < 0x7A0000 and im.section_of(v) == ".text":
            # a return address is preceded by a call instruction
            prev = im.d[v - 0x400000 - 5]
            prev2 = im.d[v - 0x400000 - 6:v - 0x400000 - 4]
            if prev == 0xE8 or prev2[:1] == b"\xff":
                rets.append((i, hex(v)))
    print(os.path.basename(p), "avatar", m.get("avatar"), "rope", m["ropes"][0]["addr"] if m.get("ropes") else "-")
    print("   eip", c["eip"], c["access"], "regs", c["regs"])
    print("   stack", " ".join(x[2:] for x in c["stack"]))
    print("   return addresses", rets)
