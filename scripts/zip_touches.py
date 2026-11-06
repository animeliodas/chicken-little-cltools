"""Dump what happens right after every zipline touch in the recordings (position NaN / huge / normal, level change, end)."""
import csv, glob, gzip, json, math, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC = os.path.join(HERE, "recordings")


def rows_of(path):
    out = []
    try:
        with gzip.open(path, "rt") as f:
            for r in csv.reader(f):
                out.append(r)
    except (EOFError, OSError):
        pass  # truncated (game crashed while writing)
    return out


def f(s):
    try:
        return float(s)
    except ValueError:
        return float("nan")


def cls(v):
    if math.isnan(v):
        return "NaN"
    if math.isinf(v):
        return "inf"
    a = abs(v)
    return f"1e{math.log10(a):.0f}" if a > 1e6 else f"{v:.1f}"


for path in sorted(glob.glob(os.path.join(REC, "cornmaze_*.csv.gz"))):
    rows = rows_of(path)
    if len(rows) < 2:
        continue
    meta = json.load(open(path.replace(".csv.gz", ".json")))
    h = rows[0]; c = {k: i for i, k in enumerate(h)}; rows = rows[1:]
    rope = meta["ropes"][0]
    addr = int(rope["addr"], 16); n = rope["name"]
    att = [int(r[c["attached"]]) for r in rows]
    print(f"== {os.path.basename(path)}  frames={len(rows)}  crash={meta.get('crash') and meta['crash']['eip']}")
    for i in range(1, len(rows)):
        if att[i] == addr and att[i - 1] != addr:
            y = f(rows[i - 1][c[n + ".y"]])
            # last rider pos while previously attached (jump point) is not needed here
            seq = []
            for k in range(i, min(len(rows), i + 12)):
                r = rows[k]
                seq.append(f"{cls(f(r[c['pos_y']]))}/{cls(f(r[c['phys_y']]))}")
            end_in = len(rows) - i
            lvl_change = any(rows[k][c["level"]] != rows[i][c["level"]] for k in range(i, len(rows)))
            vid = any(int(rows[k][c["flags"]]) & 1 for k in range(i, min(len(rows), i + 4000)))
            print(f"  touch@{i}: rope y={cls(y)} vy={cls(f(rows[i-1][c[n + '.vy']]))} rider={f(rows[i][c[n + '.pos']]):.3f} "
                  f"frames_left={end_in} level_change={lvl_change} video={vid}")
            print("     pos_y/phys_y next frames:", " ".join(seq))
