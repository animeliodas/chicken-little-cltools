"""Measure zipline instability growth for given FPS values (deterministic: CLHook FixedStep)."""
import math, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cltools.mem import Process
from cltools.bridge import Bridge
Z = int(sys.argv[1], 16); SECS = float(sys.argv[2]); FPS_LIST = [int(x) for x in sys.argv[3:]]
here = os.path.dirname(os.path.abspath(__file__))
p = Process(); br = Bridge(); R = Z + 0x3DC
for fps in FPS_LIST:
    br.b.fixedStep = 1
    subprocess.run([sys.executable, os.path.join(here, "zip_experiment.py"), hex(Z), "0.88", str(fps), "0.2"], capture_output=True)
    br.b.fixedStep = 1
    br.set_fps(fps)
    t0 = time.time(); samples = []
    vt0 = br.b.vtime_ms
    while time.time() - t0 < SECS:
        y = abs(p.f32(R + 0x6c))
        gt = (br.b.vtime_ms - vt0) / 1000.0
        if y > 0 and math.isfinite(y):
            samples.append((gt, math.log10(y)))
        time.sleep(0.02)
    br.set_fps(60); br.b.fixedStep = 0
    late = [s for s in samples if s[1] > 2]
    if len(late) > 5:
        (t1, l1), (t2, l2) = late[0], late[-1]
        rate = (l2 - l1) / (t2 - t1)
        t20 = t1 + (20 - l1) / rate; t37 = t1 + (37 - l1) / rate
        print(f"{fps:5d} fps: +{rate:.2f} decades / game-second; |y|=1e20 at ~{t20:.1f}s, 1e37 at ~{t37:.1f}s "
              f"(real fps {br.b.fps:.0f})")
    else:
        mx = max((s[1] for s in samples), default=float('nan'))
        print(f"{fps:5d} fps: no runaway (max log10|y| = {mx:.2f})")
    time.sleep(1.5)
