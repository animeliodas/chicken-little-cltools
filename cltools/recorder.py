"""Per-frame "black box" recorder for zipline-glitch attempts (and anything else).

CLHook samples up to 96 dwords every presented frame into a ring buffer in shared memory; this recorder drains it to
CLTools/recordings/<world>_<time>.csv.gz together with a .json sidecar (field names, ropes, events, crash report).
The shared memory stays alive after the game crashes, so the frames right before a crash and the crash location
(instruction address, registers, stack) are kept.

Run standalone:  py -3 -m cltools.recorder      (Ctrl+C to stop)   or  Record.bat
"""
import csv
import gzip
import json
import math
import os
import struct
import sys
import threading
import time

from . import TOOLS_DIR
from .bridge import Bridge, REC_KEYS
from .game import Game, GAME_PTR, GAME_AVATARS, AV_POS, AV_VEL, AV_PHYS_POS
from .mem import Process
from . import zipline as zl

REC_DIR = os.path.join(TOOLS_DIR, "recordings")
LEVEL_ID_ADDR = 0x82A7D8          # [[game+0x60C]+4] -> static level-state struct 0x82A7D4
F = "f"  # float
U = "u"  # uint32
I = "i"  # int32
B = "b"  # low byte


def _decode(kind, v):
    if kind == F:
        return struct.unpack("<f", struct.pack("<I", v))[0]
    if kind == I:
        return struct.unpack("<i", struct.pack("<I", v))[0]
    if kind == B:
        return v & 0xFF
    return v


class Recorder:
    def __init__(self, log=print):
        self.log = log
        self.br = Bridge()
        if self.br.b.version < 4:
            raise RuntimeError("CLHook too old for recording - restart the game with the new d3d8.dll")
        self.proc = Process()
        self.game = Game(self.proc)
        self.fields = []          # (name, kind)
        self.ropes = []           # (name, addr)
        self.world = None
        self.avatar = 0
        self.file = None
        self.writer = None
        self.meta = None
        self.read_idx = 0
        self.rows = 0
        self.lost = 0
        self.stop_flag = False
        self.thread = None
        self.crash_seen = self.br.b.crashSeq
        self.exc_seen = self.br.b.excHead
        self.events = []

    # ------------------------------------------------------------------ setup
    def _configure(self):
        p, g = self.proc, self.game
        self.world = g.world_name() or "unknown"
        self.avatar = g.avatar()
        addrs, fields = [], []

        def add(name, addr, kind):
            if len(addrs) < 96:
                addrs.append(addr)
                fields.append((name, kind))

        add("level", LEVEL_ID_ADDR, U)
        a = self.avatar
        if a:
            for k, off in (("pos", AV_POS), ("phys", AV_PHYS_POS), ("vel", AV_VEL)):
                for j, ax in enumerate("xyz"):
                    add(f"{k}_{ax}", a + off + 4 * j, F)
            add("attached", a + 0x30, U)
            add("av_state", a + 0x300, U)
            add("av_mode", a + 0x228, U)
        self.ropes = []
        if self.world.lower() != "intro":
            ropes = zl.find_ziplines(p)
            names = zl.name_ziplines(p, ropes, self.world)
            for r in ropes[:16]:
                n = names.get(r, f"zip@{r:08x}")
                self.ropes.append((n, r))
                R = r + zl.ROPE
                add(f"{n}.active", r + zl.F_ACTIVE, B)
                add(f"{n}.w", R + zl.R_WEIGHT, F)
                add(f"{n}.pos", R + zl.R_POS, F)
                add(f"{n}.y", R + zl.R_Y, F)
                add(f"{n}.vy", R + zl.R_VY, F)
        if self.world.lower() != "intro":
            try:
                for i, (L, fa, pos) in enumerate(zl.dynamic_lights(p)[:40]):
                    add(f"lamp{i}", fa, U)
            except OSError:
                pass
        b = self.br.b
        b.recNumAddr = 0
        for i, ad in enumerate(addrs):
            b.recAddr[i] = ad
        b.recNumAddr = len(addrs)
        self.fields = fields
        self._new_file()

    def _new_file(self):
        self._close_file()
        os.makedirs(REC_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = os.path.join(REC_DIR, f"{self.world}_{stamp}")
        self.path = base + ".csv.gz"
        self.meta_path = base + ".json"
        self.file = gzip.open(self.path, "wt", newline="", compresslevel=3)
        self.writer = csv.writer(self.file)
        self.writer.writerow(["frame", "real_ms", "vtime_ms", "game_ms", "fps", "keys", "flags"] +
                             [n for n, _ in self.fields])
        self.meta = {"world": self.world, "started": stamp, "avatar": hex(self.avatar or 0),
                     "ropes": [{"name": n, "addr": hex(a)} for n, a in self.ropes],
                     "fields": [n for n, _ in self.fields], "keys": REC_KEYS, "events": [], "crash": None,
                     "exceptions": []}
        self.events = self.meta["events"]
        self.rows = 0
        self.log(f"recording -> {self.path}")

    def _close_file(self):
        if self.file:
            self.file.close()
            self.file = None
            self._write_meta()

    def _write_meta(self):
        if self.meta:
            with open(self.meta_path, "w") as f:
                json.dump(self.meta, f, indent=1)

    # ------------------------------------------------------------------ loop
    def _drain(self):
        b = self.br.b
        head = b.recHead
        ring = b.recRing or 8192
        if head - self.read_idx > ring:
            self.lost += head - self.read_idx - ring
            self.read_idx = head - ring
        kinds = [k for _, k in self.fields]
        n = len(kinds)
        while self.read_idx < head:
            r = b.rec[self.read_idx % ring]
            vals = [_decode(kinds[i], r.vals[i]) for i in range(n)]
            self.writer.writerow([r.frame, f"{r.realMs:.3f}", r.vtimeMs, r.gameMs, f"{r.fps:.0f}", r.keys, r.flags] +
                                 [f"{v:.6g}" if isinstance(v, float) else v for v in vals])
            self.read_idx += 1
            self.rows += 1

    def _check_exceptions(self):
        b = self.br.b
        while self.exc_seen < b.excHead:
            e = b.exc[self.exc_seen % 16]
            if not e.inCall:
                info = {"frame": e.frame, "code": hex(e.code), "eip": hex(e.eip), "access": hex(e.access)}
                self.meta["exceptions"].append(info)
                self.log(f"exception in game code: {info}")
            self.exc_seen += 1
        if b.crashSeq != self.crash_seen:
            self.crash_seen = b.crashSeq
            regs = dict(zip(["eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp"], [hex(x) for x in b.crashRegs]))
            self.meta["crash"] = {"code": hex(b.crashCode), "eip": hex(b.crashEip),
                                  "access": ("write " if b.crashAccessType else "read ") + hex(b.crashAccess),
                                  "frame": b.crashFrame, "regs": regs, "stack": [hex(x) for x in b.crashStack]}
            self.log(f"CRASH {self.meta['crash']['code']} at {self.meta['crash']['eip']} ({self.meta['crash']['access']})")
            self._write_meta()

    def run(self):
        b = self.br.b
        self._configure()
        self.read_idx = b.recHead
        b.recOn = 1
        last_cfg = time.time()
        alive = True
        try:
            while not self.stop_flag:
                alive = self.proc.alive()
                self._drain()
                self._check_exceptions()
                if not alive:
                    self.events.append({"t": time.time(), "event": "process exited"})
                    self.log("game process exited - recording closed")
                    break
                if time.time() - last_cfg > 0.5:
                    last_cfg = time.time()
                    try:
                        w = self.game.world_name()
                        av = self.game.avatar()
                    except OSError:
                        w, av = self.world, self.avatar
                    if (w and w != self.world) or (av and av != self.avatar):
                        self.events.append({"frame": b.frame, "event": f"world/avatar change -> {w}"})
                        self._configure()
                self.file.flush()
                time.sleep(0.02)
        finally:
            try:
                self._drain()
                self._check_exceptions()
            except Exception:
                pass
            if alive:
                b.recOn = 0
            self._close_file()
            self.log(f"stopped: {self.rows} frames, lost {self.lost}")

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_flag = True
        if self.thread:
            self.thread.join(3)


def main():
    print("CLTools recorder - play normally; Ctrl+C to stop. Files go to", REC_DIR)
    while True:
        try:
            rec = Recorder()
            break
        except (OSError, RuntimeError) as e:
            print("waiting for the game:", e)
            time.sleep(2)
    try:
        rec.run()
    except KeyboardInterrupt:
        rec.stop_flag = True


if __name__ == "__main__":
    main()
