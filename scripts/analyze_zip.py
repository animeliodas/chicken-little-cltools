"""Analyse zipline-glitch recordings (CLTools/recordings/*.csv.gz from Record.bat / the Inspector recorder).

    py -3 scripts/analyze_zip.py [files...]      (default: every recording)

For every attempt: rope, jump point, wait time, FPS / game-dt statistics while waiting, |y| at the touch, where the
player touched, keys held, and the outcome (level complete / crash with address / nothing). Writes
CLTools/recordings/analysis.txt as well.
"""
import csv
import glob
import gzip
import json
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC_DIR = os.path.join(HERE, "recordings")
sys.path.insert(0, HERE)
from cltools.bridge import REC_KEYS  # noqa: E402


def fnum(s):
    try:
        return float(s)
    except ValueError:
        return float("nan")


def load(path):
    meta_path = path.replace(".csv.gz", ".json")
    meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
    rows = []
    with gzip.open(path, "rt") as f:
        rd = csv.reader(f)
        header = next(rd)
        try:
            for r in rd:
                rows.append(r)
        except (EOFError, OSError):
            pass  # file truncated by a crash
    return header, rows, meta


def keys_str(mask):
    return "+".join(k for i, k in enumerate(REC_KEYS) if mask >> i & 1) or "-"


def analyse_file(path, out):
    header, rows, meta = load(path)
    if not rows:
        return []
    col = {h: i for i, h in enumerate(header)}
    ropes = [(r["name"], int(r["addr"], 16)) for r in meta.get("ropes", [])]
    addr2name = {a: n for n, a in ropes}
    N = len(rows)
    frame = [int(r[col["frame"]]) for r in rows]
    real = [float(r[col["real_ms"]]) for r in rows]
    game_ms = [int(r[col["game_ms"]]) for r in rows]
    att = [int(r[col["attached"]]) if "attached" in col else 0 for r in rows]
    level = [int(r[col["level"]]) for r in rows]
    flags = [int(r[col["flags"]]) for r in rows]
    keys = [int(r[col["keys"]]) for r in rows]

    def rope_val(i, n, field):
        c = col.get(f"{n}.{field}")
        return fnum(rows[i][c]) if c is not None else float("nan")

    attempts = []
    cur = None          # (rope name, frame index of detach)
    i = 1
    while i < N:
        prev, now = att[i - 1], att[i]
        # leaving a rope that keeps simulating with nobody on it -> glitch candidate
        if prev in addr2name and now != prev:
            n = addr2name[prev]
            j = min(N - 1, i + 30)
            if rope_val(j, n, "active") and rope_val(j, n, "w") == 0:
                cur = {"rope": n, "detach_i": i, "jump_pos": rope_val(i - 1, n, "pos")}
        # touching a rope again
        if now in addr2name and prev != now and cur:
            n = addr2name[now]
            y = rope_val(i - 1, n, "y")
            if n == cur["rope"] or (math.isfinite(y) and abs(y) > 1) or not math.isfinite(y):
                a = cur
                a["touch_i"] = i
                a["touch_rope"] = n
                a["y_touch"] = y
                a["rider_pos_touch"] = rope_val(i, n, "pos")
                a["touch_xyz"] = tuple(fnum(rows[i - 1][col[k]]) for k in ("phys_x", "phys_y", "phys_z"))
                a["keys_touch"] = keys_str(keys[i])
                lamp_cols = [col[h] for h in header if h.startswith("lamp")]
                a["lamps_on"] = sum(1 for cc in lamp_cols if int(rows[i - 1][cc]) & 1) if lamp_cols else None
                # outcome: look ahead
                outcome, k = "nothing", i
                while k < N and real[k] - real[i] < 8000:
                    if level[k] != level[i] or (flags[k] & 1):
                        outcome = "LEVEL COMPLETE / switch"
                        break
                    k += 1
                if outcome == "nothing" and k >= N - 1 and meta.get("crash"):
                    c = meta["crash"]
                    outcome = f"CRASH {c['code']} @ {c['eip']} {c['access']}"
                elif outcome == "nothing" and k >= N - 1:
                    outcome = "recording ended (crash without report?)"
                a["outcome"] = outcome
                a["outcome_after_ms"] = real[min(k, N - 1)] - real[i]
                attempts.append(a)
                cur = None
        i += 1
    if cur:
        cur["outcome"] = "no touch recorded"
        attempts.append(cur)

    res = []
    for a in attempts:
        d0 = a["detach_i"]
        d1 = a.get("touch_i", N - 1)
        wait = (real[d1] - real[d0]) / 1000.0
        dts = [real[k] - real[k - 1] for k in range(d0 + 1, d1 + 1)]
        gdt = [game_ms[k] - game_ms[k - 1] for k in range(d0 + 1, d1 + 1)]
        hist = {}
        for g in gdt:
            hist[g] = hist.get(g, 0) + 1
        fps = 1000.0 / statistics.mean(dts) if dts else float("nan")
        hitches = sum(1 for x in dts if x > 12)
        worst = max(dts) if dts else 0
        line = (f"{os.path.basename(path)}  rope={a['rope']}  jump@{a['jump_pos']:.3f}  wait={wait:.2f}s  "
                f"fps~{fps:.0f}  frames={len(dts)}  hitches>12ms={hitches} (worst {worst:.0f}ms)  "
                f"game-dt hist={dict(sorted(hist.items())[:6])}")
        if "touch_i" in a:
            y = a["y_touch"]
            ly = math.log10(abs(y)) if y and math.isfinite(y) else float("inf")
            line += (f"\n    touch {a['touch_rope']} |y|=1e{ly:.1f} rider_pos={a['rider_pos_touch']:.3f} "
                     f"at {tuple(round(v, 2) for v in a['touch_xyz'])} keys={a['keys_touch']} "
                     f"drone_lamps_on={a.get('lamps_on')}")
        line += f"\n    => {a['outcome']}"
        if meta.get("exceptions"):
            line += f"\n    first-chance exceptions: {meta['exceptions'][-4:]}"
        res.append(line)
        print(line, file=out)
    return res


def main():
    files = sys.argv[1:] or sorted(glob.glob(os.path.join(REC_DIR, "*.csv.gz")))
    os.makedirs(REC_DIR, exist_ok=True)
    out_path = os.path.join(REC_DIR, "analysis.txt")
    with open(out_path, "w", encoding="utf-8") as out:
        class Tee:
            def write(self, s):
                out.write(s)
                sys.stdout.write(s)
        tee = Tee()
        total = 0
        for f in files:
            total += len(analyse_file(f, tee))
        print(f"\n{total} attempts in {len(files)} recordings -> {out_path}", file=tee)


if __name__ == "__main__":
    main()
