"""find_spu_code.py <file> <hex words...>: find a run of big-endian words in a file and dump what follows."""
import sys

data = open(sys.argv[1], "rb").read()
pat = b"".join(int(w, 16).to_bytes(4, "big") for w in sys.argv[2:])
off = data.find(pat)
hits = 0
while off >= 0 and hits < 4:
    hits += 1
    print("file offset 0x%X" % off)
    for row in range(0, 0x60, 0x10):
        print("  +0x%02X: %s" % (row, " ".join(data[off + row + i:off + row + i + 4].hex().upper() for i in range(0, 16, 4))))
    off = data.find(pat, off + 1)
if not hits:
    print("not found")
