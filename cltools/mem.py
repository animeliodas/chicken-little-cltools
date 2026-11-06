"""Read/write memory of the running game (Chick.exe, 32-bit) via ReadProcessMemory/WriteProcessMemory."""
import ctypes
import ctypes.wintypes as wt
import re
import struct

PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x2
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
READABLE = 0x02 | 0x04 | 0x08 | 0x20 | 0x40 | 0x80

k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", wt.WCHAR * 260)]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wt.DWORD), ("PartitionId", wt.WORD), ("RegionSize", ctypes.c_size_t),
                ("State", wt.DWORD), ("Protect", wt.DWORD), ("Type", wt.DWORD)]


k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.OpenProcess.restype = wt.HANDLE
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
k32.WriteProcessMemory.argtypes = k32.ReadProcessMemory.argtypes
k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
k32.VirtualQueryEx.restype = ctypes.c_size_t
k32.VirtualProtectEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, ctypes.POINTER(wt.DWORD)]


def find_pid(exe="Chick.exe"):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    pe = PROCESSENTRY32W()
    pe.dwSize = ctypes.sizeof(pe)
    ok = k32.Process32FirstW(snap, ctypes.byref(pe))
    pid = None
    while ok:
        if pe.szExeFile.lower() == exe.lower():
            pid = pe.th32ProcessID
            break
        ok = k32.Process32NextW(snap, ctypes.byref(pe))
    k32.CloseHandle(snap)
    return pid


class Process:
    def __init__(self, exe="Chick.exe", pid=None):
        self.pid = pid or find_pid(exe)
        if not self.pid:
            raise OSError(f"{exe} is not running")
        self.h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION |
                                 PROCESS_QUERY_INFORMATION, False, self.pid)
        if not self.h:
            raise OSError(f"OpenProcess failed ({ctypes.get_last_error()})")

    def close(self):
        if self.h:
            k32.CloseHandle(self.h)
            self.h = None

    def alive(self):
        code = wt.DWORD()
        return bool(k32.GetExitCodeProcess(self.h, ctypes.byref(code))) and code.value == 259

    # ---- raw ----------------------------------------------------------
    def read(self, addr, size):
        buf = ctypes.create_string_buffer(size)
        n = ctypes.c_size_t()
        if not k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(n)) or n.value != size:
            raise OSError(f"read failed @0x{addr:08x}+{size}")
        return buf.raw

    def try_read(self, addr, size):
        try:
            return self.read(addr, size)
        except OSError:
            return None

    def write(self, addr, data, force=False):
        n = ctypes.c_size_t()
        old = wt.DWORD()
        if force:
            k32.VirtualProtectEx(self.h, ctypes.c_void_p(addr), len(data), 0x40, ctypes.byref(old))
        ok = k32.WriteProcessMemory(self.h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(n))
        if force:
            k32.VirtualProtectEx(self.h, ctypes.c_void_p(addr), len(data), old.value, ctypes.byref(old))
        if not ok:
            raise OSError(f"write failed @0x{addr:08x}")

    # ---- typed --------------------------------------------------------
    def u8(self, a): return self.read(a, 1)[0]
    def u16(self, a): return struct.unpack("<H", self.read(a, 2))[0]
    def u32(self, a): return struct.unpack("<I", self.read(a, 4))[0]
    def i32(self, a): return struct.unpack("<i", self.read(a, 4))[0]
    def f32(self, a): return struct.unpack("<f", self.read(a, 4))[0]
    def vec3(self, a): return struct.unpack("<3f", self.read(a, 12))
    def floats(self, a, n): return struct.unpack(f"<{n}f", self.read(a, 4 * n))
    def cstr(self, a, n=64):
        b = self.read(a, n)
        return b.split(b"\0", 1)[0].decode("latin-1")

    def w_u32(self, a, v): self.write(a, struct.pack("<I", v & 0xFFFFFFFF))
    def w_i32(self, a, v): self.write(a, struct.pack("<i", v))
    def w_f32(self, a, v): self.write(a, struct.pack("<f", v))
    def w_vec3(self, a, v): self.write(a, struct.pack("<3f", *v))

    def ptr_chain(self, base, *offs):
        """[[base]+o1]+o2 ... ; returns final address (not dereferenced)."""
        a = self.u32(base)
        for o in offs[:-1]:
            a = self.u32(a + o)
        return a + (offs[-1] if offs else 0)

    # ---- scanning -----------------------------------------------------
    def regions(self, lo=0x10000, hi=0x7FFF0000, writable_only=False):
        mbi = MEMORY_BASIC_INFORMATION()
        a = lo
        while a < hi and k32.VirtualQueryEx(self.h, ctypes.c_void_p(a), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            base = mbi.BaseAddress or 0
            size = mbi.RegionSize
            if mbi.State == MEM_COMMIT and (mbi.Protect & READABLE) and not (mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS)):
                if not writable_only or (mbi.Protect & (0x04 | 0x08 | 0x40 | 0x80)):
                    yield base, size
            a = base + size

    def scan(self, pattern: bytes, regex=False, writable_only=True, limit=1000):
        """Find pattern in readable memory. Returns list of addresses."""
        out = []
        rx = re.compile(pattern if regex else re.escape(pattern), re.S)
        for base, size in self.regions(writable_only=writable_only):
            data = self.try_read(base, size)
            if not data:
                continue
            for m in rx.finditer(data):
                out.append(base + m.start())
                if len(out) >= limit:
                    return out
        return out

    def scan_vec3(self, x, y, z, tol=0.05, writable_only=True, limit=200):
        """Find 3 consecutive floats close to (x, y, z)."""
        import numpy as np
        out = []
        for base, size in self.regions(writable_only=writable_only):
            data = self.try_read(base, size)
            if not data or len(data) < 12:
                continue
            n = len(data) // 4
            arr = np.frombuffer(data[:n * 4], dtype="<f4")
            with np.errstate(invalid="ignore"):
                mx = np.abs(arr[:-2] - x) < tol
                if not mx.any():
                    continue
                my = np.abs(arr[1:-1] - y) < tol
                mz = np.abs(arr[2:] - z) < tol
                idx = np.nonzero(mx & my & mz)[0]
            for i in idx:
                out.append(base + int(i) * 4)
                if len(out) >= limit:
                    return out
        return out
