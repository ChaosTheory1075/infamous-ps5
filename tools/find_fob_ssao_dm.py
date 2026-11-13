"""Find FoB's SSAO plugin addresses: take 256 bytes at each inFamous 2 SSAO_DM_* guest address in
inFamous 2's EBOOT.elf and search FoB's EBOOT.elf for them.   find_fob_ssao_dm.py <if2 elf> <fob elf>"""
import struct
import sys

DM = {"DEPTH": 0x0087D500, "AO": 0x0087F880, "BLUR_H": 0x0087D880, "BLUR_V": 0x0087E480, "UPSAMPLE": 0x0087EC80}


def segs(d):
    phoff, = struct.unpack(">Q", d[0x20:0x28])
    phentsize, phnum = struct.unpack(">HH", d[0x36:0x3A])
    out = []
    for i in range(phnum):
        p = d[phoff + i * phentsize: phoff + (i + 1) * phentsize]
        typ, flags, off, vaddr, paddr, filesz = struct.unpack(">IIQQQQ", p[:40])
        if typ == 1 and filesz:
            out.append((vaddr, off, filesz))
    return out


def v2o(sg, v):
    for va, off, sz in sg:
        if va <= v < va + sz:
            return off + v - va
    return None


def o2v(sg, o):
    for va, off, sz in sg:
        if off <= o < off + sz:
            return va + o - off
    return None


a = open(sys.argv[1], "rb").read()
b = open(sys.argv[2], "rb").read()
sa, sb = segs(a), segs(b)
deltas = set()
for name, v in DM.items():
    o = v2o(sa, v)
    pat = a[o:o + 256]
    hits = []
    i = b.find(pat)
    while i >= 0 and len(hits) < 4:
        hits.append(i)
        i = b.find(pat, i + 1)
    vs = [o2v(sb, h) for h in hits]
    print(f"{name:9s} if2 0x{v:08X} -> fob {', '.join(f'0x{x:08X}' for x in vs) or 'NOT FOUND'}")
    if len(vs) == 1:
        deltas.add(vs[0] - v)
print("deltas:", [hex(d) for d in deltas])
