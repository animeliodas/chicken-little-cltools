"""Tiny static-analysis helper over the unpacked image (CLTools/dump/Chick_unpacked.exe).

    from re_helper import Img
    im = Img(); im.xrefs(im.str_va(b"DebugMenu")); print(im.dis(0x401000, 20))
"""
import os, re, struct
import capstone

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 0x400000


class Img:
    def __init__(self, path=os.path.join(HERE, "dump", "Chick_unpacked.exe")):
        self.d = open(path, "rb").read()   # raw == virtual layout
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        self.md.detail = False
        self.text = (0x401000, 0x401000 + 0x392ac0)
        import pefile
        pe = pefile.PE(data=self.d, fast_load=True)
        self.sections = [(s.Name.rstrip(b"\0").decode(), BASE + s.VirtualAddress, BASE + s.VirtualAddress + s.Misc_VirtualSize) for s in pe.sections]
        pe.parse_data_directories()
        self.imports = {}
        for e in pe.DIRECTORY_ENTRY_IMPORT:
            for i in e.imports:
                if i.name:
                    self.imports[i.address] = e.dll.decode() + "!" + i.name.decode()
        self.iat = {v: k for k, v in self.imports.items()}

    def u32(self, va): return struct.unpack_from("<I", self.d, va - BASE)[0]
    def f32(self, va): return struct.unpack_from("<f", self.d, va - BASE)[0]
    def cstr(self, va, n=200):
        o = va - BASE; e = self.d.index(b"\0", o)
        return self.d[o:min(e, o + n)].decode("latin1")

    def str_va(self, s: bytes, nth=0):
        hits = [m.start() + BASE for m in re.finditer(re.escape(s + b"\0"), self.d)]
        hits = [h for h in hits if self.d[h - BASE - 1:h - BASE] in (b"\0",) or True]
        return hits[nth] if len(hits) > nth else None

    def str_all(self, s: bytes):
        return [m.start() + BASE for m in re.finditer(re.escape(s), self.d)]

    def xrefs(self, va, sect=None):
        """Locations in .text where the 32-bit constant `va` appears (push/mov/cmp/call [..])."""
        pat = struct.pack("<I", va)
        lo, hi = self.text
        out = []
        for m in re.finditer(re.escape(pat), self.d[lo - BASE:hi - BASE]):
            out.append(lo + m.start())
        return out

    def calls_to(self, target):
        """Direct E8 calls to target."""
        lo, hi = self.text
        out = []
        seg = self.d[lo - BASE:hi - BASE]
        i = seg.find(b"\xe8")
        while i != -1:
            if i + 5 <= len(seg):
                rel = struct.unpack_from("<i", seg, i + 1)[0]
                if lo + i + 5 + rel == target:
                    out.append(lo + i)
            i = seg.find(b"\xe8", i + 1)
        return out

    def insn_at_ref(self, ref, back=8):
        """Disassemble a few bytes before ref to find the instruction containing it."""
        for b in range(1, back):
            start = ref - b
            for ins in self.md.disasm(self.d[start - BASE:start - BASE + 16], start):
                if ins.address <= ref < ins.address + ins.size and ins.address == start:
                    return ins
                break
        return None

    def func_start(self, va, maxback=0x4000):
        """Heuristic: walk back to the byte after an int3/nop padding run or a ret before a typical prologue."""
        o = va - BASE
        for k in range(o, o - maxback, -1):
            b0 = self.d[k - 1]
            if b0 in (0xCC, 0x90) and self.d[k] not in (0xCC, 0x90):
                # MSVC pads with CC or 90 between functions, functions 16-aligned often
                if (k % 16 == 0) or self.d[k - 2] in (0xCC, 0x90, 0xC3):
                    return k + BASE
        return None

    def dis(self, va, n=40, show=True):
        out = []
        for ins in self.md.disasm(self.d[va - BASE:va - BASE + n * 15], va):
            s = f"{ins.address:08x}  {ins.mnemonic:6s} {ins.op_str}"
            # annotate constants
            for mm in re.finditer(r"0x([0-9a-f]{6,8})", ins.op_str):
                c = int(mm.group(1), 16)
                if c in self.imports:
                    s += f"   ; {self.imports[c]}"
                elif BASE + 0x394000 <= c < BASE + 0x4c4000:
                    try:
                        t = self.cstr(c, 60)
                        if len(t) >= 3 and all(32 <= ord(ch) < 127 for ch in t):
                            s += f'   ; "{t}"'
                    except Exception:
                        pass
            out.append(s)
            n -= 1
            if n <= 0:
                break
        txt = "\n".join(out)
        if show:
            print(txt)
        return txt

    def section_of(self, va):
        for n, a, b in self.sections:
            if a <= va < b:
                return n
        return None


def _jmps_to(self, target):
    lo, hi = self.text
    seg = self.d[lo - BASE:hi - BASE]
    out = []
    i = seg.find(b"\xe9")
    while i != -1:
        if i + 5 <= len(seg):
            rel = struct.unpack_from("<i", seg, i + 1)[0]
            if lo + i + 5 + rel == target:
                out.append(lo + i)
        i = seg.find(b"\xe9", i + 1)
    return out


def _thunk_target(self, va):
    if self.d[va - BASE] == 0xE9:
        return va + 5 + struct.unpack_from("<i", self.d, va - BASE + 1)[0]
    return None


def _refs_any(self, target):
    """calls/jmps to target and to its ILT thunks, plus raw pointer refs."""
    res = {"call": self.calls_to(target), "jmp": self._jmps_to(target), "ptr": self.xrefs(target)}
    for t in list(res["jmp"]):
        if t < 0x410000:  # ILT region
            res.setdefault("thunk", []).append(t)
            res["call"] += self.calls_to(t)
            res["ptr"] += self.xrefs(t)
    return res


Img._jmps_to = _jmps_to
Img.thunk_target = _thunk_target
Img.refs_any = _refs_any
