"""Zipline (rope) state reader for the high-FPS zipline glitch. See docs/ZIPLINE_GLITCH.md.

A zipline actor has vtable 0x7BD778; its rope sub-object lives at +0x3DC.
"""
import math
import struct

ZIPLINE_VTABLE = 0x7BD778
ROPE = 0x3DC
F_ACTIVE = 0x498        # byte: rope simulation running
F_ALLOW_JUMP = 0x4D9    # byte: ziplineAllowSlideJump
F_NEXT = 0x4DB          # char[64]: nextZiplineName
R_POS = 0x60            # rider position along the rope 0..1
R_WEIGHT = 0x64         # rider weight (0 = nobody on it)
R_X, R_Y = 0x68, 0x6C   # rope displacement (sideways, vertical)
R_VY = 0x74
R_NODES, R_BASE = 0x0C, 0x80

# |y| thresholds (empirical + float limits): sqrt(FLT_MAX) = 1.8e19
NAN_LOW = 1e20          # attaching from here on produces NaN coordinates -> NaN-unsafe triggers fire
NAN_HIGH = 1e33         # past this the rope itself is about to overflow (inf/NaN): crash / random


def find_ziplines(proc):
    hits = [h for h in proc.scan(struct.pack("<I", ZIPLINE_VTABLE), writable_only=True, limit=500) if h % 4 == 0]
    out = []
    for h in hits:
        try:
            n = proc.i32(h + ROPE + R_NODES)
            if 2 <= n <= 64:
                out.append(h)
        except OSError:
            pass
    return out


def status(y):
    a = abs(y)
    if not math.isfinite(a):
        return "OVERFLOW (inf/NaN)", 0xFF4040
    if a < 1.0:
        return "calm", 0xA0A0A0
    if a < NAN_LOW:
        return "growing (touch now = fly to the sky)", 0xFFD040
    if a < NAN_HIGH:
        return "NaN WINDOW (touch now = NaN position)", 0x40FF60
    return "near overflow (crash risk)", 0xFF8030


class ZipState:
    __slots__ = ("addr", "name", "active", "weight", "pos", "y", "vy", "allow_jump", "start", "end")


def read(proc, addr, names=None):
    z = ZipState()
    z.addr = addr
    r = addr + ROPE
    z.active = proc.u8(addr + F_ACTIVE)
    z.allow_jump = proc.u8(addr + F_ALLOW_JUMP)
    z.weight, z.pos, z.y, z.vy = proc.f32(r + R_WEIGHT), proc.f32(r + R_POS), proc.f32(r + R_Y), proc.f32(r + R_VY)
    base = proc.u32(r + R_BASE)
    n = proc.i32(r + R_NODES)
    z.start = proc.vec3(base)
    z.end = proc.vec3(base + 12 * (n - 1))
    z.name = (names or {}).get(addr, f"zip@{addr:08x}")
    return z


def name_ziplines(proc, addrs, world):
    """Match zipline actors to .OA names by position."""
    from .oa import load_world_instances
    inst = [i for i in load_world_instances(world) if i.type == "Zipline" and i.pos]
    out = {}
    for a in addrs:
        p = proc.vec3(a + 0x44)
        if inst:
            best = min(inst, key=lambda i: math.dist(i.pos, p))
            if math.dist(best.pos, p) < 0.05:
                out[a] = best.name
    return out


# --- dynamic lights (ground "trash-can" drone lamps in cornmaze) -----------------------------
# With a NaN player position the light sorter 0x5D4DE0 reads a NULL slot (NaN compares as "less" with
# fcomp/test ah,1) as soon as any dynamic light is enabled -> crash at 0x5D5066. See docs/ZIPLINE_GLITCH.md.
DYN_LIGHT_COUNT = 0x83A47C
DYN_LIGHT_LIST = 0x83A4A0
LIGHT_FLAGS = 0x70        # bit 0 = enabled


def dynamic_lights(proc):
    """[(light address, flags address, position)]"""
    n = proc.u32(DYN_LIGHT_COUNT)
    lst = proc.u32(DYN_LIGHT_LIST)
    out = []
    for i in range(min(n, 64)):
        L = proc.u32(lst + 4 * i)
        out.append((L, L + LIGHT_FLAGS, proc.vec3(L + 0x10)))
    return out


def lamps_on(proc):
    lights = dynamic_lights(proc)
    on = [pos for L, fa, pos in lights if proc.u32(fa) & 1]
    return on, len(lights)
