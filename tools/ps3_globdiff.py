#!/usr/bin/env python3
"""Globals that are steady on the real PS3 and steady on the PS5 but DIFFERENT: config/state bugs.

    ps3_globdiff.py [--game if2|if1] PS5_SNAP_DIR [PS5_SNAP_DIR ...]
PS3 side: if2 = work/ps3_if2_20261103/snap_*_freeroam*, if1 = work/ps3_if1_20261103/snap_* (pass
--ps3 GLOB to pick other snapshots). Both sides' elf_data_00010000.bin (from 0x10000); the EBOOT RW
segment is compared word by word (big-endian).
"""
import argparse
import glob
import struct
from pathlib import Path

W = Path.home() / "inFamous/work"
GAMES = {
    "if2": (0x930000, 0xBA4408, str(W / "ps3_if2_20261103/snap_*_freeroam*")),
    "if1": (0x720000, 0x9EED60, str(W / "ps3_if1_20261103/snap_*")),
}
BASE = 0x10000

ap = argparse.ArgumentParser()
ap.add_argument("--game", default="if2", choices=sorted(GAMES))
ap.add_argument("--ps3", default="")
ap.add_argument("ps5", nargs="+")
a = ap.parse_args()
LO, HI, ps3_glob = GAMES[a.game]
ps3 = sorted(glob.glob(a.ps3 or ps3_glob))


def words(d):
    b = (Path(d) / "elf_data_00010000.bin").read_bytes()[LO - BASE:HI - BASE]
    return struct.unpack(f">{len(b) // 4}I", b[:len(b) // 4 * 4])


A = [words(d) for d in ps3]
B = [words(d) for d in a.ps5]
n = min(len(x) for x in A + B)


def kind(v):
    if 0x30000000 <= v < 0x3C000000: return "heap ptr"
    if 0x40000000 <= v < 0x4A000000: return "io/0x40 ptr"
    if 0x10000 <= v < HI: return "elf ptr"
    if 0xD0000000 <= v < 0xD1000000: return "stack ptr"
    if v < 0x10000: return "small int"
    f = struct.unpack(">f", struct.pack(">I", v))[0]
    if 1e-6 < abs(f) < 1e7: return f"float {f:g}"
    return "other"


rows = []
for i in range(n):
    x = {s[i] for s in A}
    y = {s[i] for s in B}
    if len(x) == 1 and len(y) == 1 and x != y:
        rows.append((LO + 4 * i, x.pop(), y.pop()))

print(f"{a.game}: PS3 snaps {len(A)}, PS5 snaps {len(B)}: {len(rows)} steady words that differ "
      f"(of {n} in the RW segment {LO:X}-{HI:X})")
groups = {}
for addr, va, vb in rows:
    k = kind(va) if kind(va) == kind(vb) else f"{kind(va)} vs {kind(vb)}"
    groups.setdefault(k.split(" ")[0] if k.startswith("float") else k, []).append((addr, va, vb))
for k, g in sorted(groups.items(), key=lambda x: (x[0] != "small int", -len(x[1]))):
    print(f"\n== {k}: {len(g)}")
    for addr, va, vb in g[:400 if k == "small int" else 60]:
        print(f"  {addr:08X}  PS3 {va:08X}  PS5 {vb:08X}   {kind(va)} | {kind(vb)}")
