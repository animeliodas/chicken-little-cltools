"""Avalanche "DB" container (.DBL/.env/.adb/.sdb/.mdb/.dbu ...) and world-instance extraction.

Container:
    0x00 u32 0x30, u32 ?, char[2] "DB"/"DX", ..., 0x18 u32 chunk_count, ...
    chunks start at 0x20, each: 0x40-byte header + data
        +0x00 u16 type   +0x02 u16 flags   +0x04 u32 data size   +0x08 u16 version  +0x0A "1000"
World .DBL chunk types (townsquare):
    0x0082 textures (names + pixel data)       0x0022 models (481 in townsquare)
    0x0060 placed world instances (records of 0xB0 bytes)
    0x0600 sound emitters                       0x0283 world bounding box
    0x0067/0x0068/0x0069/0x0083/0x0200/0x0201/0x0203/0x0209/0x0210/0x0280/0x0281: not decoded yet

Instance record (chunk 0x60, after a 0x10-byte header: u16 count, u16 ?, u32 record size):
    +0x10 3 rows vec4: rotation * scale       +0x40 vec4 position (w = 1)
    +0x50 vec4 bounding sphere (centre, radius) +0x60 vec3 AABB min, +0x6C vec3 AABB max (world space)
    +0x90 u16 ?, u16 model index, u32 relative offset, u32 instance index
"""
import os
import struct

from . import GAME_DIR

CHUNK_HDR = 0x40


class Chunk:
    __slots__ = ("type", "flags", "version", "offset", "size", "data")

    def __init__(self, type_, flags, version, offset, size, data):
        self.type, self.flags, self.version, self.offset, self.size, self.data = type_, flags, version, offset, size, data

    def __repr__(self):
        return f"Chunk(type=0x{self.type:04x}, size=0x{self.size:x}, ver={self.version})"


class DBFile:
    def __init__(self, path=None, data=None):
        self.path = path
        self.data = data if data is not None else open(path, "rb").read()
        d = self.data
        self.kind = d[8:10].decode("latin-1")
        count = struct.unpack_from("<I", d, 0x18)[0]
        self.chunks = []
        off = 0x20
        for _ in range(count):
            if off + CHUNK_HDR > len(d):
                break
            t, f, sz, ver = struct.unpack_from("<HHIH", d, off)
            self.chunks.append(Chunk(t, f, ver, off, sz, d[off + CHUNK_HDR:off + CHUNK_HDR + sz]))
            off += CHUNK_HDR + sz

    def chunk(self, type_):
        for c in self.chunks:
            if c.type == type_:
                return c
        return None


class WorldInstance:
    __slots__ = ("index", "model", "matrix", "pos", "sphere", "bmin", "bmax", "flags")

    def __repr__(self):
        return f"WorldInstance(#{self.index}, model={self.model}, pos={self.pos})"


def world_instances(db: DBFile):
    c = db.chunk(0x0060)
    if not c:
        return []
    d = c.data
    count, _unk, rec = struct.unpack_from("<HHI", d, 0)
    if rec < 0xA0 or rec > 0x200:
        rec = 0xB0
    out = []
    for i in range(count):
        r = 0x10 + i * rec
        if r + rec > len(d):
            break
        w = WorldInstance()
        w.flags = struct.unpack_from("<I", d, r)[0]
        rows = [struct.unpack_from("<3f", d, r + 0x10 + 16 * k) for k in range(3)]
        w.matrix = rows
        w.pos = struct.unpack_from("<3f", d, r + 0x40)
        w.sphere = struct.unpack_from("<4f", d, r + 0x50)
        w.bmin = struct.unpack_from("<3f", d, r + 0x60)
        w.bmax = struct.unpack_from("<3f", d, r + 0x6C)
        _, w.model, _, w.index = struct.unpack_from("<HHII", d, r + 0x90)
        out.append(w)
    return out


def world_bbox(db: DBFile):
    c = db.chunk(0x0283)
    if not c or len(c.data) < 0x1C:
        return None
    v = struct.unpack_from("<6f", c.data, 4)
    return v[0:3], v[3:6]


def find_world_dbl(world):
    d = os.path.join(GAME_DIR, "data_dx", "worlds")
    for n in os.listdir(d):
        if n.lower() == world.lower():
            for f in os.listdir(os.path.join(d, n)):
                if f.lower().endswith(".dbl"):
                    return os.path.join(d, n, f)
    return None


def load_world_boxes(world):
    p = find_world_dbl(world)
    if not p:
        return [], None
    db = DBFile(p)
    return world_instances(db), world_bbox(db)


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        db = DBFile(p)
        print(f"{p}: {db.kind}, {len(db.chunks)} chunks")
        for c in db.chunks:
            print(f"   0x{c.offset:08x}  type 0x{c.type:04x}  size 0x{c.size:08x}  ver {c.version}")
        inst = world_instances(db)
        if inst:
            print(f"   {len(inst)} placed instances; bbox {world_bbox(db)}")
