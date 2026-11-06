"""After a zipline glitch: keep FPS uncapped and log rope fields over time (CSV in CLTools/dump/zip_log.csv)."""
import os, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cltools.mem import Process
from cltools.bridge import Bridge
Z = int(sys.argv[1], 16); SECS = float(sys.argv[2]); FPS = int(sys.argv[3]) if len(sys.argv) > 3 else 0
p = Process(); br = Bridge(); R = Z + 0x3DC
br.set_fps(FPS)
out = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dump", "zip_log.csv"), "w")
names = {0x58: "maxsag", 0x60: "pos", 0x64: "w", 0x68: "x", 0x6c: "y", 0x70: "vx", 0x74: "vy", 0x78: "r", 0x7c: "ang",
         0x84: "px", 0x88: "py", 0x8c: "pvx", 0x90: "pvy", 0xb4: "fx", 0xb8: "fy"}
out.write("t,fps,act," + ",".join(names.values()) + "\n")
t0 = time.time(); nxt = 0
while time.time() - t0 < SECS:
    t = time.time() - t0
    vals = [p.f32(R + o) for o in names]
    out.write(f"{t:.3f},{br.b.fps:.0f},{p.u8(Z + 0x498)}," + ",".join(f"{v:.6g}" for v in vals) + "\n")
    if t >= nxt:
        print(f"{t:5.1f}s fps {br.b.fps:4.0f} act {p.u8(Z + 0x498)} " + " ".join(f"{k}={v:.3g}" for k, v in zip(names.values(), vals)))
        nxt += 2.0
    time.sleep(0.01)
br.set_fps(60)
