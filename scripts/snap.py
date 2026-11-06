"""Usage: py -3 scripts/snap.py [keys...]  -> presses keys in game (key, key:hold_s, waitN) then saves screens/last.png"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cltools.bridge import Bridge
from cltools import winput
from PIL import Image

br = Bridge()
winput.focus(br.b.hwnd)
for k in sys.argv[1:]:
    if k.startswith("wait"):
        time.sleep(float(k[4:]))
    elif ":" in k:
        key, sec = k.split(":")
        winput.hold(key, float(sec))
    else:
        winput.tap(k)
time.sleep(0.3)
p = br.screenshot()
out = os.path.join(os.path.dirname(p), "last.png")
Image.open(p).save(out)
os.remove(p)
print(f"fps={br.b.fps:.1f} frame={br.b.frame} -> {out}")
