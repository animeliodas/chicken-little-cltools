"""Parser for world object-attribute files (data_dx/worlds/<world>/<world>.OA).

The .OA file is the text export of every placed instance in a world:
name, position (#Pos x,y,z) and the editor attributes (env_type, scripts, triggers...).
The game itself loads the compiled .env; the .OA is the most readable source of the layout.
"""
import os
import re

from . import GAME_DIR

_INST_RE = re.compile(r'Instance\s+"(?P<idx>[^"]*)"\s*=\s*\{(?P<body>.*?)\n\t\}', re.S)
_POS_RE = re.compile(r"#Pos\s+([-\d.eE+]+),([-\d.eE+]+),([-\d.eE+]+)")
_NAME_RE = re.compile(r'Name\s*=\s*"([^"]*)"')
_ATTR_RE = re.compile(r'Attributes\s*=\s*"BEGIN OBJECTATTRIBUTES(.*?)END OBJECTATTRIBUTES"', re.S)


class Instance:
    __slots__ = ("index", "name", "pos", "attrs")

    def __init__(self, index, name, pos, attrs):
        self.index, self.name, self.pos, self.attrs = index, name, pos, attrs

    @property
    def type(self):
        return self.attrs.get("env_type") or self.attrs.get("env_select") or "?"

    def to_dict(self):
        return {"index": self.index, "name": self.name, "pos": self.pos, "attrs": self.attrs}

    def __repr__(self):
        return f"Instance({self.name!r}, {self.type}, pos={self.pos})"


def parse_oa(text):
    out = []
    for m in _INST_RE.finditer(text):
        body = m.group("body")
        pm = _POS_RE.search(body)
        pos = tuple(float(v) for v in pm.groups()) if pm else None
        nm = _NAME_RE.search(body)
        attrs = {}
        am = _ATTR_RE.search(body)
        if am:
            for line in am.group(1).splitlines():
                line = line.strip()
                if not line or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if k in attrs:  # repeated keys (lists) -> join
                    attrs[k] = attrs[k] + ";" + v
                else:
                    attrs[k] = v
        out.append(Instance(m.group("idx"), nm.group(1) if nm else "", pos, attrs))
    return out


def world_dirs():
    root = os.path.join(GAME_DIR, "data_dx", "worlds")
    return sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))


def find_world_file(world, ext):
    d = os.path.join(GAME_DIR, "data_dx", "worlds", world)
    for n in os.listdir(d):
        if n.lower().endswith(ext.lower()):
            return os.path.join(d, n)
    return None


def load_world_instances(world):
    p = find_world_file(world, ".oa")
    if not p:
        return []
    with open(p, "r", encoding="latin-1") as f:
        return parse_oa(f.read())


if __name__ == "__main__":
    import sys, collections
    w = sys.argv[1] if len(sys.argv) > 1 else "townsquare"
    inst = load_world_instances(w)
    print(f"{w}: {len(inst)} instances")
    c = collections.Counter(i.type for i in inst)
    for t, n in c.most_common():
        print(f"  {n:5d}  {t}")
