import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6 import QtWidgets
from cltools.inspector import Inspector
from cltools.bridge import Bridge
from PIL import Image
app = QtWidgets.QApplication(sys.argv)
w = Inspector(); w.show()
for i in range(20):
    app.processEvents(); w.tick(); time.sleep(0.05)
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
w.grab().save(os.path.join(here, "screens", "inspector.png"))
p = Bridge().screenshot(); Image.open(p).save(os.path.join(here, "screens", "last.png")); os.remove(p)
print("ok", w.lbl_pos.text(), "|", w.lbl_extra.text())
