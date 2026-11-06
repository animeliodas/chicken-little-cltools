"""Glitch a zipline, wait T seconds uncapped, touch it again and log what happens."""
import math, os, struct, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cltools.mem import Process
from cltools.game import Game
from cltools.bridge import Bridge
Z = int(sys.argv[1], 16); WAIT = float(sys.argv[2]); TOUCH_T = float(sys.argv[3]) if len(sys.argv) > 3 else 0.05
here = os.path.dirname(os.path.abspath(__file__))
subprocess.run([sys.executable, os.path.join(here, "zip_experiment.py"), hex(Z), "0.88", "0", "0.3"], capture_output=True)
p = Process(); g = Game(p); br = Bridge(); R = Z + 0x3DC
br.set_fps(0)
t0 = time.time()
while time.time() - t0 < WAIT:
    time.sleep(0.05)
y = p.f32(R + 0x6c)
base = p.u32(R + 0x80); cnt = p.i32(R + 0xc)
a = p.vec3(base); b = p.vec3(base + 12 * (cnt - 1))
tp = tuple(a[k] + (b[k] - a[k]) * TOUCH_T for k in range(3))
lvl0 = p.u32(p.u32(g.game() + 0x60c) + 4)
print(f"after {WAIT}s: rope y={y:.3g} r={p.f32(R+0x78):.3g}  touching at t={TOUCH_T} {tuple(round(v,2) for v in tp)}  level={lvl0}")
g.teleport((tp[0], tp[1] - 0.3, tp[2]))
t1 = time.time(); last = None
while time.time() - t1 < 6:
    try:
        av = g.avatar()
        s = (f"att={p.u32(av + 0x30):#x} pos={[float('%.3g' % v) for v in p.vec3(av + 0x44)]} "
             f"phys={[float('%.3g' % v) for v in p.vec3(av + 0x12ac)]} rider={p.f32(R+0x60):.3g} w={p.f32(R+0x64):.3g} "
             f"world={g.world_name()} level={p.u32(p.u32(g.game() + 0x60c) + 4)} fps={br.b.fps:.0f} video={br.b.videoPlaying}")
    except Exception as e:
        s = f"read error {e}"
    if s != last:
        print(f"{time.time() - t1:5.2f}s {s}")
        last = s
    time.sleep(0.03)
br.set_fps(60)
