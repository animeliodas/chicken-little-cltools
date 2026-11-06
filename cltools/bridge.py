"""Shared-memory bridge to CLHook (d3d8.dll proxy) running inside the game.

Layout must match struct CLBridge in src/hook/clhook.cpp.
"""
import ctypes
import ctypes.wintypes as wt
import time

FILE_MAP_ALL_ACCESS = 0xF001F
MAGIC = 0x42544C43


class Label(ctypes.Structure):
    _pack_ = 4
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float), ("z", ctypes.c_float),
                ("color", ctypes.c_uint32), ("text", ctypes.c_char * 48)]


class LineVert(ctypes.Structure):
    _pack_ = 4
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float), ("z", ctypes.c_float), ("color", ctypes.c_uint32)]


class ScriptCall(ctypes.Structure):
    _pack_ = 4
    _fields_ = [("fn", ctypes.c_uint32), ("nargs", ctypes.c_uint32), ("types", ctypes.c_uint8 * 4),
                ("args", ctypes.c_uint32 * 4), ("rtype", ctypes.c_uint32), ("result", ctypes.c_uint32)]


T_INT, T_FLOAT, T_BOOL = 1, 2, 4


class Exc(ctypes.Structure):
    _pack_ = 4
    _fields_ = [("frame", ctypes.c_uint32), ("code", ctypes.c_uint32), ("eip", ctypes.c_uint32),
                ("access", ctypes.c_uint32), ("esp", ctypes.c_uint32), ("inCall", ctypes.c_uint32)]


class Rec(ctypes.Structure):
    _pack_ = 4
    _fields_ = [("frame", ctypes.c_uint32), ("vtimeMs", ctypes.c_uint32), ("realMs", ctypes.c_double),
                ("keys", ctypes.c_uint32), ("flags", ctypes.c_uint32), ("fps", ctypes.c_float),
                ("gameMs", ctypes.c_uint32), ("vals", ctypes.c_uint32 * 96)]


REC_KEYS = ["W", "A", "S", "D", "SPACE", "R", "E", "LSHIFT", "V", "LMB", "RMB", "NUM8", "NUM2", "NUM4", "NUM6",
            "ESC", "ENTER", "UP", "DOWN", "LEFT", "RIGHT", "CTRL", "TAB", "Q", "F", "C", "X", "Z", "F5", "F6", "F7",
            "F8"]


class CLBridge(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("magic", ctypes.c_uint32),
        ("version", ctypes.c_uint32),
        ("pid", ctypes.c_uint32),
        ("hwnd", ctypes.c_uint32),
        ("device", ctypes.c_uint32),
        ("frame", ctypes.c_uint32),
        ("fps", ctypes.c_float),
        ("frameMs", ctypes.c_float),
        ("fpsTarget", ctypes.c_int32),
        ("speedPct", ctypes.c_int32),
        ("paused", ctypes.c_int32),
        ("stepFrames", ctypes.c_int32),
        ("overlayOn", ctypes.c_int32),
        ("screenshotReq", ctypes.c_int32),
        ("screenshotCount", ctypes.c_uint32),
        ("fixedStep", ctypes.c_int32),
        ("overlaySeq", ctypes.c_uint32),
        ("bbWidth", ctypes.c_uint32),
        ("bbHeight", ctypes.c_uint32),
        ("windowed", ctypes.c_uint32),
        ("presentInterval", ctypes.c_uint32),
        ("origInterval", ctypes.c_uint32),
        ("origRefresh", ctypes.c_uint32),
        ("vtime_ms", ctypes.c_uint32),
        ("videoPlaying", ctypes.c_uint32),
        ("videoCount", ctypes.c_uint32),
        ("freecamOn", ctypes.c_int32),
        ("freecam", ctypes.c_float * 5),
        ("screenshotPath", ctypes.c_char * 260),
        ("overlayText", ctypes.c_char * 4096),
        # v2: remote call
        ("callSeq", ctypes.c_uint32),
        ("callDone", ctypes.c_uint32),
        ("callFn", ctypes.c_uint32),
        ("callConv", ctypes.c_uint32),
        ("callThis", ctypes.c_uint32),
        ("callNArgs", ctypes.c_uint32),
        ("callArgs", ctypes.c_uint32 * 8),
        ("callResult", ctypes.c_uint32),
        ("callStatus", ctypes.c_int32),
        ("callBufAddr", ctypes.c_uint32),
        ("callBuf", ctypes.c_uint8 * 2048),
        # v2: world drawing
        ("worldOn", ctypes.c_int32),
        ("worldDepth", ctypes.c_int32),
        ("lineCount", ctypes.c_uint32),
        ("labelCount", ctypes.c_uint32),
        ("viewValid", ctypes.c_int32),
        ("view", ctypes.c_float * 16),
        ("proj", ctypes.c_float * 16),
        ("videoName", ctypes.c_char * 32),
        ("labels", Label * 256),
        ("lines", LineVert * 65536),
        # v3: batched script-function calls
        ("scSeq", ctypes.c_uint32),
        ("scDone", ctypes.c_uint32),
        ("scCount", ctypes.c_uint32),
        ("scErrors", ctypes.c_uint32),
        ("sc", ScriptCall * 8192),
        # v4: per-frame recorder + exception catcher
        ("recOn", ctypes.c_int32),
        ("recHead", ctypes.c_uint32),
        ("recNumAddr", ctypes.c_uint32),
        ("recRing", ctypes.c_uint32),
        ("recAddr", ctypes.c_uint32 * 96),
        ("crashSeq", ctypes.c_uint32),
        ("crashCode", ctypes.c_uint32),
        ("crashEip", ctypes.c_uint32),
        ("crashAccess", ctypes.c_uint32),
        ("crashAccessType", ctypes.c_uint32),
        ("crashFrame", ctypes.c_uint32),
        ("crashRegs", ctypes.c_uint32 * 8),
        ("crashStack", ctypes.c_uint32 * 32),
        ("excHead", ctypes.c_uint32),
        ("exc", Exc * 16),
        ("rec", Rec * 8192),
    ]


assert CLBridge.callSeq.offset == 4484 and CLBridge.worldOn.offset == 6600, "bridge layout"
assert CLBridge.labels.offset == 6780 and CLBridge.lines.offset == 23164, "bridge layout"
assert CLBridge.recOn.offset == 1366668 and ctypes.sizeof(Rec) == 416, (CLBridge.recOn.offset, ctypes.sizeof(Rec))
assert CLBridge.scSeq.offset == 1071740 and CLBridge.sc.offset == 1071756 and ctypes.sizeof(ScriptCall) == 36

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenFileMappingW.restype = wt.HANDLE
_k32.OpenFileMappingW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
_k32.MapViewOfFile.restype = ctypes.c_void_p
_k32.MapViewOfFile.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t]


class Bridge:
    """Live view of the CLHook bridge. Raises OSError if the game/hook is not running."""

    def __init__(self):
        h = _k32.OpenFileMappingW(FILE_MAP_ALL_ACCESS, False, "Local\\CLToolsBridge")
        if not h:
            raise OSError("CLHook bridge not found - is the game running with CLTools d3d8.dll?")
        p = _k32.MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, ctypes.sizeof(CLBridge))
        if not p:
            p = _k32.MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, 8)
            ver = ctypes.c_uint32.from_address(p + 4).value if p else 0
            raise OSError(f"CLHook bridge v{ver} is older than these tools (v4) - restart the game with the new d3d8.dll")
        self._h = h
        self.b = CLBridge.from_address(p)
        if self.b.magic != MAGIC:
            raise OSError("bridge magic mismatch")

    # ---- control -------------------------------------------------------
    def set_overlay(self, text: str):
        data = text.encode("latin-1", "replace")[:4095]
        ctypes.memmove(ctypes.addressof(self.b) + CLBridge.overlayText.offset, data + b"\0", len(data) + 1)
        self.b.overlaySeq += 1

    def pause(self, on=True):
        self.b.paused = 1 if on else 0

    def step(self, frames=1):
        self.b.paused = 1
        self.b.stepFrames += frames

    def set_speed(self, pct: int):
        self.b.speedPct = int(pct)

    def set_fps(self, fps: int):
        self.b.fpsTarget = int(fps)

    def screenshot(self, timeout=5.0) -> str:
        n = self.b.screenshotCount
        self.b.screenshotReq = 1
        t = time.time()
        while self.b.screenshotCount == n:
            if time.time() - t > timeout:
                raise TimeoutError("screenshot not taken (game minimized or not presenting?)")
            time.sleep(0.02)
        return self.b.screenshotPath.decode("mbcs", "replace")

    # ---- v2 ------------------------------------------------------------
    @property
    def v2(self):
        return self.b.version >= 2

    def call(self, fn, *args, this=None, timeout=3.0):
        """Call a game function on the game thread (between frames). cdecl/stdcall, or thiscall if this= given.
        Returns eax. Raises on exception inside the game (caught by CLHook)."""
        b = self.b
        if not self.v2:
            raise RuntimeError("CLHook too old: rebuild/reinstall d3d8.dll")
        while b.callSeq != b.callDone:
            time.sleep(0.005)
        b.callFn = fn
        b.callConv = 1 if this is not None else 0
        b.callThis = this or 0
        b.callNArgs = len(args)
        for i, a in enumerate(args):
            b.callArgs[i] = a & 0xFFFFFFFF
        seq = (b.callSeq + 1) & 0xFFFFFFFF
        b.callSeq = seq
        t = time.time()
        while b.callDone != seq:
            if time.time() - t > timeout:
                raise TimeoutError("game did not execute the call (not presenting?)")
            time.sleep(0.002)
        if b.callStatus == 1:
            raise RuntimeError(f"exception inside game while calling 0x{fn:08x}")
        if b.callStatus == 2:
            raise ValueError("bad call request")
        return b.callResult

    def buf_write(self, data: bytes, offset=0):
        """Write into the shared scratch buffer; returns the in-game address of that data."""
        ctypes.memmove(ctypes.addressof(self.b) + CLBridge.callBuf.offset + offset, data, len(data))
        return self.b.callBufAddr + offset

    def buf_read(self, offset, size):
        return bytes(self.b.callBuf[offset:offset + size])

    def set_lines(self, verts):
        """verts: iterable of (x, y, z, argb) - consecutive pairs form line segments."""
        n = 0
        L = self.b.lines
        for x, y, z, c in verts:
            if n >= 65536:
                break
            v = L[n]
            v.x, v.y, v.z, v.color = x, y, z, c
            n += 1
        self.b.lineCount = n & ~1

    def set_labels(self, labels):
        """labels: iterable of (x, y, z, rgb, text)."""
        n = 0
        for x, y, z, c, text in labels:
            if n >= 256:
                break
            l = self.b.labels[n]
            l.x, l.y, l.z, l.color = x, y, z, c
            l.text = text.encode("latin-1", "replace")[:47]
            n += 1
        self.b.labelCount = n

    def script_batch(self, calls, timeout=5.0):
        """calls: list of (handler, [(type, value), ...]). Executed in one game frame.
        Returns list of (rtype, value) with value decoded by type (float/int/raw); rtype 0xFF = exception."""
        import struct as _s
        b = self.b
        if b.version < 3:
            raise RuntimeError("CLHook too old: reinstall d3d8.dll")
        out = []
        for start in range(0, len(calls), 8192):
            chunk = calls[start:start + 8192]
            while b.scSeq != b.scDone:
                time.sleep(0.002)
            for i, (fn, args) in enumerate(chunk):
                e = b.sc[i]
                e.fn = fn
                e.nargs = len(args)
                for k, (t, v) in enumerate(args):
                    e.types[k] = t
                    e.args[k] = _s.unpack("<I", _s.pack("<f", v))[0] if t == T_FLOAT else (int(v) & 0xFFFFFFFF)
                e.rtype = 0
            b.scCount = len(chunk)
            seq = (b.scSeq + 1) & 0xFFFFFFFF
            b.scSeq = seq
            t0 = time.time()
            while b.scDone != seq:
                if time.time() - t0 > timeout:
                    raise TimeoutError("game did not execute the script batch")
                time.sleep(0.002)
            for i in range(len(chunk)):
                e = b.sc[i]
                if e.rtype == T_FLOAT:
                    out.append((e.rtype, _s.unpack("<f", _s.pack("<I", e.result))[0]))
                elif e.rtype == T_INT:
                    out.append((e.rtype, _s.unpack("<i", _s.pack("<I", e.result))[0]))
                else:
                    out.append((e.rtype, e.result))
        return out

    def status(self) -> dict:
        b = self.b
        skip = {"freecam", "overlayText", "callArgs", "callBuf", "view", "proj", "labels", "lines", "sc", "recAddr", "crashRegs", "crashStack", "exc", "rec"}
        return {f: getattr(b, f) for f, _ in CLBridge._fields_ if f not in skip}


if __name__ == "__main__":
    import sys, json
    br = Bridge()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        s = br.status()
        s["screenshotPath"] = s["screenshotPath"].decode("mbcs", "replace")
        print(json.dumps(s, indent=1))
    elif cmd == "shot":
        print(br.screenshot())
    elif cmd == "pause":
        br.pause(True)
    elif cmd == "resume":
        br.pause(False)
    elif cmd == "step":
        br.step(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    elif cmd == "speed":
        br.set_speed(int(sys.argv[2]))
    elif cmd == "fps":
        br.set_fps(int(sys.argv[2]))
    elif cmd == "text":
        br.set_overlay(" ".join(sys.argv[2:]).replace("\n", "\n"))
