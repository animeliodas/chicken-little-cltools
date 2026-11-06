"""HOG archive reader/writer (Avalanche Software engine, Chicken Little PC).

Format (little endian):
    0x00 u16 version (2)
    0x02 u16 unknown (1)
    0x04 u32 file count
    0x08 u32 size of the name block
    0x0C u32 offset of the entry table (0x10)
    entry[count]: u32 name_offset, u32 data_offset, u32 size
    name block: NUL-terminated names (e.g. "VAR\\PLAYER.VAR")
    file data (16-byte aligned)

CLI:
    py -3 -m cltools.hog list  data_dx/vars.hog
    py -3 -m cltools.hog extract data_dx/vars.hog out_dir [pattern]
    py -3 -m cltools.hog pack in_dir new.hog [--like original.hog]
"""
import fnmatch
import os
import struct
import sys


class HogEntry:
    __slots__ = ("name", "offset", "size")

    def __init__(self, name, offset, size):
        self.name, self.offset, self.size = name, offset, size

    def __repr__(self):
        return f"HogEntry({self.name!r}, off=0x{self.offset:x}, size={self.size})"


class Hog:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self.data = f.read()
        d = self.data
        self.version, self.unk, count, self.names_size, table = struct.unpack_from("<HHIII", d, 0)
        self.entries = []
        for i in range(count):
            no, do, sz = struct.unpack_from("<III", d, table + i * 12)
            name = d[no:d.index(b"\0", no)].decode("latin-1")
            self.entries.append(HogEntry(name, do, sz))
        self.by_name = {e.name.upper().replace("/", "\\"): e for e in self.entries}

    def read(self, name):
        e = self.by_name[name.upper().replace("/", "\\")] if isinstance(name, str) else name
        return self.data[e.offset:e.offset + e.size]

    def glob(self, pattern):
        p = pattern.upper().replace("/", "\\")
        return [e for e in self.entries if fnmatch.fnmatch(e.name.upper(), p)]

    def extract(self, out_dir, pattern="*"):
        n = 0
        for e in self.glob(pattern):
            dst = os.path.join(out_dir, *e.name.split("\\"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(self.read(e))
            n += 1
        return n


def pack(files, out_path, version=2, unk=1, align=16):
    """files: list of (archive_name, bytes). Names are stored as given (use backslashes)."""
    count = len(files)
    table_off = 0x10
    names_off = table_off + count * 12
    name_blob = b""
    name_offs = []
    for name, _ in files:
        name_offs.append(names_off + len(name_blob))
        name_blob += name.encode("latin-1") + b"\0"
    pos = names_off + len(name_blob)
    pos = (pos + align - 1) // align * align
    entries = []
    blobs = []
    for (name, data), no in zip(files, name_offs):
        entries.append((no, pos, len(data)))
        blobs.append((pos, data))
        pos = (pos + len(data) + align - 1) // align * align
    out = bytearray(pos)
    struct.pack_into("<HHIII", out, 0, version, unk, count, len(name_blob), table_off)
    for i, (no, do, sz) in enumerate(entries):
        struct.pack_into("<III", out, table_off + i * 12, no, do, sz)
    out[names_off:names_off + len(name_blob)] = name_blob
    for do, data in blobs:
        out[do:do + len(data)] = data
    with open(out_path, "wb") as f:
        f.write(out)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "list":
        h = Hog(argv[1])
        for e in h.entries:
            print(f"{e.size:10d}  0x{e.offset:08x}  {e.name}")
        print(f"{len(h.entries)} files")
    elif cmd == "extract":
        h = Hog(argv[1])
        n = h.extract(argv[2], argv[3] if len(argv) > 3 else "*")
        print(f"extracted {n} files to {argv[2]}")
    elif cmd == "pack":
        src, dst = argv[1], argv[2]
        order = None
        if "--like" in argv:
            like = Hog(argv[argv.index("--like") + 1])
            order = [e.name for e in like.entries]
        files = {}
        for root, _, names in os.walk(src):
            for n in names:
                full = os.path.join(root, n)
                rel = os.path.relpath(full, src).replace("/", "\\").upper()
                files[rel] = open(full, "rb").read()
        if order:
            names = [n for n in order if n.upper() in files] + sorted(set(files) - {n.upper() for n in order})
        else:
            names = sorted(files)
        pack([(n, files[n.upper()]) for n in names], dst)
        print(f"packed {len(names)} files -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
