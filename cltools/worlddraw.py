"""In-game 3D debug drawing of hidden level data (trigger volumes, death boxes, checkpoints, ...).

Every object in <world>.OA matches a placed instance in <world>.DBL (same position), whose world-space AABB is the
object's volume. The boxes near the player are sent to CLHook, which draws them with the game's own camera.
"""
import math

from . import dbl, oa

# category -> (match function, ARGB colour, enabled by default)
CATEGORIES = [
    ("Death boxes", lambda t: "death" in t, 0xFFFF3030, True),
    ("Checkpoints", lambda t: "checkpoint" in t, 0xFF30FF60, True),
    ("Level triggers", lambda t: t.startswith("level trigger") or "level exit" in t, 0xFFFF40FF, True),
    ("Trigger volumes", lambda t: t == "trigger volume", 0xFF30D0FF, True),
    ("Other triggers", lambda t: "trigger" in t and not any(k in t for k in ("particle", "sound", "level", "volume")),
     0xFFFFD030, True),
    ("Cameras", lambda t: "camera" in t, 0xFF9090A0, False),
    ("Sound / particle triggers", lambda t: "particle trigger" in t or "sound trigger" in t, 0x80A0A0A0, False),
    ("Start positions", lambda t: "start position" in t, 0xFFFFFFFF, True),
    ("Pickups", lambda t: any(k in t for k in ("acorn", "card", "egg", "pickup", "coin")), 0xFFFFA020, False),
    ("Everything else", None, 0x60FFFFFF, False),
]


def classify(type_name):
    t = type_name.lower()
    for i, (name, fn, color, _) in enumerate(CATEGORIES):
        if fn is None or fn(t):
            return i
    return len(CATEGORIES) - 1


class WorldObjects:
    """Objects of one world with their volumes."""

    def __init__(self, world):
        self.world = world
        boxes, _ = dbl.load_world_boxes(world)
        by_pos = {}
        for b in boxes:
            by_pos.setdefault(tuple(round(v, 3) for v in b.pos), b)
        self.items = []  # (category, name, type, bmin, bmax)
        for inst in oa.load_world_instances(world):
            if not inst.pos:
                continue
            b = by_pos.get(tuple(round(v, 3) for v in inst.pos))
            if b is None:
                continue
            self.items.append((classify(inst.type), inst.name, inst.type, b.bmin, b.bmax))


def box_lines(bmin, bmax, color):
    x0, y0, z0 = bmin
    x1, y1, z1 = bmax
    c = [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), (x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)]
    out = []
    for a, b in ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)):
        out.append((*c[a], color))
        out.append((*c[b], color))
    return out


def point_box_dist(p, bmin, bmax):
    d = 0.0
    for k in range(3):
        if p[k] < bmin[k]:
            d += (bmin[k] - p[k]) ** 2
        elif p[k] > bmax[k]:
            d += (p[k] - bmax[k]) ** 2
    return math.sqrt(d)


def build(objs: WorldObjects, player_pos, enabled, radius=80.0, labels=True, max_area=40000.0):
    """Returns (line_verts, labels) for categories in `enabled` (set of indices) near player_pos."""
    lines, labs = [], []
    near = []
    for cat, name, typ, bmin, bmax in objs.items:
        if cat not in enabled:
            continue
        if (bmax[0] - bmin[0]) * (bmax[2] - bmin[2]) > max_area:
            continue
        d = point_box_dist(player_pos, bmin, bmax) if player_pos else 0.0
        if d <= radius:
            near.append((d, cat, name, typ, bmin, bmax))
    near.sort(key=lambda t: t[0])
    for d, cat, name, typ, bmin, bmax in near[:1300]:
        color = CATEGORIES[cat][2]
        lines += box_lines(bmin, bmax, color)
        if labels and len(labs) < 256:
            cx, cz = (bmin[0] + bmax[0]) / 2, (bmin[2] + bmax[2]) / 2
            labs.append((cx, bmax[1], cz, color & 0xFFFFFF, name))
    return lines, labs
