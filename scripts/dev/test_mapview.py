import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6 import QtWidgets, QtCore
from cltools.mapview import MapView
app = QtWidgets.QApplication(sys.argv)
w = MapView(sys.argv[1] if len(sys.argv) > 1 else "SchoolYard")
w.resize(1400, 900); w.show()
for i in range(10):
    app.processEvents(); w.tick(); time.sleep(0.05)
if w.game and w.game.player_pos():
    p = w.game.player_pos(); px, py = w.to_plot(p[0], p[2])
    if "--zoom" in sys.argv:
        w.vb.setRange(xRange=(px - 40, px + 40), yRange=(py - 25, py + 25), padding=0)
app.processEvents()
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screens", "mapview.png")
w.grab().save(out); print(out, w.status.text())
