"""Search the files inside a PSARC archive (zlib) for a byte pattern (ASCII and UTF-16, any case).
  psarc_grep.py <archive.psarc> <word>"""
import struct, sys, zlib

data = open(sys.argv[1], "rb").read()
word = sys.argv[2].lower()
magic, ver, comp, toc_len, ent_sz, n, blk, flags = struct.unpack(">4sI4sIIIII", data[:32])
assert magic == b"PSAR", magic
bw = 2 if blk <= 0x10000 else 3 if blk <= 0x1000000 else 4
ents = []
for i in range(n):
    e = data[32 + i * ent_sz: 32 + (i + 1) * ent_sz]
    zi, = struct.unpack(">I", e[16:20])
    ln = int.from_bytes(e[20:25], "big"); off = int.from_bytes(e[25:30], "big")
    ents.append((zi, ln, off))
zs_at = 32 + n * ent_sz
nz = (toc_len - zs_at) // bw
zs = [int.from_bytes(data[zs_at + k * bw: zs_at + (k + 1) * bw], "big") for k in range(nz)]

def read(zi, ln, off):
    out = bytearray()
    while len(out) < ln:
        z = zs[zi] or blk
        b = data[off:off + z]
        try:
            out += zlib.decompress(b) if b[:1] == b"\x78" else b
        except zlib.error:
            out += b
        off += z; zi += 1
    return bytes(out[:ln])

names = read(*ents[0]).decode("latin1").split("\n")
for name, e in zip(names, ents[1:]):
    if name.lower().endswith((".ogg", ".bik", ".xpps", ".dds", ".wav", ".vag", ".at3")): continue
    body = read(*e)
    for enc in ("latin1", "utf-16-be", "utf-16-le"):
        try:
            t = body.decode(enc, "ignore")
        except Exception:
            continue
        lo = t.lower()
        i = lo.find(word)
        while i >= 0:
            print(f"{name} [{enc}]: ...{t[max(0, i - 80):i + 80]!r}")
            i = lo.find(word, i + 1)
