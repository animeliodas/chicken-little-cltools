"""Rebuild an analysable PE from the in-memory dump written by CLHook (clhook.ini: [Debug] DumpImage=1).

Usage: py -3 scripts/rebuild_dump.py
Output: CLTools/dump/Chick_unpacked.exe
  * section raw offsets == RVAs (file layout == memory layout, so file offset = VA - 0x400000)
  * headers and the import section (.idata) restored from Chick.exe on disk (memory has resolved IAT pointers)
Meant for static analysis (Ghidra / IDA / REA / capstone), not for running.
"""
import os
import pefile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.path.dirname(HERE)
orig_path = os.path.join(GAME, "Chick.exe")
mem_path = os.path.join(HERE, "dump", "Chick_mem.bin")
out_path = os.path.join(HERE, "dump", "Chick_unpacked.exe")

mem = bytearray(open(mem_path, "rb").read())
raw = open(orig_path, "rb").read()
orig = pefile.PE(orig_path, fast_load=True)

# restore .idata from disk (import names + unresolved IAT)
for s in orig.sections:
    if s.Name.rstrip(b"\0") == b".idata":
        mem[s.VirtualAddress:s.VirtualAddress + s.SizeOfRawData] = raw[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]

# headers: take the on-disk ones and make every section's raw data point at its RVA
hdr = pefile.PE(data=raw[:orig.OPTIONAL_HEADER.SizeOfHeaders] + b"\0" * 0x1000, fast_load=True)
hdr.OPTIONAL_HEADER.FileAlignment = hdr.OPTIONAL_HEADER.SectionAlignment
for s in hdr.sections:
    s.PointerToRawData = s.VirtualAddress
    s.SizeOfRawData = (s.Misc_VirtualSize + 0xFFF) & ~0xFFF
new_hdr = hdr.write()[:orig.OPTIONAL_HEADER.SizeOfHeaders]
mem[:len(new_hdr)] = new_hdr

with open(out_path, "wb") as f:
    f.write(mem)
print("wrote", out_path, len(mem), "bytes")
