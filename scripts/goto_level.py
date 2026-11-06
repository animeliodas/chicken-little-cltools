"""Dev helper: launch the game if needed, load save slot 1 and enter level N via "Select Level".
    py -3 scripts/goto_level.py [N=1]"""
import os, subprocess, sys, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from cltools.mem import find_pid

n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
if not find_pid("Chick.exe"):
    subprocess.run([sys.executable, os.path.join(HERE, "scripts", "launch.py")], check=True)
from cltools.nav import Nav
nav = Nav()
if nav.to_main_menu():
    nav.load_slot1_and_select_level(n)
print("state:", nav.state(), "world:", nav.game.world_name())
