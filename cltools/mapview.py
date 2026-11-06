"""CLTools Map Viewer / Editor for Chicken Little.

    py -3 -m cltools.mapview [world]

Top-down map of a world:
  * world geometry: AABBs of every placed instance from <world>.DBL (coloured by height)
  * objects from <world>.OA (pickups, triggers, checkpoints, enemies...) - hover for name, click for attributes
  * player start points from data/worlds/<world>/player.var - drag to move, "Save starts" writes the file
  * live player position, heading and trail when the game is running
  * double-click: teleport the player there;  Shift+click two points: measure distance
"""
import colorsys
import hashlib
import math
import os
import shutil
import sys
import time

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtGui, QtWidgets

from . import GAME_DIR, TOOLS_DIR
from . import dbl, oa, var
from .mem import Process
from . import game as gm

pg.setConfigOptions(antialias=True, background="#15171c", foreground="#d0d0d0")


def type_color(t):
    h = int(hashlib.md5(t.encode()).hexdigest()[:6], 16) / 0xFFFFFF
    r, g, b = colorsys.hsv_to_rgb(h, 0.65, 1.0)
    return QtGui.QColor(int(r * 255), int(g * 255), int(b * 255))


FIXED_COLORS = {"acorn": "#ffd23f", "checkpoint": "#3fff6a", "card": "#ff9f1c", "egg": "#ffffff"}


def category_color(t):
    tl = t.lower()
    for k, c in FIXED_COLORS.items():
        if k in tl:
            return QtGui.QColor(c)
    if "trg" in tl or "trigger" in tl:
        return QtGui.QColor("#38c8ff")
    if "cam" in tl:
        return QtGui.QColor("#9090a0")
    return type_color(t)


def height_color(y, lo, hi, alpha=150):
    t = 0.0 if hi <= lo else min(1.0, max(0.0, (y - lo) / (hi - lo)))
    r, g, b = colorsys.hsv_to_rgb(0.66 - 0.66 * t, 0.55, 0.35 + 0.5 * t)
    return QtGui.QColor(int(r * 255), int(g * 255), int(b * 255), alpha)


class StartMarker(pg.TargetItem):
    pass


class MapView(QtWidgets.QMainWindow):
    def __init__(self, world=None):
        super().__init__()
        self.setWindowTitle("CLTools Map Viewer - Chicken Little")
        self.resize(1400, 900)
        self.proc = None
        self.game = None
        self.world = None
        self.instances = []
        self.boxes = []
        self.trail = []
        self.measure = []
        self.box_items = []
        self.start_items = []
        self.flip_z = True
        self._build()
        worlds = oa.world_dirs()
        self.world_combo.addItems(worlds)
        if world:
            self._select_world(world)
        else:
            self.load_world(self.world_combo.currentText())
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(50)

    # ------------------------------------------------------------------ UI
    def _build(self):
        split = QtWidgets.QSplitter()
        self.setCentralWidget(split)
        self.plot = pg.PlotWidget()
        self.plot.setAspectLocked(True)
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.plot.setLabel("bottom", "X")
        self.plot.setLabel("left", "-Z" if self.flip_z else "Z")
        self.vb = self.plot.getViewBox()
        split.addWidget(self.plot)

        side = QtWidgets.QWidget()
        sl = QtWidgets.QVBoxLayout(side)
        split.addWidget(side)
        split.setSizes([1050, 350])

        row = QtWidgets.QHBoxLayout()
        self.world_combo = QtWidgets.QComboBox()
        self.world_combo.currentTextChanged.connect(self.load_world)
        row.addWidget(QtWidgets.QLabel("World"))
        row.addWidget(self.world_combo, 1)
        sl.addLayout(row)
        self.chk_follow_world = QtWidgets.QCheckBox("Follow game's current world")
        self.chk_follow_world.setChecked(True)
        sl.addWidget(self.chk_follow_world)

        g = QtWidgets.QGroupBox("Layers")
        gl = QtWidgets.QGridLayout(g)
        self.chk_boxes = QtWidgets.QCheckBox("Geometry (DBL boxes)")
        self.chk_objs = QtWidgets.QCheckBox("Objects (.OA)")
        self.chk_starts = QtWidgets.QCheckBox("Player starts")
        self.chk_player = QtWidgets.QCheckBox("Live player")
        self.chk_trail = QtWidgets.QCheckBox("Trail")
        self.chk_follow = QtWidgets.QCheckBox("Camera follows player")
        self.chk_drones = QtWidgets.QCheckBox("Enemy drones (live)")
        for i, c in enumerate((self.chk_boxes, self.chk_objs, self.chk_starts, self.chk_player, self.chk_trail,
                               self.chk_follow, self.chk_drones)):
            c.setChecked(c is not self.chk_follow)
            c.toggled.connect(self._layers_changed)
            gl.addWidget(c, i // 2, i % 2)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Height slice Y <="))
        self.slice = QtWidgets.QDoubleSpinBox()
        self.slice.setRange(-10000, 10000)
        self.slice.setValue(10000)
        self.slice.setDecimals(1)
        self.slice.valueChanged.connect(self._draw_boxes)
        row.addWidget(self.slice)
        bsl = QtWidgets.QPushButton("@ player")
        bsl.clicked.connect(self._slice_at_player)
        row.addWidget(bsl)
        gl.addLayout(row, 4, 0, 1, 2)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Hide boxes larger than (m2)"))
        self.max_area = QtWidgets.QSpinBox()
        self.max_area.setRange(10, 10000000)
        self.max_area.setValue(6000)
        self.max_area.valueChanged.connect(self._draw_boxes)
        row.addWidget(self.max_area)
        gl.addLayout(row, 5, 0, 1, 2)
        sl.addWidget(g)

        g = QtWidgets.QGroupBox("Object types (filter)")
        gl = QtWidgets.QVBoxLayout(g)
        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText("search name / type / attribute...")
        self.filter.textChanged.connect(self._draw_objects)
        gl.addWidget(self.filter)
        self.type_list = QtWidgets.QListWidget()
        self.type_list.itemChanged.connect(self._draw_objects)
        gl.addWidget(self.type_list)
        row = QtWidgets.QHBoxLayout()
        ball = QtWidgets.QPushButton("All")
        ball.clicked.connect(lambda: self._set_all_types(True))
        bnone = QtWidgets.QPushButton("None")
        bnone.clicked.connect(lambda: self._set_all_types(False))
        row.addWidget(ball)
        row.addWidget(bnone)
        gl.addLayout(row)
        sl.addWidget(g, 2)

        g = QtWidgets.QGroupBox("Selection")
        gl = QtWidgets.QVBoxLayout(g)
        self.info = QtWidgets.QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setFont(QtGui.QFont("Consolas", 9))
        gl.addWidget(self.info)
        btp = QtWidgets.QPushButton("Teleport player to selection")
        btp.clicked.connect(self._tp_selected)
        gl.addWidget(btp)
        sl.addWidget(g, 2)

        g = QtWidgets.QGroupBox("Edit")
        gl = QtWidgets.QVBoxLayout(g)
        bss = QtWidgets.QPushButton("Save player starts -> player.var")
        bss.clicked.connect(self.save_starts)
        gl.addWidget(bss)
        bsp = QtWidgets.QPushButton("Set start 0 = current player position")
        bsp.clicked.connect(self._start_from_player)
        gl.addWidget(bsp)
        row = QtWidgets.QHBoxLayout()
        bct = QtWidgets.QPushButton("Clear trail")
        bct.clicked.connect(lambda: self.trail.clear())
        bpng = QtWidgets.QPushButton("Export PNG")
        bpng.clicked.connect(self.export_png)
        row.addWidget(bct)
        row.addWidget(bpng)
        gl.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Teleport height"))
        self.tp_mode = QtWidgets.QComboBox()
        self.tp_mode.addItems(["current Y + 1", "top of geometry", "keep Y"])
        row.addWidget(self.tp_mode, 1)
        gl.addLayout(row)
        sl.addWidget(g)

        self.status = QtWidgets.QLabel("")
        self.statusBar().addWidget(self.status, 1)

        # plot items
        self.obj_scatter = pg.ScatterPlotItem(size=8, pen=pg.mkPen("#000000", width=0.5), hoverable=True,
                                              hoverSize=13, tip=self._tip)
        self.obj_scatter.sigClicked.connect(self._obj_clicked)
        self.plot.addItem(self.obj_scatter)
        self.trail_item = pg.PlotDataItem(pen=pg.mkPen("#ff4fd8", width=2))
        self.plot.addItem(self.trail_item)
        self.player_item = pg.ScatterPlotItem(size=14, brush=pg.mkBrush("#ff2b2b"), pen=pg.mkPen("w", width=2))
        self.plot.addItem(self.player_item)
        self.heading_item = pg.PlotDataItem(pen=pg.mkPen("#ff2b2b", width=3))
        self.plot.addItem(self.heading_item)
        self.measure_item = pg.PlotDataItem(pen=pg.mkPen("#ffff00", width=2, style=QtCore.Qt.PenStyle.DashLine),
                                            symbol="x", symbolBrush="#ffff00")
        self.plot.addItem(self.measure_item)
        self.drone_item = pg.ScatterPlotItem(size=14, symbol="t", pen=pg.mkPen("#000000", width=1), hoverable=True,
                                             tip=lambda x, y, data: data)
        self.drone_item.setZValue(18)
        self.plot.addItem(self.drone_item)
        from .drones import DroneTracker
        self.tracker = DroneTracker()
        self._drone_t = 0
        self.sel_item = pg.ScatterPlotItem(size=20, brush=None, pen=pg.mkPen("#ffffff", width=2), symbol="o")
        self.plot.addItem(self.sel_item)
        for it in (self.obj_scatter, self.trail_item, self.player_item, self.heading_item, self.sel_item):
            it.setZValue(10)
        self.player_item.setZValue(20)
        self.heading_item.setZValue(20)
        self.plot.scene().sigMouseMoved.connect(self._mouse_moved)
        self.plot.scene().sigMouseClicked.connect(self._mouse_clicked)
        self.selected = None

    # ----------------------------------------------------------- coords
    def to_plot(self, x, z):
        return x, (-z if self.flip_z else z)

    def from_plot(self, px, py):
        return px, (-py if self.flip_z else py)

    # ----------------------------------------------------------- loading
    def _select_world(self, w):
        for i in range(self.world_combo.count()):
            if self.world_combo.itemText(i).lower() == w.lower():
                self.world_combo.setCurrentIndex(i)
                return True
        return False

    def load_world(self, world):
        if not world:
            return
        self.world = world
        t = time.time()
        self.boxes, self.bbox = dbl.load_world_boxes(world)
        self.instances = [i for i in oa.load_world_instances(world) if i.pos]
        self.starts = [list(s) for s in var.player_starts(world)]
        types = sorted({i.type for i in self.instances})
        self.type_list.blockSignals(True)
        self.type_list.clear()
        counts = {}
        for i in self.instances:
            counts[i.type] = counts.get(i.type, 0) + 1
        for tname in types:
            it = QtWidgets.QListWidgetItem(f"{tname}  ({counts[tname]})")
            it.setData(QtCore.Qt.ItemDataRole.UserRole, tname)
            it.setFlags(it.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.CheckState.Checked)
            it.setForeground(QtGui.QBrush(category_color(tname)))
            self.type_list.addItem(it)
        self.type_list.blockSignals(False)
        if self.boxes:
            ys = np.array([b.bmax[1] for b in self.boxes])
            self.ylo, self.yhi = float(np.percentile(ys, 2)), float(np.percentile(ys, 98))
        else:
            self.ylo, self.yhi = 0, 1
        self.trail.clear()
        self._draw_boxes()
        self._draw_objects()
        self._draw_starts()
        self.plot.autoRange()
        self.status.setText(f"{world}: {len(self.boxes)} geometry boxes, {len(self.instances)} objects, "
                            f"{len(self.starts)} starts  ({time.time() - t:.2f}s)")

    def _set_all_types(self, on):
        self.type_list.blockSignals(True)
        for i in range(self.type_list.count()):
            self.type_list.item(i).setCheckState(QtCore.Qt.CheckState.Checked if on else QtCore.Qt.CheckState.Unchecked)
        self.type_list.blockSignals(False)
        self._draw_objects()

    def _layers_changed(self):
        self._draw_boxes()
        self._draw_objects()
        self._draw_starts()

    # ----------------------------------------------------------- drawing
    def _draw_boxes(self):
        for it in self.box_items:
            self.plot.removeItem(it)
        self.box_items = []
        if not self.chk_boxes.isChecked() or not self.boxes:
            return
        lim = self.slice.value()
        max_area = self.max_area.value()
        boxes = [b for b in self.boxes if b.bmin[1] <= lim]
        boxes.sort(key=lambda b: min(b.bmax[1], lim))
        # group into a few height buckets -> one QGraphicsPathItem per bucket (fast)
        nb = 24
        buckets = [QtGui.QPainterPath() for _ in range(nb)]
        for b in boxes:
            top = min(b.bmax[1], lim)
            t = 0 if self.yhi <= self.ylo else (top - self.ylo) / (self.yhi - self.ylo)
            k = max(0, min(nb - 1, int(t * nb)))
            x0, z0, x1, z1 = b.bmin[0], b.bmin[2], b.bmax[0], b.bmax[2]
            if (x1 - x0) * (z1 - z0) > max_area:  # skip giant backdrop boxes
                continue
            px0, py0 = self.to_plot(x0, z0)
            px1, py1 = self.to_plot(x1, z1)
            buckets[k].addRect(QtCore.QRectF(min(px0, px1), min(py0, py1), abs(px1 - px0), abs(py1 - py0)))
        for k, path in enumerate(buckets):
            if path.isEmpty():
                continue
            y = self.ylo + (k + 0.5) / nb * (self.yhi - self.ylo)
            item = QtWidgets.QGraphicsPathItem(path)
            item.setBrush(QtGui.QBrush(height_color(y, self.ylo, self.yhi, 110)))
            pen = QtGui.QPen(height_color(y, self.ylo, self.yhi, 200))
            pen.setCosmetic(True)
            pen.setWidthF(0.8)
            item.setPen(pen)
            item.setZValue(-100 + k)
            self.plot.addItem(item)
            self.box_items.append(item)

    def _visible_types(self):
        out = set()
        for i in range(self.type_list.count()):
            it = self.type_list.item(i)
            if it.checkState() == QtCore.Qt.CheckState.Checked:
                out.add(it.data(QtCore.Qt.ItemDataRole.UserRole))
        return out

    def _draw_objects(self):
        if not self.chk_objs.isChecked():
            self.obj_scatter.setData([])
            return
        vis = self._visible_types()
        f = self.filter.text().lower().strip()
        spots = []
        for inst in self.instances:
            if inst.type not in vis:
                continue
            if f and f not in inst.name.lower() and f not in inst.type.lower() and \
                    not any(f in f"{k}={v}".lower() for k, v in inst.attrs.items()):
                continue
            px, py = self.to_plot(inst.pos[0], inst.pos[2])
            spots.append({"pos": (px, py), "data": inst, "brush": pg.mkBrush(category_color(inst.type))})
        self.obj_scatter.setData(spots)

    def _draw_starts(self):
        for it in self.start_items:
            self.plot.removeItem(it)
        self.start_items = []
        if not self.chk_starts.isChecked():
            return
        for i, (idx, pos, rot) in enumerate(self.starts):
            px, py = self.to_plot(pos[0], pos[2])
            t = pg.TargetItem(pos=(px, py), size=18, movable=True, pen=pg.mkPen("#00ff9c", width=2),
                              label=f"start{idx}", labelOpts={"color": "#00ff9c", "offset": (8, -8)})
            t.sigPositionChangeFinished.connect(lambda item, k=i: self._start_moved(k, item))
            t.setZValue(15)
            self.plot.addItem(t)
            self.start_items.append(t)

    def _start_moved(self, k, item):
        p = item.pos()
        x, z = self.from_plot(p.x(), p.y())
        idx, pos, rot = self.starts[k]
        self.starts[k] = [idx, (round(x, 3), pos[1], round(z, 3)), rot]
        self.status.setText(f"start{idx} -> {x:.3f} {pos[1]:.3f} {z:.3f}  (not saved)")

    # ----------------------------------------------------------- interaction
    def _tip(self, x, y, data):
        inst = data
        return f"{inst.name}\n{inst.type}\n{inst.pos[0]:.2f} {inst.pos[1]:.2f} {inst.pos[2]:.2f}"

    def _obj_clicked(self, item, points, ev=None):
        if not points:
            return
        inst = points[0].data()
        self.selected = inst
        px, py = self.to_plot(inst.pos[0], inst.pos[2])
        self.sel_item.setData([px], [py])
        lines = [f"{inst.name}  (#{inst.index})", f"type: {inst.type}",
                 "pos: %.3f %.3f %.3f" % inst.pos, ""]
        lines += [f"{k} = {v}" for k, v in inst.attrs.items()]
        self.info.setPlainText("\n".join(lines))

    def _mouse_moved(self, pos):
        p = self.vb.mapSceneToView(pos)
        x, z = self.from_plot(p.x(), p.y())
        msg = f"X {x:9.2f}   Z {z:9.2f}"
        top = self._top_at(x, z)
        if top is not None:
            msg += f"   geometry top Y {top:.2f}"
        if len(self.measure) == 1:
            mx, mz = self.measure[0]
            msg += f"   dist {math.hypot(x - mx, z - mz):.2f}"
        self.status.setText(msg)

    def _mouse_clicked(self, ev):
        p = self.vb.mapSceneToView(ev.scenePos())
        x, z = self.from_plot(p.x(), p.y())
        if ev.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier:
            self.measure = (self.measure + [(x, z)])[-2:] if len(self.measure) < 2 else [(x, z)]
            pts = [self.to_plot(a, b) for a, b in self.measure]
            self.measure_item.setData([q[0] for q in pts], [q[1] for q in pts])
            if len(self.measure) == 2:
                (ax, az), (bx, bz) = self.measure
                self.statusBar().showMessage(f"distance {math.hypot(bx - ax, bz - az):.3f}", 10000)
            ev.accept()
            return
        if ev.double():
            self.teleport_xz(x, z)
            ev.accept()

    def _top_at(self, x, z, below=None):
        best = None
        for b in self.boxes:
            if b.bmin[0] <= x <= b.bmax[0] and b.bmin[2] <= z <= b.bmax[2]:
                if (b.bmax[0] - b.bmin[0]) * (b.bmax[2] - b.bmin[2]) > self.max_area.value():
                    continue
                y = b.bmax[1]
                if below is not None and y > below:
                    continue
                if best is None or y > best:
                    best = y
        return best

    def _update_drones(self):
        if not self.chk_drones.isChecked() or not self.game:
            self.drone_item.setData([])
            return
        if time.time() - self._drone_t < 0.25:
            return
        self._drone_t = time.time()
        from . import drones as dr
        try:
            ds = self.tracker.update(self.proc, self.world, include_corn=True)
        except OSError:
            return
        spots = []
        for d in ds:
            c = dr.COLORS[d.state]
            px, py = self.to_plot(d.pos[0], d.pos[2])
            spots.append({"pos": (px, py), "brush": pg.mkBrush((c >> 16) & 255, (c >> 8) & 255, c & 255, 230),
                          "data": f"{d.name}: {d.state}", "symbol": "x" if d.state == dr.DEAD else "t"})
        self.drone_item.setData(spots)

    def teleport_xz(self, x, z, y=None):
        if not self.game or not self.game.avatar():
            self.statusBar().showMessage("game not running / no player", 4000)
            return
        cur = self.game.player_pos()
        if y is None:
            mode = self.tp_mode.currentIndex()
            if mode == 0:
                y = cur[1] + 1.0
            elif mode == 1:
                top = self._top_at(x, z)
                y = (top + 0.5) if top is not None else cur[1] + 1.0
            else:
                y = cur[1]
        br = None
        try:
            from .bridge import Bridge
            br = Bridge()
        except Exception:
            pass
        self.game.teleport_snap((x, y, z), br)
        self.statusBar().showMessage(f"teleported to {x:.2f} {y:.2f} {z:.2f}", 4000)

    def _tp_selected(self):
        if self.selected:
            x, y, z = self.selected.pos
            self.teleport_xz(x, z, y + 0.5)

    def _slice_at_player(self):
        if self.game and self.game.player_pos():
            self.slice.setValue(self.game.player_pos()[1] + 2.0)

    def _start_from_player(self):
        if not self.game or not self.game.player_pos():
            return
        p = self.game.player_pos()
        yaw = self.game.player_yaw_deg() or 0.0
        if not self.starts:
            self.starts = [[0, p, yaw]]
        else:
            self.starts[0] = [self.starts[0][0], tuple(round(v, 3) for v in p), round(yaw, 1)]
        self._draw_starts()
        self.status.setText("start0 = player position (not saved)")

    def save_starts(self):
        path = var.world_var_path(self.world, "player.var")
        if not os.path.exists(path):
            QtWidgets.QMessageBox.warning(self, "player.var", f"{path} not found")
            return
        bak = path + ".orig"
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        with open(path, "r", encoding="latin-1") as f:
            ctx = var.parse_var(f.read())
        items = ctx.get("player", [])
        d = {k: v for k, v in items}
        for idx, pos, rot in self.starts:
            d[f"startPos{idx}"] = [float(v) for v in pos]
            d[f"startRot{idx}"] = rot
        keys = [k for k, _ in items] + [k for k in d if k not in {k for k, _ in items}]
        ctx["player"] = [(k, d[k]) for k in keys]
        with open(path, "w", encoding="latin-1", newline="") as f:
            f.write(var.write_var(ctx))
        self.statusBar().showMessage(f"saved {path} (backup {os.path.basename(bak)}) - restart the level to apply", 8000)

    def export_png(self):
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export map", os.path.join(TOOLS_DIR, f"{self.world}.png"),
                                                     "PNG (*.png)")
        if p:
            import pyqtgraph.exporters
            ex = pyqtgraph.exporters.ImageExporter(self.plot.plotItem)
            ex.parameters()["width"] = 3000
            ex.export(p)

    # ------------------------------------------------------------------ live
    def tick(self):
        if not self.proc:
            try:
                self.proc = Process()
                self.game = gm.Game(self.proc)
            except OSError:
                self.player_item.setData([])
                return
        if not self.proc.alive():
            self.proc = self.game = None
            return
        try:
            w = self.game.world_name()
            if w and self.chk_follow_world.isChecked() and (not self.world or w.lower() != self.world.lower()):
                self._select_world(w)
            pos = self.game.player_pos() if self.game.avatar() else None
        except OSError:
            pos = None
        self._update_drones()
        if not pos or not self.chk_player.isChecked():
            self.player_item.setData([])
            self.heading_item.setData([])
            return
        px, py = self.to_plot(pos[0], pos[2])
        self.player_item.setData([px], [py])
        yaw = self.game.player_yaw_deg() or 0.0
        dx, dz = math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
        hx, hy = self.to_plot(pos[0] + dx * 2.0, pos[2] + dz * 2.0)
        self.heading_item.setData([px, hx], [py, hy])
        if self.chk_trail.isChecked():
            if not self.trail or math.hypot(self.trail[-1][0] - px, self.trail[-1][1] - py) > 0.05:
                self.trail.append((px, py))
                self.trail = self.trail[-6000:]
            self.trail_item.setData([t[0] for t in self.trail], [t[1] for t in self.trail])
        else:
            self.trail_item.setData([])
        if self.chk_follow.isChecked():
            r = self.vb.viewRange()
            w2 = (r[0][1] - r[0][0]) / 2
            h2 = (r[1][1] - r[1][0]) / 2
            self.vb.setRange(xRange=(px - w2, px + w2), yRange=(py - h2, py + h2), padding=0)


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MapView(sys.argv[1] if len(sys.argv) > 1 else None)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
