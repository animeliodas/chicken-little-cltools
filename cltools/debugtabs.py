"""Extra Inspector tabs: revived developer debug menu, in-game 3D world debug, hidden levels, script console.

The retail game still contains the developer debug menu, but its central command handler was stubbed out.
The parts whose handlers survived are exposed here and called on the game thread through CLHook.
"""
import math
import os
import struct
import time

from PyQt6 import QtCore, QtGui, QtWidgets

from . import GAME_DIR, TOOLS_DIR
from . import colscan, worlddraw
from .bridge import T_BOOL, T_FLOAT, T_INT
from . import game as gm

# --- surviving developer-menu entries ------------------------------------------------------
# (label, flag address, size, toggle function (cdecl, no args))
RENDER_FLAGS = [
    ("Wire-frame", 0x83ED77, 1, 0x5E5B50),
    ("Lighting", 0x83ED74, 1, 0x5E5AF0),
    ("Fog", 0x83ED75, 1, 0x5E5B30),
    ("Vertex colours", 0x83ED76, 1, 0x5E5B10),
    ("Diffuse maps (textures)", 0x83ED80, 1, 0x5E5BF0),
    ("View back buffer", 0x83ED8B, 1, 0x5E5D40),
    ("Distortion effects", 0x83EB3C, 1, 0x5DDFE0),
]
# (label, value address, cycle function, number of values)
RENDER_CYCLES = [
    ("Bone render", 0x83ED8D, 0x5E5B60, 4),
    ("Visibility mode", 0x839C34, 0x5C30A0, 5),
    ("Render mode", 0x839C3C, 0x5C2FF0, 6),
    ("Occlusion mode", 0x839C58, 0x5C3170, 4),
]
CHEAT_TOGGLE = 0x459B00         # cb(id, key)
CHEAT_GET = 0x4033EB            # thiscall PersistentData::Get(key), this = [0x82A6D0] + 0x148
CHEAT_TABLE_PTR = 0x82A6D0
CHEATS = [("God mode", "godMode", 0x79BB70), ("Big head", "bigHead", 0x79BB58), ("Big comb", "bigComb", 0x79BB40),
          ("Big feet", "bigFeet", 0x79BB28), ("Sun glasses", "sunGlasses", 0x79BB0C),
          ("Underwear", "underwear", 0x79BAF0), ("Paper pants", "paperPants", 0x79BAD4),
          ("Feather cloud", "featherCloud", 0x79BAB4), ("Cannon balls", "cannonBalls", 0x79BA94)]
PLAYER_CB = 0x460D50            # cb(id, ctx)
PLAYER_ACTIONS = [("Add egg", -4), ("Remove egg", -3), ("Add coin", -2), ("Difficulty: easy", -1),
                  ("Difficulty: normal", 0), ("Difficulty: hard", 1), ("Add 20 card sets", 2)]
ENGINE_LIMITER_TOGGLE = 0x5E5CF0


def _need(insp):
    if not insp.br or not insp.proc:
        raise RuntimeError("game not running")
    if insp.br.b.version < 3:
        raise RuntimeError("old d3d8.dll - restart the game with the new CLHook")
    return insp.br, insp.proc


class DebugMenuTab(QtWidgets.QWidget):
    def __init__(self, insp):
        super().__init__()
        self.insp = insp
        v = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel("Developer debug menu from the retail exe (only entries whose code survived). "
                                "Actions run on the game thread between frames.")
        note.setWordWrap(True)
        v.addWidget(note)

        g = QtWidgets.QGroupBox("Renderer")
        gl = QtWidgets.QGridLayout(g)
        self.flag_boxes = []
        for i, (label, addr, size, fn) in enumerate(RENDER_FLAGS):
            cb = QtWidgets.QCheckBox(label)
            cb.clicked.connect(lambda on, a=addr, f=fn: self._set_flag(a, f, on))
            gl.addWidget(cb, i // 2, i % 2)
            self.flag_boxes.append((cb, addr))
        row = len(RENDER_FLAGS) // 2 + 1
        self.cycle_labels = []
        for j, (label, addr, fn, n) in enumerate(RENDER_CYCLES):
            b = QtWidgets.QPushButton(f"{label}: ?")
            b.clicked.connect(lambda _, f=fn: self._call(f))
            gl.addWidget(b, row + j // 2, j % 2)
            self.cycle_labels.append((b, label, addr))
        v.addWidget(g)

        g = QtWidgets.QGroupBox("Free camera (CLHook)  -  F11 toggle, I/J/K/L move, U/O down/up, arrows look, Ctrl fast")
        gl = QtWidgets.QHBoxLayout(g)
        self.fc = QtWidgets.QCheckBox("enabled")
        self.fc.clicked.connect(lambda on: self.insp.br and setattr(self.insp.br.b, "freecamOn", int(on)))
        self.fc_pos = QtWidgets.QLabel("-")
        self.fc_pos.setFont(QtGui.QFont("Consolas", 9))
        btp = QtWidgets.QPushButton("Teleport player to camera")
        btp.clicked.connect(self._tp_to_cam)
        gl.addWidget(self.fc)
        gl.addWidget(self.fc_pos, 1)
        gl.addWidget(btp)
        v.addWidget(g)

        g = QtWidgets.QGroupBox("Engine frame limiter (game's own, Sleep-based)")
        gl = QtWidgets.QHBoxLayout(g)
        self.lim = QtWidgets.QCheckBox("enabled")
        self.lim.clicked.connect(lambda on: self._set_flag(gm.GAME_LIMITER_ON, ENGINE_LIMITER_TOGGLE, on))
        self.interval = QtWidgets.QSpinBox()
        self.interval.setRange(1, 6)
        self.interval.setPrefix("interval ")
        self.interval.setSuffix(" x 1/60 s")
        bi = QtWidgets.QPushButton("Set")
        bi.clicked.connect(lambda: self.insp.proc and self.insp.proc.write(gm.GAME_FRAME_INTERVAL,
                                                                            bytes([self.interval.value()])))
        gl.addWidget(self.lim)
        gl.addWidget(self.interval)
        gl.addWidget(bi)
        gl.addStretch(1)
        v.addWidget(g)

        g = QtWidgets.QGroupBox("Cheats (game's own cheat flags)")
        gl = QtWidgets.QGridLayout(g)
        self.cheat_boxes = []
        for i, (label, key, addr) in enumerate(CHEATS):
            cb = QtWidgets.QCheckBox(label)
            cb.clicked.connect(lambda on, k=i, a=addr: self._toggle_cheat(k, a, on))
            gl.addWidget(cb, i // 3, i % 3)
            self.cheat_boxes.append((cb, addr))
        v.addWidget(g)

        g = QtWidgets.QGroupBox("Player (changes progress if the game saves afterwards)")
        gl = QtWidgets.QGridLayout(g)
        for i, (label, aid) in enumerate(PLAYER_ACTIONS):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(lambda _, x=aid: self._call(PLAYER_CB, x, 0))
            gl.addWidget(b, i // 3, i % 3)
        v.addWidget(g)
        v.addStretch(1)
        self._last = 0

    def _tp_to_cam(self):
        br, g = self.insp.br, self.insp.game
        if not br or not g or not br.b.freecamOn:
            self.insp.msg("enable the free camera first")
            return
        x, y, z = br.b.freecam[0], br.b.freecam[1], br.b.freecam[2]
        br.b.freecamOn = 0
        g.teleport_snap((x, y - 0.3, z), br)

    def _call(self, fn, *args):
        try:
            br, _ = _need(self.insp)
            br.call(fn, *args)
        except Exception as e:
            self.insp.msg(f"call 0x{fn:x} failed: {e}")

    def _set_flag(self, addr, fn, on):
        try:
            _, p = _need(self.insp)
            if bool(p.u8(addr)) != bool(on):
                self._call(fn)
        except Exception as e:
            self.insp.msg(str(e))

    def _toggle_cheat(self, idx, key_addr, on):
        try:
            br, p = _need(self.insp)
            table = p.u32(CHEAT_TABLE_PTR) + 0x148
            if bool(br.call(CHEAT_GET, key_addr, this=table)) != bool(on):
                br.call(CHEAT_TOGGLE, idx, key_addr)
        except Exception as e:
            self.insp.msg(f"cheat: {e}")

    def tick(self):
        if time.time() - self._last < 0.5 or not self.insp.proc or not self.isVisible():
            return
        self._last = time.time()
        p = self.insp.proc
        br = self.insp.br
        if br:
            self.fc.setChecked(bool(br.b.freecamOn))
            f = br.b.freecam
            self.fc_pos.setText(f"{f[0]:8.2f} {f[1]:8.2f} {f[2]:8.2f}  yaw {math.degrees(f[3]):6.1f}  pitch {math.degrees(f[4]):5.1f}")
        try:
            for cb, addr in self.flag_boxes:
                cb.setChecked(bool(p.u8(addr)))
            for b, label, addr in self.cycle_labels:
                val = p.u8(addr) if label == "Bone render" else p.i32(addr)
                b.setText(f"{label}: {val}  (click = next)")
            lim, iv = p.u8(gm.GAME_LIMITER_ON), p.u8(gm.GAME_FRAME_INTERVAL)
            self.lim.setChecked(bool(lim))
            if not self.interval.hasFocus():
                self.interval.setValue(max(1, iv))
            if self.insp.br and self.insp.br.b.version >= 3:
                table = p.u32(CHEAT_TABLE_PTR) + 0x148
                for cb, addr in self.cheat_boxes:
                    cb.setChecked(bool(self.insp.br.call(CHEAT_GET, addr, this=table, timeout=0.5)))
        except Exception:
            pass


class World3DTab(QtWidgets.QWidget):
    def __init__(self, insp):
        super().__init__()
        self.insp = insp
        self.objs = None
        self.col_lines = []
        self._last = 0
        self._last_scan = 0
        v = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel("Draws hidden level data inside the game with the game's own camera. "
                                "Object volumes come from the world files (.OA + .DBL), collision from live "
                                "probes of the game's collision (FindGroundXYZ).")
        note.setWordWrap(True)
        v.addWidget(note)

        g = QtWidgets.QGroupBox("Object volumes")
        gl = QtWidgets.QGridLayout(g)
        self.cat_boxes = []
        for i, (name, fn, color, default) in enumerate(worlddraw.CATEGORIES):
            cb = QtWidgets.QCheckBox(name)
            cb.setChecked(default)
            c = QtGui.QColor((color >> 16) & 255, (color >> 8) & 255, color & 255)
            cb.setStyleSheet(f"color: {c.name()}")
            gl.addWidget(cb, i // 2, i % 2)
            self.cat_boxes.append(cb)
        r = len(worlddraw.CATEGORIES) // 2 + 1
        self.radius = QtWidgets.QDoubleSpinBox()
        self.radius.setRange(5, 2000)
        self.radius.setValue(60)
        self.radius.setPrefix("radius ")
        self.labels = QtWidgets.QCheckBox("names")
        self.labels.setChecked(True)
        self.depth = QtWidgets.QCheckBox("hide behind walls (depth test)")
        gl.addWidget(self.radius, r, 0)
        gl.addWidget(self.labels, r, 1)
        gl.addWidget(self.depth, r + 1, 0, 1, 2)
        self.enabled = QtWidgets.QCheckBox("Show object volumes in game")
        gl.addWidget(self.enabled, r + 2, 0, 1, 2)
        v.addWidget(g)

        g = QtWidgets.QGroupBox("Collision scan (walkable surface around the player)")
        gl = QtWidgets.QGridLayout(g)
        self.c_radius = QtWidgets.QDoubleSpinBox()
        self.c_radius.setRange(1, 60)
        self.c_radius.setValue(10)
        self.c_radius.setPrefix("radius ")
        self.c_step = QtWidgets.QDoubleSpinBox()
        self.c_step.setRange(0.1, 4)
        self.c_step.setSingleStep(0.1)
        self.c_step.setValue(0.4)
        self.c_step.setPrefix("step ")
        self.c_above = QtWidgets.QDoubleSpinBox()
        self.c_above.setRange(0.2, 50)
        self.c_above.setValue(2.5)
        self.c_above.setPrefix("start above player ")
        self.c_auto = QtWidgets.QCheckBox("auto refresh (1 s)")
        bscan = QtWidgets.QPushButton("Scan now")
        bscan.clicked.connect(self.scan)
        bclr = QtWidgets.QPushButton("Clear")
        bclr.clicked.connect(self.clear_scan)
        gl.addWidget(self.c_radius, 0, 0)
        gl.addWidget(self.c_step, 0, 1)
        gl.addWidget(self.c_above, 1, 0)
        gl.addWidget(self.c_auto, 1, 1)
        gl.addWidget(bscan, 2, 0)
        gl.addWidget(bclr, 2, 1)
        legend = QtWidgets.QLabel("blue..green..yellow = floor below..above you, red = step/wall, orange = edge/hole")
        legend.setWordWrap(True)
        gl.addWidget(legend, 3, 0, 1, 2)
        v.addWidget(g)
        g = QtWidgets.QGroupBox("Enemy drones (live, through walls)")
        gl = QtWidgets.QGridLayout(g)
        self.drones_on = QtWidgets.QCheckBox("Highlight drones")
        self.drones_on.setChecked(True)
        self.drones_corn = QtWidgets.QCheckBox("include corn-field drones")
        self.drones_dead = QtWidgets.QCheckBox("show killed")
        self.drones_dead.setChecked(True)
        self.drones_beam = QtWidgets.QCheckBox("8 m beams")
        self.drones_beam.setChecked(True)
        gl.addWidget(self.drones_on, 0, 0)
        gl.addWidget(self.drones_corn, 0, 1)
        gl.addWidget(self.drones_dead, 1, 0)
        gl.addWidget(self.drones_beam, 1, 1)
        self.drone_info = QtWidgets.QLabel("-")
        self.drone_info.setStyleSheet("font-weight: bold")
        gl.addWidget(self.drone_info, 2, 0, 1, 2)
        leg = QtWidgets.QLabel("green = asleep in its trash can, yellow = awake, red = lamp ON "
                               "(zipline NaN glitch would crash), grey = killed")
        leg.setWordWrap(True)
        gl.addWidget(leg, 3, 0, 1, 2)
        v.addWidget(g)
        from .drones import DroneTracker
        self.tracker = DroneTracker()

        self.info = QtWidgets.QLabel("")
        v.addWidget(self.info)
        v.addStretch(1)

    def _drone_lines(self):
        from . import drones as dr
        from .worlddraw import box_lines
        self.insp.drone_overlay = []
        if not self.drones_on.isChecked() or not self.insp.game:
            return [], []
        w = self.insp.game.world_name()
        if not w or w.lower() == "intro":
            return [], []
        try:
            ds = self.tracker.update(self.insp.proc, w, self.drones_corn.isChecked())
        except OSError:
            return [], []
        if not ds:
            self.drone_info.setText("no drones in this level")
            return [], []
        p = self.insp.game.player_pos() or (0, 0, 0)
        lines, labels = [], []
        for d in ds:
            if d.state == dr.DEAD and not self.drones_dead.isChecked():
                continue
            c = dr.COLORS[d.state]
            x, y, z = d.pos
            lines += box_lines((x - 0.4, y - 0.1, z - 0.4), (x + 0.4, y + 0.9, z + 0.4), c)
            if self.drones_beam.isChecked() and d.state != dr.DEAD:
                lines += [(x, y + 0.9, z, c), (x, y + 8.0, z, c)]
            dist = math.dist(p, d.pos) if p else 0
            if len(labels) < 200:
                labels.append((x, y + 1.0, z, c & 0xFFFFFF, f"{d.name} {d.state} {dist:.0f}m"))
        alive, awake, lamps, dead = dr.summary(ds)
        self.drone_info.setText(f"alive {alive}  (awake {awake}, lamps ON {lamps})  killed {dead}")
        col = "FF4040" if lamps else ("FFD030" if awake else "40FF60")
        self.insp.drone_overlay = [f"{col}drones: alive {alive}  awake {awake}  lamps ON {lamps}  killed {dead}"]
        return lines, labels

    def scan(self):
        try:
            br, _ = _need(self.insp)
            p = self.insp.game.player_pos()
            if not p:
                return
            t = time.time()
            hf = colscan.scan(br, p, self.c_radius.value(), self.c_step.value(), self.c_above.value())
            self.col_lines = colscan.to_lines(hf, p[1])
            hits = sum(1 for row in hf.h for x in row if x is not None)
            self.info.setText(f"collision: {hits}/{hf.n * hf.n} probes hit, {time.time() - t:.2f}s")
            self._last_scan = time.time()
            self._push()
        except Exception as e:
            self.insp.msg(f"scan: {e}")

    def clear_scan(self):
        self.col_lines = []
        self.c_auto.setChecked(False)
        self._push()

    def _push(self, lines=None, labels=None):
        br = self.insp.br
        if not br or br.b.version < 3:
            return
        br.b.worldDepth = 1 if self.depth.isChecked() else 0
        if lines is None:
            lines, labels = self._object_lines()
        dl, dlab = self._drone_lines()
        br.set_lines(lines + dl + self.col_lines)
        br.set_labels((labels or []) + dlab)

    def _object_lines(self):
        if not self.enabled.isChecked() or not self.insp.game:
            return [], []
        w = self.insp.game.world_name()
        if not w or w.lower() == "intro":
            return [], []
        if not self.objs or self.objs.world.lower() != w.lower():
            self.objs = worlddraw.WorldObjects(w)
        p = self.insp.game.player_pos()
        en = {i for i, cb in enumerate(self.cat_boxes) if cb.isChecked()}
        return worlddraw.build(self.objs, p, en, self.radius.value(), self.labels.isChecked())

    def tick(self):
        if time.time() - self._last < 0.3 or not self.insp.br:
            return
        self._last = time.time()
        if self.c_auto.isChecked() and time.time() - self._last_scan > 1.0:
            self.scan()
            return
        if self.enabled.isChecked() or self.col_lines or self.drones_on.isChecked():
            self._push()
        elif self.insp.br.b.version >= 3 and (self.insp.br.b.lineCount or self.insp.br.b.labelCount):
            self.insp.br.set_lines([])
            self.insp.br.set_labels([])


def _orig_level_dir_ptr(index):
    """Pointer stored in the level table entry on disk (Chick.exe .data is not encrypted)."""
    import pefile
    pe = pefile.PE(os.path.join(GAME_DIR, "Chick.exe"), fast_load=True)
    va = gm.LEVEL_TABLE + index * gm.LEVEL_TABLE_STRIDE + 4
    off = pe.get_offset_from_rva(va - 0x400000)
    with open(os.path.join(GAME_DIR, "Chick.exe"), "rb") as f:
        f.seek(off)
        return struct.unpack("<I", f.read(4))[0]


class LevelsTab(QtWidgets.QWidget):
    HOST = 1  # "Late for School"

    def __init__(self, insp):
        super().__init__()
        self.insp = insp
        v = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel(
            "Level table of the game (33 entries). Load any world directly, e.g. sub-levels like <b>theatre</b> "
            "that Select Level does not list (handy for practice). #0 intro is the title-screen backdrop; "
            "entries 25-27 and 29-32 are dev leftovers without data.<br>Pick a world, press <i>Load via 'Late for School'</i>, then in the main menu "
            "choose <i>Select Level → Late for School</i>. The patch lives only in memory.")
        note.setWordWrap(True)
        v.addWidget(note)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "World folder", "Name", "Data"])
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        v.addWidget(self.table)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Load via 'Late for School'")
        b.clicked.connect(self.patch)
        r = QtWidgets.QPushButton("Restore 'Late for School'")
        r.clicked.connect(self.restore)
        ref = QtWidgets.QPushButton("Refresh")
        ref.clicked.connect(self.refresh)
        row.addWidget(b)
        row.addWidget(r)
        row.addWidget(ref)
        v.addLayout(row)
        self.status = QtWidgets.QLabel("")
        v.addWidget(self.status)
        self.ptrs = {}

    def refresh(self):
        p = self.insp.proc
        if not p:
            return
        worlds = {d.lower() for d in os.listdir(os.path.join(GAME_DIR, "data_dx", "worlds"))}
        self.table.setRowCount(0)
        for i in range(gm.LEVEL_COUNT):
            a = gm.LEVEL_TABLE + i * gm.LEVEL_TABLE_STRIDE
            ptr = p.u32(a + 4)
            self.ptrs[i] = ptr
            d, name = p.cstr(ptr, 40), p.cstr(p.u32(a + 8), 40)
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, val in enumerate([str(i), d, name, "yes" if d.lower() in worlds else "-"]):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(val))
        cur = p.cstr(p.u32(gm.LEVEL_TABLE + self.HOST * gm.LEVEL_TABLE_STRIDE + 4), 40)
        self.status.setText(f"'Late for School' currently loads: {cur}")

    def patch(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows or not self.insp.proc:
            return
        i = rows[0].row()
        self.insp.proc.w_u32(gm.LEVEL_TABLE + self.HOST * gm.LEVEL_TABLE_STRIDE + 4, self.ptrs[i])
        self.refresh()

    def restore(self):
        if self.insp.proc:
            self.insp.proc.w_u32(gm.LEVEL_TABLE + self.HOST * gm.LEVEL_TABLE_STRIDE + 4, _orig_level_dir_ptr(self.HOST))
            self.refresh()

    def tick(self):
        if self.insp.proc and self.table.rowCount() == 0 and self.isVisible():
            self.refresh()


class ScriptTab(QtWidgets.QWidget):
    """Call any of the 1222 native script functions with int/float/bool arguments."""

    def __init__(self, insp):
        super().__init__()
        self.insp = insp
        self.funcs = {}
        path = os.path.join(TOOLS_DIR, "docs", "script_functions.txt")
        if os.path.exists(path):
            for line in open(path, encoding="latin-1"):
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.split()
                self.funcs[parts[0]] = int(parts[2], 16)
        v = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel("Native script functions of the engine (docs/script_functions.txt). Arguments are "
                                "pushed in order; use 1.5 for float, 3 for int, true/false for bool, i:3 / f:3 to "
                                "force a type. Functions that need a script 'self' actor will fail safely.")
        note.setWordWrap(True)
        v.addWidget(note)
        self.name = QtWidgets.QComboBox()
        self.name.setEditable(True)
        self.name.addItems(sorted(self.funcs))
        self.name.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        comp = QtWidgets.QCompleter(sorted(self.funcs))
        comp.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
        comp.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self.name.setCompleter(comp)
        self.args = QtWidgets.QLineEdit()
        self.args.setPlaceholderText("arguments, comma separated, e.g.  42.8, 19.1, -97.3")
        b = QtWidgets.QPushButton("Call")
        b.clicked.connect(self.run)
        form = QtWidgets.QFormLayout()
        form.addRow("Function", self.name)
        form.addRow("Arguments", self.args)
        v.addLayout(form)
        v.addWidget(b)
        self.out = QtWidgets.QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setFont(QtGui.QFont("Consolas", 9))
        v.addWidget(self.out, 1)

    @staticmethod
    def parse_arg(s):
        s = s.strip()
        if s.lower() in ("true", "false"):
            return (T_BOOL, 1 if s.lower() == "true" else 0)
        if s[:2] in ("i:", "f:"):
            return (T_INT, int(s[2:], 0)) if s[0] == "i" else (T_FLOAT, float(s[2:]))
        if any(c in s for c in ".eE") and not s.lower().startswith("0x"):
            return (T_FLOAT, float(s))
        return (T_INT, int(s, 0))

    def run(self):
        name = self.name.currentText().strip()
        fn = self.funcs.get(name)
        if fn is None:
            try:
                fn = int(name, 16)
            except ValueError:
                self.out.appendPlainText(f"unknown function {name}")
                return
        try:
            args = [self.parse_arg(a) for a in self.args.text().split(",") if a.strip()]
            br, _ = _need(self.insp)
            (rtype, val), = br.script_batch([(fn, args)])
            kind = {0: "no result", T_INT: "int", T_FLOAT: "float", T_BOOL: "bool", 0xFF: "EXCEPTION"}.get(rtype,
                                                                                                         f"type {rtype}")
            self.out.appendPlainText(f"{name}({self.args.text()}) -> {kind}: {val if rtype else ''}")
        except Exception as e:
            self.out.appendPlainText(f"error: {e}")

    def tick(self):
        pass


class ZiplineTab(QtWidgets.QWidget):
    """Live monitor for the high-FPS zipline glitch (docs/ZIPLINE_GLITCH.md)."""

    def __init__(self, insp):
        super().__init__()
        from . import zipline as zl
        self.zl = zl
        self.insp = insp
        self.addrs, self.names, self.world = [], {}, None
        self.glitch_t0 = {}
        self._last = 0
        v = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel(
            "Ropes stay simulated after you leave them early; above ~120-200 FPS their bounce integrator is "
            "unstable and |y| grows exponentially. Touching a rope in the <b>NaN window</b> turns the player position "
            "into NaN, which fires NaN-unsafe triggers (SchoolYard: Level_EXIT -> level complete).")
        note.setWordWrap(True)
        v.addWidget(note)
        self.lamps = QtWidgets.QLabel("Drone lamps: -")
        self.lamps.setStyleSheet("font-weight: bold")
        v.addWidget(self.lamps)
        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Zipline", "Active", "Rider", "log10|y|", "Since glitch", "Status",
                                              "Jump ok"])
        self.table.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.table)
        g = QtWidgets.QGroupBox("Anomaly detector: actors with NaN / inf / huge coordinates (any class)")
        gl = QtWidgets.QVBoxLayout(g)
        self.anom = QtWidgets.QPlainTextEdit()
        self.anom.setReadOnly(True)
        self.anom.setMaximumHeight(120)
        self.anom.setFont(QtGui.QFont("Consolas", 9))
        gl.addWidget(self.anom)
        v.addWidget(g)
        from .anomalies import AnomalyWatch
        self.watch = AnomalyWatch()
        self._last_anom = 0
        row = QtWidgets.QHBoxLayout()
        self.ov = QtWidgets.QCheckBox("Show glitched ropes in the game overlay")
        self.ov.setChecked(True)
        b = QtWidgets.QPushButton("Calm all ropes (reset practice)")
        b.clicked.connect(self.calm)
        r = QtWidgets.QPushButton("Rescan")
        r.clicked.connect(lambda: setattr(self, "world", None))
        nan = QtWidgets.QPushButton("Simulate: player position = NaN")
        nan.setToolTip("Does what the zipline glitch does, instantly. Usually ends the level (or warps / crashes).")
        nan.clicked.connect(self.simulate_nan)
        row.addWidget(nan)
        row.addWidget(self.ov)
        row.addStretch(1)
        row.addWidget(b)
        row.addWidget(r)
        v.addLayout(row)

    def simulate_nan(self):
        g = self.insp.game
        if not g or not g.avatar():
            return
        nl = chr(10)
        on, total = self.zl.lamps_on(self.insp.proc)
        warn = (nl + nl + f"{len(on)} dynamic light(s) are ON right now -> the game will most likely CRASH.") if on else ""
        q = ("Set the player position to NaN (what the zipline glitch does)?" + nl +
             "Usually this fires the level switch / warp trigger." + warn)
        if QtWidgets.QMessageBox.question(self, "NaN position", q) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        nan = float("nan")
        g.teleport((nan, nan, nan), zero_velocity=False)
        self.insp.msg(f"player position set to NaN in {g.world_name()} (dynamic lights ON: {len(on)}/{total})")

    def calm(self):
        p = self.insp.proc
        if not p:
            return
        zl = self.zl
        for a in self.addrs:
            r = a + zl.ROPE
            for off in (0x68, 0x6C, 0x70, 0x74, 0x78, 0x84, 0x88, 0x8C, 0x90):
                p.w_f32(r + off, 0.0)
        self.glitch_t0.clear()

    def tick(self):
        p, g = self.insp.proc, self.insp.game
        if not p or not g or time.time() - self._last < 0.2:
            return
        self._last = time.time()
        w = g.world_name()
        if w != self.world:
            self.world = w
            self.addrs = self.zl.find_ziplines(p) if w and w.lower() != "intro" else []
            self.names = self.zl.name_ziplines(p, self.addrs, w) if self.addrs else {}
            self.glitch_t0.clear()
        rows, lines = [], []
        for a in self.addrs:
            try:
                z = self.zl.read(p, a, self.names)
            except OSError:
                continue
            glitched = z.active and z.weight == 0 and (abs(z.y) > 0.5 or not math.isfinite(z.y))
            if glitched and a not in self.glitch_t0:
                self.glitch_t0[a] = time.time()
            if not glitched and z.active == 0:
                self.glitch_t0.pop(a, None)
            st, col = self.zl.status(z.y)
            ly = math.log10(abs(z.y)) if z.y and math.isfinite(z.y) else (float("inf") if not math.isfinite(z.y) else -9)
            since = time.time() - self.glitch_t0[a] if a in self.glitch_t0 else None
            rows.append((z.name, str(z.active), f"{z.weight:g}", f"{ly:.1f}", f"{since:.1f}s" if since else "-", st,
                         "yes" if z.allow_jump else "no", col))
            if glitched and self.ov.isChecked():
                lines.append(f"\x01{col:06X}{z.name}: |y|=1e{ly:.0f}  {since or 0:.1f}s  {st}")
        try:
            on, total = self.zl.lamps_on(p)
        except OSError:
            on, total = [], 0
        if total:
            if on:
                self.lamps.setText(f"Dynamic lights ON: {len(on)} / {total}  -> NaN now (rope touch) = CRASH")
                self.lamps.setStyleSheet("font-weight: bold; color: #ff5050")
                if self.ov.isChecked() and (lines or any(self.glitch_t0.values())):
                    lines.append(f"FF4040drone lamps ON: {len(on)}  (touch = crash)")
            else:
                self.lamps.setText(f"Dynamic lights ON: 0 / {total}  (safe for NaN right now)")
                self.lamps.setStyleSheet("font-weight: bold; color: #40ff60")
        else:
            self.lamps.setText("Dynamic lights: none in this level (NaN cannot crash the lighting)")
            self.lamps.setStyleSheet("font-weight: bold")
        if time.time() - self._last_anom > 0.5:
            self._last_anom = time.time()
            try:
                found = self.watch.scan(p, w)
            except OSError:
                found = []
            txt = chr(10).join(f"{x['since']:6.1f}s  {x['kind']:9s} {x['class']:26s} @{x['addr']:08x}  "
                             f"pos {tuple(float('%.3g' % c) for c in x['pos'])}" for x in found[:40])
            self.anom.setPlainText(txt or "nothing broken")
            if found and self.ov.isChecked():
                lines.append(chr(1) + f"FF80FFanomalies: {len(found)} actor(s) with NaN/inf/huge position")
        self.insp.zip_overlay = lines
        if not self.isVisible():
            return
        self.table.setRowCount(len(rows))
        for r, vals in enumerate(rows):
            for c, val in enumerate(vals[:7]):
                it = QtWidgets.QTableWidgetItem(val)
                if c == 5:
                    it.setForeground(QtGui.QBrush(QtGui.QColor((vals[7] >> 16) & 255, (vals[7] >> 8) & 255,
                                                               vals[7] & 255)))
                self.table.setItem(r, c, it)
