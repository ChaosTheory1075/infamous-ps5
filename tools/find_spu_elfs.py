"""List the SPU ELF images embedded in a PS3 EBOOT (e_machine 0x17 = SPU), with their file offsets,
guest addresses (via the PPU ELF's program headers), sizes and any nearby name string.
  find_spu_elfs.py <EBOOT.elf>"""
import sys, struct
d = open(sys.argv[1], "rb").read()
# PPU program headers: file offset -> vaddr
phoff = struct.unpack(">Q", d[0x20:0x28])[0]
phnum = struct.unpack(">H", d[0x38:0x3A])[0]
segs = []
for i in range(phnum):
    o = phoff + i * 56
    typ, flg, off, va, pa, fsz, msz, al = struct.unpack(">IIQQQQQQ", d[o:o + 56])
    if typ == 1:
        segs.append((off, va, fsz))
def va_of(off):
    for so, va, sz in segs:
        if so <= off < so + sz:
            return va + off - so
    return None
i = 0
while True:
    i = d.find(b"\x7fELF", i + 1)
    if i < 0:
        break
    if d[i + 4] != 1:   # 32-bit
        continue
    mach = struct.unpack(">H", d[i + 18:i + 20])[0]
    if mach != 0x17:
        continue
    shoff, = struct.unpack(">I", d[i + 32:i + 36])
    shnum, = struct.unpack(">H", d[i + 48:i + 50])
    shent, = struct.unpack(">H", d[i + 46:i + 48])
    size = shoff + shnum * shent if shoff else 0
    entry, = struct.unpack(">I", d[i + 24:i + 28])
    va = va_of(i)
    print("SPU ELF at file 0x%07X guest %s entry 0x%05X size ~0x%X" % (i, ("0x%08X" % va) if va is not None else "?", entry, size))
