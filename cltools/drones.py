"""Live enemy-drone tracker (cornmaze "trash-can" ground drones and others).

Actors live in a linked list: node = [[0x857CEC]+0x1C], next = [node+0x18], actor = [node+4].
Enemies: ([actor+4] & [0x83190C]) == [0x831908]; enemy sub-type at actor+0x718 (9 = ground drone,
11 = corn-field drone). Ground drone: +0x44 position, +0x550 = -1 while asleep in its trash can (10 when alerted),
lamps = light objects at +0x928/+0x930 (lit when light+0x70 & 1). Killed drones disappear from the list.

Why it matters: a lit lamp crashes the game when the player position becomes NaN (zipline glitch), see
docs/ZIPLINE_GLITCH.md.
"""
import math

ACTOR_MGR = 0x857CEC
ENEMY_MASK, ENEMY_VALUE = 0x83190C, 0x831908
SUBTYPE = 0x718
GROUND_DRONE, CORN_DRONE = 9, 11
D_ALERT = 0x550
D_LIGHTS = (0x928, 0x930)

ASLEEP, AWAKE, LAMP, DEAD = "asleep", "AWAKE", "LAMP ON", "dead"
COLORS = {ASLEEP: 0xFF40FF60, AWAKE: 0xFFFFD030, LAMP: 0xFFFF3030, DEAD: 0x80909090}


def enemies(proc, subtypes=(GROUND_DRONE,)):
    out = []
    mgr = proc.u32(ACTOR_MGR)
    if not mgr:
        return out
    m1, m2 = proc.u32(ENEMY_MASK), proc.u32(ENEMY_VALUE)
    node = proc.u32(mgr + 0x1C)
    n = 0
    while node and n < 20000:
        n += 1
        try:
            a = proc.u32(node + 4)
            if a and (proc.u32(a + 4) & m1) == m2:
                st = proc.u32(a + SUBTYPE)
                if st in subtypes:
                    out.append((a, st))
            node = proc.u32(node + 0x18)
        except OSError:
            break
    return out


class Drone:
    __slots__ = ("addr", "subtype", "name", "pos", "state", "home")


class DroneTracker:
    """Keeps names (from <world>.OA by spawn position) and remembers drones that died."""

    def __init__(self):
        self.world = None
        self.known = {}       # addr -> Drone

    def _name_for(self, world, pos):
        try:
            from .oa import load_world_instances
            if not hasattr(self, "_inst") or self._inst_world != world:
                self._inst = [i for i in load_world_instances(world)
                              if i.pos and ("drone" in i.type.lower())]
                self._inst_world = world
            used = {d.name for d in self.known.values()}
            cands = [i for i in self._inst if i.name not in used]
            if cands:
                best = min(cands, key=lambda i: math.dist(i.pos, pos))
                if math.dist(best.pos, pos) < 12.0:
                    return best.name
        except Exception:
            pass
        return None

    def update(self, proc, world, include_corn=False):
        if world != self.world:
            self.world = world
            self.known = {}
        subtypes = (GROUND_DRONE, CORN_DRONE) if include_corn else (GROUND_DRONE,)
        alive = set()
        for a, st in enemies(proc, subtypes):
            alive.add(a)
            d = self.known.get(a)
            if d is None:
                d = Drone()
                d.addr, d.subtype = a, st
                d.pos = proc.vec3(a + 0x44)
                d.home = d.pos
                d.name = self._name_for(world, d.pos) or f"drone@{a:08x}"
                self.known[a] = d
            try:
                d.pos = proc.vec3(a + 0x44)
                if st == GROUND_DRONE:
                    lamp = any(proc.u32(proc.u32(a + o) + 0x70) & 1 for o in D_LIGHTS)
                    alert = proc.i32(a + D_ALERT)
                    d.state = LAMP if lamp else (ASLEEP if alert == -1 else AWAKE)
                else:
                    d.state = AWAKE
            except OSError:
                d.state = DEAD
        for a, d in self.known.items():
            if a not in alive:
                d.state = DEAD
        return list(self.known.values())


def summary(drones):
    alive = [d for d in drones if d.state != DEAD]
    return (len(alive), sum(1 for d in alive if d.state in (AWAKE, LAMP)),
            sum(1 for d in alive if d.state == LAMP), len(drones) - len(alive))
