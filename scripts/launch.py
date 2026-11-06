"""Start Chicken Little through Steam and press "Play!" in the launcher automatically.

    py -3 scripts/launch.py           # waits until the CLHook bridge is up
"""
import ctypes, ctypes.wintypes as wt, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cltools.mem import find_pid

u = ctypes.windll.user32
EnumProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def launcher_play_button():
    pid = find_pid("Launcher.exe")
    if not pid:
        return None
    found = []

    def top(h, _):
        p = wt.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h):
            def child(c, _):
                if u.GetDlgCtrlID(c) == 1:  # IDOK = "Play!"
                    found.append(c)
                return True
            u.EnumChildWindows(h, EnumProc(child), 0)
        return True

    u.EnumWindows(EnumProc(top), 0)
    return found[0] if found else None


def main():
    if find_pid("Chick.exe"):
        print("game already running")
        return 0
    if not find_pid("Launcher.exe"):
        os.startfile("steam://rungameid/339040")
    t = time.time()
    while time.time() - t < 60:
        b = launcher_play_button()
        if b:
            time.sleep(0.5)
            u.PostMessageW(b, 0x00F5, 0, 0)  # BM_CLICK
            break
        time.sleep(0.5)
    else:
        print("launcher did not appear")
        return 1
    from cltools.bridge import Bridge
    t = time.time()
    while time.time() - t < 60:
        try:
            br = Bridge()
            if br.b.frame > 0:
                print(f"game running, pid {br.b.pid}")
                return 0
        except OSError:
            pass
        time.sleep(0.5)
    print("game did not start")
    return 1


if __name__ == "__main__":
    sys.exit(main())
