"""Parser/writer for .VAR text scripts ("Generated script for ..." files).

Example (data/worlds/townsquare/player.var):
    context player
    startPos0 [-4.21 0 -8.71]
    startRot0 0
    end

Values: numbers, [vectors], "strings" or bare words. Comments start with '#'.
Loose files in data/worlds/<world>/ are read by the game, so editing them (e.g. startPos)
changes the level start without touching any archive.
"""
import os
import re

from . import GAME_DIR

_VEC = re.compile(r"^\[(.*)\]$")


def _value(tok):
    m = _VEC.match(tok)
    if m:
        return [float(x) for x in m.group(1).split()]
    try:
        return int(tok)
    except ValueError:
        pass
    try:
        return float(tok)
    except ValueError:
        return tok.strip('"')


def parse_var(text):
    """Returns {context_name: [(key, value), ...]} preserving order (keys may repeat)."""
    out = {}
    cur = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("context "):
            cur = line.split(None, 1)[1].strip()
            out.setdefault(cur, [])
            continue
        if line == "end":
            cur = None
            continue
        parts = line.split(None, 1)
        key = parts[0]
        val = _value(parts[1].strip()) if len(parts) > 1 else None
        out.setdefault(cur or "", []).append((key, val))
    return out


def format_value(v):
    if isinstance(v, list):
        return "[" + " ".join(_fmt_num(x) for x in v) + "]"
    if isinstance(v, float):
        return _fmt_num(v)
    return str(v)


def _fmt_num(x):
    s = f"{x:.6f}".rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def write_var(contexts, header=None):
    lines = []
    for ctx, items in contexts.items():
        lines.append(f"# Generated script for '{ctx}'" if header is None else header)
        lines.append("")
        lines.append(f"context {ctx}")
        lines.append("")
        for k, v in items:
            lines.append(f"{k} {format_value(v)}" if v is not None else k)
        lines.append("")
        lines.append("end")
        lines.append("")
    return "\r\n".join(lines)


def world_var_path(world, name="player.var"):
    d = os.path.join(GAME_DIR, "data", "worlds", world)
    if not os.path.isdir(d):
        for n in os.listdir(os.path.join(GAME_DIR, "data", "worlds")):
            if n.lower() == world.lower():
                d = os.path.join(GAME_DIR, "data", "worlds", n)
                break
    for n in os.listdir(d) if os.path.isdir(d) else []:
        if n.lower() == name.lower():
            return os.path.join(d, n)
    return os.path.join(d, name)


def player_starts(world):
    """[(index, (x,y,z), rot_deg)] from data/worlds/<world>/player.var"""
    p = world_var_path(world)
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="latin-1") as f:
        ctx = parse_var(f.read())
    items = dict()
    for k, v in ctx.get("player", []):
        items[k] = v
    out = []
    i = 0
    while f"startPos{i}" in items:
        out.append((i, tuple(items[f"startPos{i}"]), float(items.get(f"startRot{i}", 0))))
        i += 1
    return out
