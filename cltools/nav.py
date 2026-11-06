"""State-aware menu navigation for automated testing (avoids sending input into videos / the attract demo / loads).

States: "nogame", "loading" (no frames presented), "video" (Bink FMV playing), "menu" (front-end world `intro`:
title or menus), "level" (any other world with a player avatar).
"""
import os
import time

from .bridge import Bridge
from .mem import Process
from .game import Game
from . import winput


class Nav:
    def __init__(self):
        self.br = Bridge()
        self.game = Game(Process())

    # ---------------------------------------------------------------- state
    def frames_advancing(self, window=0.25):
        f = self.br.b.frame
        time.sleep(window)
        return self.br.b.frame - f >= 3

    def state(self):
        b = self.br.b
        if b.videoPlaying:
            return "video"
        if not self.frames_advancing():
            return "loading"
        w = (self.game.world_name() or "").lower()
        if w == "intro":
            return "menu"
        return "level" if self.game.avatar() else "loading"

    def wait_state(self, wanted, timeout=60, skip_videos=True):
        t = time.time()
        while time.time() - t < timeout:
            s = self.state()
            if s in wanted:
                return s
            if s == "video" and skip_videos:
                self.key("esc", force=True)
                time.sleep(0.4)
        raise TimeoutError(f"state {wanted} not reached (last: {s})")

    def in_menu_frame(self):
        """True when the blue front-end menu frame is on screen (main menu / dialogs), False on the title."""
        from PIL import Image
        p = self.br.screenshot()
        im = Image.open(p).convert("RGB")
        w, h = im.size
        r, g, b = im.getpixel((int(w * 0.02), int(h * 0.5)))
        os.remove(p)
        return b > r + 60 and b > g + 20

    # ---------------------------------------------------------------- input
    def key(self, k, hold=0.15, after=0.45, force=False):
        if not force:
            s = self.wait_state(("menu", "level"))
        winput.focus(self.br.b.hwnd)
        winput.hold(k, hold)
        time.sleep(after)

    def keys(self, *ks, **kw):
        for k in ks:
            self.key(k, **kw)

    # ---------------------------------------------------------------- flows
    def to_main_menu(self, timeout=90):
        """From launch/title to the main menu."""
        t = time.time()
        winput.focus(self.br.b.hwnd)
        winput.click_window(self.br.b.hwnd)
        while time.time() - t < timeout:
            s = self.wait_state(("menu", "level"), timeout=timeout)
            if s == "level":
                return False
            if self.in_menu_frame():
                return True
            self.key("space", hold=0.4, after=2.0)
        return False

    def load_slot1_and_select_level(self, level_index=1):
        """Main menu -> Load Game -> slot 1 -> Select Level -> level N (1 = Late for School)."""
        self.keys("s", "s", "enter")
        time.sleep(4.5)                 # "Checking saved games"
        self.key("enter", after=4.5)    # slot 1
        self.keys("s", "s", "s", "s")
        for _ in range(level_index):
            self.key("d")
        self.key("enter", after=2.0)
        self.wait_state(("level",), timeout=120)   # videos are skipped automatically
        time.sleep(1.0)
        self.key("esc", after=1.0)      # objective popup


def quit_to_title(nav):
    """From inside a level: pause -> Main Menu -> Yes."""
    nav.key("esc", after=1.0)
    nav.keys("s", "s")
    nav.key("enter", after=1.0)
    nav.key("w")
    nav.key("enter", after=2.0)
    nav.wait_state(("menu",), timeout=90)
    time.sleep(2.0)


def skip_level_complete(nav):
    """Save prompt after a level completion -> No save -> confirm -> next level loads."""
    nav.key("esc", force=True, after=2.0)          # "No save"
    t = time.time()
    while time.time() - t < 60 and nav.br.b.videoPlaying:
        nav.key("esc", force=True, after=0.5)
    time.sleep(3)
    nav.key("w", force=True)
    nav.key("enter", force=True, after=3)          # "continue without saving?" -> Yes
    nav.wait_state(("level", "menu"), timeout=120)
    time.sleep(3)


def dialog_open(nav):
    """True when a blue menu dialog (pause etc.) covers the screen centre."""
    from PIL import Image
    p = nav.br.screenshot()
    im = Image.open(p).convert("RGB")
    w, h = im.size
    r, g, b = im.getpixel((w // 2, int(h * 0.55)))
    os.remove(p)
    return b > 90 and b > r + 50 and b > g + 20


def back_to_level(nav, n=1):
    """From inside any level: quit to title, load slot 1, Select Level n."""
    for _ in range(4):
        nav.key("esc", after=1.2)
        if dialog_open(nav):
            break
    nav.keys("s", "s")
    nav.key("enter", after=1.2)
    nav.key("w")
    nav.key("enter", after=2)
    nav.wait_state(("menu",), timeout=90)
    time.sleep(2)
    if nav.to_main_menu():
        nav.load_slot1_and_select_level(n)
