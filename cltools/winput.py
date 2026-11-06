"""Send keyboard input to the game (DirectInput reads scancodes, so we use SendInput with KEYEVENTF_SCANCODE)."""
import ctypes
import ctypes.wintypes as wt
import time

u32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x2
KEYEVENTF_SCANCODE = 0x8
KEYEVENTF_EXTENDEDKEY = 0x1

# set-1 scancodes; extended keys have 0xE000
SC = {
    "esc": 0x01, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A,
    "0": 0x0B, "-": 0x0C, "=": 0x0D, "backspace": 0x0E, "tab": 0x0F, "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13,
    "t": 0x14, "y": 0x15, "u": 0x16, "i": 0x17, "o": 0x18, "p": 0x19, "enter": 0x1C, "lctrl": 0x1D, "a": 0x1E,
    "s": 0x1F, "d": 0x20, "f": 0x21, "g": 0x22, "h": 0x23, "j": 0x24, "k": 0x25, "l": 0x26, "lshift": 0x2A,
    "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30, "n": 0x31, "m": 0x32, "rshift": 0x36, "lalt": 0x38,
    "space": 0x39, "f1": 0x3B, "f2": 0x3C, "f3": 0x3D, "f4": 0x3E, "f5": 0x3F, "f6": 0x40, "f7": 0x41, "f8": 0x42,
    "f9": 0x43, "f10": 0x44, "num7": 0x47, "num8": 0x48, "num9": 0x49, "num4": 0x4B, "num5": 0x4C, "num6": 0x4D,
    "num1": 0x4F, "num2": 0x50, "num3": 0x51, "num0": 0x52,
    "up": 0xE048, "left": 0xE04B, "right": 0xE04D, "down": 0xE050, "rctrl": 0xE01D, "ralt": 0xE038,
    "home": 0xE047, "end": 0xE04F, "pgup": 0xE049, "pgdn": 0xE051, "ins": 0xE052, "del": 0xE053,
}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def _send(sc, up):
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    if sc & 0xE000:
        flags |= KEYEVENTF_EXTENDEDKEY
    i = INPUT(type=INPUT_KEYBOARD)
    i.u.ki = KEYBDINPUT(0, sc & 0xFF, flags, 0, 0)
    u32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))


def down(key):
    _send(SC[key], False)


def up(key):
    _send(SC[key], True)


def tap(key, hold=0.08, after=0.15):
    down(key)
    time.sleep(hold)
    up(key)
    time.sleep(after)


def hold(key, seconds):
    down(key)
    time.sleep(seconds)
    up(key)


def focus(hwnd):
    """Bring the game window to the foreground (works around the foreground lock)."""
    fg = u32.GetForegroundWindow()
    cur = u32.GetWindowThreadProcessId(fg, None)
    tgt = u32.GetWindowThreadProcessId(hwnd, None)
    me = ctypes.windll.kernel32.GetCurrentThreadId()
    u32.AttachThreadInput(me, cur, True)
    u32.AttachThreadInput(me, tgt, True)
    u32.ShowWindow(hwnd, 9)  # SW_RESTORE
    u32.BringWindowToTop(hwnd)
    u32.SetForegroundWindow(hwnd)
    u32.AttachThreadInput(me, cur, False)
    u32.AttachThreadInput(me, tgt, False)
    time.sleep(0.2)
    return u32.GetForegroundWindow() == hwnd


if __name__ == "__main__":
    import sys
    from .bridge import Bridge
    br = Bridge()
    print("focus:", focus(br.b.hwnd))
    for k in sys.argv[1:]:
        if k.startswith("wait"):
            time.sleep(float(k[4:]))
        elif ":" in k:
            key, sec = k.split(":")
            hold(key, float(sec))
        else:
            tap(k)


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


def click_window(hwnd):
    """Real left click in the middle of the client area (re-activates DirectInput like a user click)."""
    rc = wt.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(rc))
    pt = wt.POINT((rc.right - rc.left) // 2, (rc.bottom - rc.top) // 2)
    u32.ClientToScreen(hwnd, ctypes.byref(pt))
    u32.SetCursorPos(pt.x, pt.y)
    for flags in (0x0002, 0x0004):  # LEFTDOWN, LEFTUP
        i = INPUT(type=0)
        mi = _MOUSEINPUT(0, 0, 0, flags, 0, 0)
        ctypes.memmove(ctypes.addressof(i.u), ctypes.addressof(mi), ctypes.sizeof(mi))
        u32.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))
        time.sleep(0.05)
    time.sleep(0.3)
