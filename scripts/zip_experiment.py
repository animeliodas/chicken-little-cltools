"""Reproduce the high-FPS zipline glitch: ride zipwire N uncapped and jump before the end; log rope state."""
import math, struct, sys, time, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cltools.mem import Process
from cltools.game import Game
from cltools.bridge import Bridge
from cltools import winput

ZIP = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x9696700
JUMP_AT = float(sys.argv[2]) if len(sys.argv) > 2 else 0.88
FPS = int(sys.argv[3]) if len(sys.argv) > 3 else 0
WATCH = float(sys.argv[4]) if len(sys.argv) > 4 else 8
p = Process(); g = Game(p); br = Bridge()
R = ZIP + 0x3DC

def rope():
    return dict(pos=p.f32(R + 0x60), w=p.f32(R + 0x64), sag=p.f32(R + 0x68), v=p.f32(R + 0x6c),
                act=p.u8(ZIP + 0x498), att=hex(p.u32(g.avatar() + 0x30)))

def fmt(d): return " ".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in d.items())

base = p.u32(R + 0x80)
start = p.vec3(base)
second = p.vec3(base + 12 * 2)
dirv = [b - a for a, b in zip(start, second)]
dl = math.sqrt(sum(x * x for x in dirv)) or 1
dirv = [x / dl for x in dirv]
winput.focus(br.b.hwnd)
br.set_fps(FPS)
time.sleep(0.5)
print("fps", round(br.b.fps), "frameMs", round(br.b.frameMs, 3))
g.teleport((start[0] + dirv[0] * 0.6, start[1] + dirv[1] * 0.6 + 0.05, start[2] + dirv[2] * 0.6))
t0 = time.time()
while time.time() - t0 < 15:
    d = rope()
    if d["pos"] >= JUMP_AT:
        winput.hold("space", 0.12)
        print(f"JUMP at pos {d['pos']:.3f} fps {br.b.fps:.0f}")
        break
    time.sleep(0.002)
t1 = time.time()
last = None
while time.time() - t1 < WATCH:
    d = rope()
    s = fmt(d)
    if s != last:
        print(f"{time.time() - t1:6.2f}s {s}  player {[round(x, 2) for x in p.vec3(g.avatar() + 0x44)]}")
        last = s
    time.sleep(0.05)
if "keep" not in sys.argv: br.set_fps(60)
