"""Find Festival of Blood's equivalents of the inFamous 2 port's executable-specific numbers.

usage: fob_map.py <inFamous 2 EBOOT.elf> <FoB EBOOT.elf>
"""
import hashlib
import struct
import sys

i2 = open(sys.argv[1], "rb").read()
fob = open(sys.argv[2], "rb").read()


def phdrs(d):
    e_phoff, = struct.unpack_from(">Q", d, 0x20)
    e_phentsize, e_phnum = struct.unpack_from(">HH", d, 0x36)
    out = []
    for i in range(e_phnum):
        p_type, p_flags, p_offset, p_vaddr, _, p_filesz, p_memsz = struct.unpack_from(">IIQQQQQ", d, e_phoff + i * e_phentsize)
        out.append((p_type, p_flags, p_offset, p_vaddr, p_filesz, p_memsz))
    return out


for name, d in (("inFamous 2", i2), ("FoB", fob)):
    print(f"== {name}: {len(d)} bytes, sha1 {hashlib.sha1(d).hexdigest()[:12]}")
    for t, fl, off, va, fs, ms in phdrs(d):
        if t == 1:
            print(f"   LOAD flags={fl:#x} off={off:#x} vaddr={va:#x} filesz={fs:#x} memsz={ms:#x} end={va + ms:#x}")

# The Wws_Job policy module: 11904 bytes at file offset 0x8D5B00 in inFamous 2 (guest 0x8E5B00).
pm = i2[0x8D5B00:0x8D5B00 + 11904]
at = fob.find(pm)
print("policy module (exact) in FoB at file offset", hex(at) if at >= 0 else "not found")
if at < 0:
    head = pm[:256]
    at = fob.find(head)
    print("policy module (first 256 bytes) at", hex(at) if at >= 0 else "not found")
if at >= 0:
    for t, fl, off, va, fs, ms in phdrs(fob):
        if t == 1 and off <= at < off + fs:
            print("  guest address", hex(va + at - off))

# inFamous 2's code end (--code-end 0x742e18) vs its text segment: report the same distance for FoB.
