"""CLTools Inspector - live research panel for Chicken Little.

    py -3 -m cltools.inspector

* time control through CLHook: FPS target, game speed, pause, frame advance, fixed step
* player info (position, velocity, speed, world) + teleport and position save slots
* memory watch list (any address / pointer chain / type), freeze values
* pushes selected values to the in-game overlay
"""
import json
import math
import os
import struct
import sys
import time

from PyQt6 import QtCore, QtGui, QtWidgets

from . import TOOLS_DIR
from .bridge import Bridge
from .mem import Process
from . import game

WATCH_FILE = os.path.join(TOOLS_DIR, "watches.json")
SLOTS_FILE = os.path.join(TOOLS_DIR, "pos_slots.json")
TYPES = ["f32", "i32", "u32", "u16", "u8", "vec3", "str"]


def parse_addr(text):
    """'0x7f00a0', '[0x8a1234]+0x30', '[[0x8a1234]+0x10]+0x30' -> (base, [offsets])"""
    t = text.replace(" ", "")
    offs = []
    depth = 0
    while t.startswith("["):
        depth += 1
        t = t[1:]
    parts = t.replace("]", "|").split("|")
    base = int(parts[0], 0)
    for p in parts[1:]:
        if p:
            offs.append(int(p.lstrip("+"), 0))
    return base, depth, offs


def resolve(proc, text):
    base, depth, offs = parse_addr(text)
    a = base
    for i in range(depth):
        a = proc.u32(a)
        if i < len(offs):
            a += offs[i]
    for o in offs[depth:]:
        a += o
    return a


def read_typed(proc, addr, typ):
    if typ == "f32":
        return f"{proc.f32(addr):.4f}"
    if typ == "i32":
        return str(proc.i32(addr))
    if typ == "u32":
        v = proc.u32(addr)
        return f"{v} (0x{v:08x})"
    if typ == "u16":
        return str(proc.u16(addr))
    if typ == "u8":
        return str(proc.u8(addr))
    if typ == "vec3":
        return "%.3f %.3f %.3f" % proc.vec3(addr)
    if typ == "str":
        return proc.cstr(addr, 64)
    return "?"


def write_typed(proc, addr, typ, text):
    if typ == "f32":
        proc.w_f32(addr, float(text))
    elif typ == "i32":
        proc.w_i32(addr, int(text, 0))
    elif typ == "u32":
        proc.w_u32(addr, int(text.split()[0], 0))
    elif typ == "u16":
        proc.write(addr, struct.pack("<H", int(text, 0)))
    elif typ == "u8":
        proc.write(addr, bytes([int(text, 0) & 0xFF]))
    elif typ == "vec3":
        proc.w_vec3(addr, [float(x) for x in text.replace(",", " ").split()])


class Inspector(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CLTools Inspector - Chicken Little")
        self.resize(780, 860)
        self.br = None
        self.proc = None
        self.game = None
        self.trail = []
        self.slots = self._load_json(SLOTS_FILE, {})
        self._build()
        from .debugtabs import DebugMenuTab, World3DTab, LevelsTab, ScriptTab, ZiplineTab
        self.zip_overlay = []
        self.extra = [DebugMenuTab(self), World3DTab(self), ZiplineTab(self), LevelsTab(self), ScriptTab(self)]
        for t, name in zip(self.extra, ["Debug menu", "World 3D", "Zipline", "Levels", "Script"]):
            self.tabs.addTab(t, name)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(50)
        for w in self._load_json(WATCH_FILE, []):
            self.add_watch(w.get("label", ""), w["addr"], w.get("type", "f32"), w.get("overlay", False))

    # ------------------------------------------------------------------ UI
    def _build(self):
        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)
        c = QtWidgets.QWidget()
        self.tabs.addTab(c, "Main")
        v = QtWidgets.QVBoxLayout(c)

        self.status = QtWidgets.QLabel("not connected")
        self.status.setStyleSheet("font-weight:bold")
        v.addWidget(self.status)

        # --- time control
        g = QtWidgets.QGroupBox("Time control (CLHook)")
        gl = QtWidgets.QGridLayout(g)
        self.fps = QtWidgets.QSpinBox()
        self.fps.setRange(0, 1000)
        self.fps.setValue(60)
        self.fps.setSuffix(" fps")
        b = QtWidgets.QPushButton("Set")
        b.clicked.connect(lambda: self.br and self.br.set_fps(self.fps.value()))
        gl.addWidget(QtWidgets.QLabel("FPS target"), 0, 0)
        gl.addWidget(self.fps, 0, 1)
        gl.addWidget(b, 0, 2)
        row = QtWidgets.QHBoxLayout()
        for pct in (100, 75, 50, 25, 10, 200):
            bb = QtWidgets.QPushButton(f"x{pct / 100:g}")
            bb.clicked.connect(lambda _, p=pct: self.br and self.br.set_speed(p))
            row.addWidget(bb)
        gl.addWidget(QtWidgets.QLabel("Game speed"), 1, 0)
        gl.addLayout(row, 1, 1, 1, 3)
        row2 = QtWidgets.QHBoxLayout()
        self.btn_pause = QtWidgets.QPushButton("Pause (F5)")
        self.btn_pause.clicked.connect(lambda: self.br and self.br.pause(not self.br.b.paused))
        row2.addWidget(self.btn_pause)
        for n in (1, 5, 30):
            bb = QtWidgets.QPushButton(f"Step {n}")
            bb.clicked.connect(lambda _, k=n: self.br and self.br.step(k))
            row2.addWidget(bb)
        self.chk_fixed = QtWidgets.QCheckBox("Fixed step (dt = 1/fps)")
        self.chk_fixed.toggled.connect(lambda on: self.br and setattr(self.br.b, "fixedStep", int(on)))
        row2.addWidget(self.chk_fixed)
        gl.addLayout(row2, 2, 0, 1, 4)
        row3 = QtWidgets.QHBoxLayout()
        self.chk_ov = QtWidgets.QCheckBox("In-game overlay")
        self.chk_ov.setChecked(True)
        self.chk_ov.toggled.connect(lambda on: self.br and setattr(self.br.b, "overlayOn", int(on)))
        row3.addWidget(self.chk_ov)
        bs = QtWidgets.QPushButton("Screenshot")
        bs.clicked.connect(self.screenshot)
        row3.addWidget(bs)
        row3.addStretch(1)
        gl.addLayout(row3, 3, 0, 1, 4)
        v.addWidget(g)

        # --- player
        g = QtWidgets.QGroupBox("Player")
        gl = QtWidgets.QGridLayout(g)
        self.lbl_world = QtWidgets.QLabel("-")
        self.lbl_pos = QtWidgets.QLabel("-")
        self.lbl_vel = QtWidgets.QLabel("-")
        self.lbl_extra = QtWidgets.QLabel("-")
        for lbl in (self.lbl_pos, self.lbl_vel, self.lbl_extra):
            lbl.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setFont(QtGui.QFont("Consolas", 10))
        gl.addWidget(QtWidgets.QLabel("World"), 0, 0)
        gl.addWidget(self.lbl_world, 0, 1, 1, 3)
        gl.addWidget(QtWidgets.QLabel("Position"), 1, 0)
        gl.addWidget(self.lbl_pos, 1, 1, 1, 3)
        gl.addWidget(QtWidgets.QLabel("Velocity"), 2, 0)
        gl.addWidget(self.lbl_vel, 2, 1, 1, 3)
        gl.addWidget(QtWidgets.QLabel("State"), 3, 0)
        gl.addWidget(self.lbl_extra, 3, 1, 1, 3)
        self.tp = [QtWidgets.QDoubleSpinBox() for _ in range(3)]
        tpl = QtWidgets.QHBoxLayout()
        for s, n in zip(self.tp, "XYZ"):
            s.setRange(-100000, 100000)
            s.setDecimals(3)
            s.setPrefix(n + " ")
            tpl.addWidget(s)
        bget = QtWidgets.QPushButton("<- current")
        bget.clicked.connect(self.tp_from_current)
        btp = QtWidgets.QPushButton("Teleport")
        btp.clicked.connect(lambda: self.teleport([s.value() for s in self.tp]))
        tpl.addWidget(bget)
        tpl.addWidget(btp)
        gl.addLayout(tpl, 4, 0, 1, 4)
        sl = QtWidgets.QHBoxLayout()
        self.slot_combo = QtWidgets.QComboBox()
        self.slot_combo.setEditable(True)
        self.slot_combo.addItems(sorted(self.slots))
        bsave = QtWidgets.QPushButton("Save pos")
        bsave.clicked.connect(self.save_slot)
        bload = QtWidgets.QPushButton("Load pos")
        bload.clicked.connect(self.load_slot)
        sl.addWidget(QtWidgets.QLabel("Slot"))
        sl.addWidget(self.slot_combo, 1)
        sl.addWidget(bsave)
        sl.addWidget(bload)
        gl.addLayout(sl, 5, 0, 1, 4)
        v.addWidget(g)

        # --- watches
        g = QtWidgets.QGroupBox("Memory watch  (address: 0x1234 | [0x8a0000]+0x30 | [[0x8a0000]+0x10]+0x4)")
        gl = QtWidgets.QVBoxLayout(g)
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Label", "Address", "Type", "Value", "Overlay"])
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._watch_edited)
        gl.addWidget(self.table)
        row = QtWidgets.QHBoxLayout()
        self.w_label = QtWidgets.QLineEdit()
        self.w_label.setPlaceholderText("label")
        self.w_addr = QtWidgets.QLineEdit()
        self.w_addr.setPlaceholderText("address / pointer chain")
        self.w_type = QtWidgets.QComboBox()
        self.w_type.addItems(TYPES)
        badd = QtWidgets.QPushButton("Add")
        badd.clicked.connect(lambda: self.add_watch(self.w_label.text(), self.w_addr.text(), self.w_type.currentText()))
        bdel = QtWidgets.QPushButton("Remove selected")
        bdel.clicked.connect(self.remove_watch)
        for w in (self.w_label, self.w_addr, self.w_type, badd, bdel):
            row.addWidget(w)
        gl.addLayout(row)
        v.addWidget(g, 1)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        v.addWidget(self.log)

    # ------------------------------------------------------------- helpers
    def _load_json(self, p, default):
        try:
            with open(p, "r") as f:
                return json.load(f)
        except Exception:
            return default

    def _save_watches(self):
        out = []
        for r in range(self.table.rowCount()):
            out.append({"label": self.table.item(r, 0).text(), "addr": self.table.item(r, 1).text(),
                        "type": self.table.item(r, 2).text(),
                        "overlay": self.table.item(r, 4).checkState() == QtCore.Qt.CheckState.Checked})
        with open(WATCH_FILE, "w") as f:
            json.dump(out, f, indent=1)

    def msg(self, s):
        self.log.appendPlainText(time.strftime("%H:%M:%S ") + s)

    def add_watch(self, label, addr, typ, overlay=False):
        if not addr:
            return
        self.table.blockSignals(True)
        r = self.table.rowCount()
        self.table.insertRow(r)
        for col, val in enumerate([label, addr, typ, ""]):
            it = QtWidgets.QTableWidgetItem(val)
            if col in (1, 2):
                it.setFlags(it.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, col, it)
        it = QtWidgets.QTableWidgetItem()
        it.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsEnabled)
        it.setCheckState(QtCore.Qt.CheckState.Checked if overlay else QtCore.Qt.CheckState.Unchecked)
        self.table.setItem(r, 4, it)
        self.table.blockSignals(False)
        self._save_watches()

    def remove_watch(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        self._save_watches()

    def _watch_edited(self, item):
        if item.column() == 3 and self.proc:  # write value
            r = item.row()
            try:
                a = resolve(self.proc, self.table.item(r, 1).text())
                write_typed(self.proc, a, self.table.item(r, 2).text(), item.text())
                self.msg(f"wrote {item.text()} -> 0x{a:08x}")
            except Exception as e:
                self.msg(f"write failed: {e}")
        self._save_watches()

    # --------------------------------------------------------------- actions
    def screenshot(self):
        if self.br:
            try:
                self.msg("screenshot: " + self.br.screenshot())
            except Exception as e:
                self.msg(str(e))

    def tp_from_current(self):
        if self.game and self.game.player_pos():
            for s, val in zip(self.tp, self.game.player_pos()):
                s.setValue(val)

    def teleport(self, pos):
        if not self.game:
            return
        try:
            self.game.teleport_snap(pos, self.br)
            self.msg("teleport -> %.2f %.2f %.2f" % tuple(pos))
        except Exception as e:
            self.msg(f"teleport failed: {e}")

    def save_slot(self):
        if not self.game or not self.game.player_pos():
            return
        name = self.slot_combo.currentText() or f"slot{len(self.slots) + 1}"
        self.slots[name] = {"world": self.game.world_name(), "pos": list(self.game.player_pos())}
        with open(SLOTS_FILE, "w") as f:
            json.dump(self.slots, f, indent=1)
        if self.slot_combo.findText(name) < 0:
            self.slot_combo.addItem(name)
        self.msg(f"saved {name}")

    def load_slot(self):
        s = self.slots.get(self.slot_combo.currentText())
        if s:
            self.teleport(s["pos"])

    # ------------------------------------------------------------------ tick
    def connect(self):
        if not self.br:
            try:
                self.br = Bridge()
                self.msg("bridge connected")
            except OSError:
                pass
        if not self.proc:
            try:
                self.proc = Process()
                self.game = game.Game(self.proc)
                self.msg(f"attached to Chick.exe pid {self.proc.pid}")
            except OSError:
                pass

    def tick(self):
        if not self.br or not self.proc:
            self.connect()
        if self.proc and not self.proc.alive():
            self.msg("game exited")
            self.proc, self.game, self.br = None, None, None
        if self.br:
            b = self.br.b
            self.status.setText(f"connected  |  {b.fps:5.1f} fps  |  frame {b.frame}  |  target {b.fpsTarget}  |  "
                                f"speed x{b.speedPct / 100:g}  |  {'PAUSED' if b.paused else 'running'}  |  "
                                f"{b.bbWidth}x{b.bbHeight} {'windowed' if b.windowed else 'fullscreen'}")
            self.btn_pause.setText("Resume (F5)" if b.paused else "Pause (F5)")
        else:
            self.status.setText("waiting for game (start Chicken Little with CLTools d3d8.dll installed)")
        overlay_lines = []
        if self.game:
            try:
                info = self.game.snapshot()
            except Exception as e:
                info = {"error": str(e)}
            self.lbl_world.setText(str(info.get("world", "-")))
            p = info.get("pos")
            if p:
                self.lbl_pos.setText("%10.3f %10.3f %10.3f" % p)
                overlay_lines.append("\x01" "80FF80pos %8.3f %8.3f %8.3f" % p)
            vel = info.get("vel")
            if vel:
                hs = math.hypot(vel[0], vel[2])
                self.lbl_vel.setText("%10.3f %10.3f %10.3f   |h| %.3f  |v| %.3f" % (vel + (hs, math.sqrt(sum(x * x for x in vel)))))
                overlay_lines.append("\x01" "80C0FFvel %8.3f %8.3f %8.3f  h %.3f" % (vel + (hs,)))
            self.lbl_extra.setText(info.get("extra", "") or info.get("error", "-"))
            if info.get("overlay"):
                overlay_lines += info["overlay"]
        # watches
        if self.proc:
            self.table.blockSignals(True)
            for r in range(self.table.rowCount()):
                it = self.table.item(r, 3)
                if self.table.state() == QtWidgets.QAbstractItemView.State.EditingState and self.table.currentRow() == r:
                    continue
                try:
                    a = resolve(self.proc, self.table.item(r, 1).text())
                    val = read_typed(self.proc, a, self.table.item(r, 2).text())
                except Exception:
                    val = "??"
                it.setText(val)
                if self.table.item(r, 4).checkState() == QtCore.Qt.CheckState.Checked:
                    overlay_lines.append(f"{self.table.item(r, 0).text() or self.table.item(r, 1).text()}: {val}")
            self.table.blockSignals(False)
        overlay_lines += getattr(self, "zip_overlay", [])
        overlay_lines += getattr(self, "drone_overlay", [])
        if self.br:
            self.br.set_overlay("\n".join(overlay_lines))
        for t in getattr(self, "extra", []):
            try:
                t.tick()
            except Exception as e:
                self.msg(f"{type(t).__name__}: {e}")


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = Inspector()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
