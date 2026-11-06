import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6 import QtWidgets
from cltools.inspector import Inspector
from PIL import Image
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = QtWidgets.QApplication(sys.argv)
w = Inspector(); w.show()
for i in range(10): app.processEvents(); w.tick(); time.sleep(0.05)
dbg, world, levels, script = w.extra
world.enabled.setChecked(True); world.scan()
for idx in range(5):
    w.tabs.setCurrentIndex(idx)
    for i in range(8): app.processEvents(); w.tick(); time.sleep(0.06)
    w.grab().save(os.path.join(here, "screens", f"tab{idx}.png"))
script.name.setCurrentText("Avatar__GetLives"); script.run()
script.name.setCurrentText("FindGroundXYZ"); p = w.game.player_pos(); script.args.setText(f"{p[0]:.2f}, {p[1]+2:.2f}, {p[2]:.2f}"); script.run()
print(script.out.toPlainText())
w.tabs.setCurrentIndex(2)
for i in range(6): app.processEvents(); w.tick(); time.sleep(0.06)
time.sleep(0.4)
pth = w.br.screenshot(); Image.open(pth).save(os.path.join(here, "screens", "last.png")); os.remove(pth)
print(w.log.toPlainText()[-600:])
