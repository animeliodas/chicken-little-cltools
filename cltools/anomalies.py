"""Anomaly detector: walks every actor of the level and reports those whose position became NaN / inf or
absurdly large. Useful to discover new high-FPS instabilities (the zipline glitch is one of them).

Actor list: node = [[0x857CEC]+0x1C], next = [node+0x18], actor = [node+4]; position at actor+0x44.
"""
import math
import time

ACTOR_MGR = 0x857CEC
HUGE = 1e5

KNOWN_CLASSES = {
    0x7A61D0: "Avatar (player / NPC)",
    0x7BD778: "Zipline",
    0x7BD300: "Wire (wire walk)",
    0x7BC970: "Trigger",
    0x7C1AE8: "Ground drone (trash can)",
    0x7C17E8: "Corn-field drone",
    0x7BAF30: "Env object",
    0x7C49D0: "Pickup / simple",
}


def actors(proc):
    mgr = proc.u32(ACTOR_MGR)
    if not mgr:
        return
    node = proc.u32(mgr + 0x1C)
    n = 0
    while node and n < 20000:
        n += 1
        a = proc.u32(node + 4)
        if a:
            yield a
        node = proc.u32(node + 0x18)


class AnomalyWatch:
    def __init__(self):
        self.first_seen = {}      # addr -> (time, kind)
        self.world = None

    def scan(self, proc, world):
        if world != self.world:
            self.world = world
            self.first_seen = {}
        out = []
        now = time.time()
        for a in actors(proc):
            try:
                vt = proc.u32(a)
                pos = proc.vec3(a + 0x44)
            except OSError:
                continue
            if any(math.isnan(v) for v in pos):
                kind = "NaN"
            elif any(math.isinf(v) for v in pos):
                kind = "inf"
            elif max(abs(v) for v in pos) > HUGE:
                kind = f"huge 1e{math.log10(max(abs(v) for v in pos)):.0f}"
            else:
                continue
            if a not in self.first_seen:
                self.first_seen[a] = (now, kind)
            out.append({"addr": a, "vtable": vt, "class": KNOWN_CLASSES.get(vt, f"vtable {vt:#x}"),
                        "kind": kind, "pos": pos, "since": now - self.first_seen[a][0]})
        return out
