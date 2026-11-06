"""Collision scanner: probes the game's own collision with its script function FindGroundXYZ
(native handler 0x61C690: ray straight down from (x, y, z), returns the hit height or -FLT_MAX).

Thousands of probes run inside one game frame through CLHook's batched script calls, so the result is the real
collision surface the player walks on (invisible floors/ledges included), not the render mesh.
"""
import math

from .bridge import T_FLOAT

FIND_GROUND_XYZ = 0x61C690
NO_HIT = -1e30


def probe(bridge, points):
    """points: [(x, y_start, z)] -> [y_hit or None]"""
    calls = [(FIND_GROUND_XYZ, [(T_FLOAT, x), (T_FLOAT, y), (T_FLOAT, z)]) for x, y, z in points]
    res = bridge.script_batch(calls)
    out = []
    for rtype, v in res:
        if rtype == T_FLOAT and v > NO_HIT and abs(v) < 1e7:
            out.append(v)
        else:
            out.append(None)
    return out


class HeightField:
    def __init__(self, cx, cz, radius, step, start_y, heights, n):
        self.cx, self.cz, self.radius, self.step, self.start_y, self.h, self.n = cx, cz, radius, step, start_y, heights, n

    def xz(self, i, j):
        return self.cx - self.radius + i * self.step, self.cz - self.radius + j * self.step


def scan(bridge, center, radius=12.0, step=0.5, above=2.5):
    """Grid of down-rays around center (x, y, z), starting `above` units over center height."""
    cx, cy, cz = center
    n = int(round(2 * radius / step)) + 1
    pts = []
    for i in range(n):
        for j in range(n):
            pts.append((cx - radius + i * step, cy + above, cz - radius + j * step))
    hs = probe(bridge, pts)
    grid = [[hs[i * n + j] for j in range(n)] for i in range(n)]
    return HeightField(cx, cz, radius, step, cy + above, grid, n)


def _height_color(y, ref):
    d = max(-3.0, min(3.0, y - ref)) / 3.0  # -1..1
    if d >= 0:
        r, g, b = 0.3 + 0.7 * d, 1.0, 0.3 * (1 - d)
    else:
        r, g, b = 0.2, 0.8 + 0.2 * d, 1.0 + 0.0 * d
    return 0xC0000000 | (int(r * 255) << 16) | (int(g * 255) << 8) | int(b * 255)


def to_lines(hf: HeightField, ref_y, max_slope_step=None, lift=0.02):
    """Wireframe of the floor. Edges between neighbours with a big height jump are drawn as red 'walls'."""
    jump = max_slope_step if max_slope_step is not None else max(hf.step * 2.5, 0.8)
    out = []
    n, h = hf.n, hf.h
    for i in range(n):
        for j in range(n):
            y = h[i][j]
            if y is None:
                continue
            x, z = hf.xz(i, j)
            for di, dj in ((1, 0), (0, 1)):
                ii, jj = i + di, j + dj
                if ii >= n or jj >= n:
                    continue
                y2 = h[ii][jj]
                x2, z2 = hf.xz(ii, jj)
                if y2 is None:
                    # edge of the world / hole: mark with an orange tick
                    out += [(x, y + lift, z, 0xFFFF8000), (x, y + 0.3, z, 0xFFFF8000)]
                    continue
                if abs(y2 - y) > jump:
                    # step / wall between samples: vertical red segment
                    xm, zm = (x + x2) / 2, (z + z2) / 2
                    out += [(xm, min(y, y2) + lift, zm, 0xFFFF3030), (xm, max(y, y2) + lift, zm, 0xFFFF3030)]
                    continue
                c = _height_color((y + y2) / 2, ref_y)
                out += [(x, y + lift, z, c), (x2, y2 + lift, z2, c)]
    return out
