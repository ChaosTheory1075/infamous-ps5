#!/usr/bin/env python3
"""if1 unstable audio: RPCS3's canary patch "(Experimental) Unstable audio" by Hasster (EU BCES00220 01.00,
PPU-d0c3e2a1...: "Improves sound cackling by disabling some functions related to the audio. Lightning sounds
might be distorted.") applied to the lifted code of ~/if1/infamous2-lle/recompiled: the 7 blr's are a return
at the function's entry, the 6 nop'd branches are dropped, each behind g_if1_unst_audio (PS3_IF1_AUDIO_PATCH=0
turns it off at run time; defined in game_patches.cpp). Idempotent: lines already patched are left alone."""
import re, sys
R = sys.argv[1] if len(sys.argv) > 1 else __import__("os").path.expanduser("~") + "/if1/infamous2-lle/recompiled"
BLR = ["002833E0", "0028AB28", "00503AD8", "0050A870", "0050EBA0", "005189D0", "005511F0"]
# (file, line text of the branch, guest address it was checked to be at)
NOPS = [("ppu_recomp_004.cpp", "if (((ctx->cr >> 1) & 1)) goto loc_0028BD08;", "0028BCF0", "0028BCD8", 6),
        ("ppu_recomp_013.cpp", "if (((ctx->cr >> 1) & 1)) goto loc_0028BD08;", "0028BCF0", "0028BCD8", 6),
        ("ppu_recomp_009.cpp", "if ((!((ctx->cr >> 2) & 1))) goto loc_0050F730;", "0050F698", "0050F648", 20),
        ("ppu_recomp_009.cpp", "goto loc_0050F6D8;", "0050F754", "0050F74C", 2),
        ("ppu_recomp_009.cpp", "if (((ctx->cr >> 1) & 1)) goto loc_0051979C;", "005197DC", "005197A8", 13),
        # 0x00519900 (bgt past a 10-entry jump table) deliberately NOT dropped: with it gone an out-of-range voice
        # state jumps to garbage (the audio thread dies, audio freezes and loops). In-range: identical.
        ("ppu_recomp_009.cpp", "if ((!((ctx->cr >> 1) & 1))) goto loc_005197E0;", "00519798", "00519790", 2)]
TAG = "/* if1 unstable audio */"
import glob, os
files = {}
def get(f):
    if f not in files: files[f] = open(os.path.join(R, f)).read().split("\n")
    return files[f]
n = 0
for a in BLR:
    for f in sorted(glob.glob(os.path.join(R, "ppu_recomp_0*.cpp"))):
        L = get(os.path.basename(f))
        for i, l in enumerate(L):
            if l == "void func_%s(ppu_context* ctx) {" % a:
                if TAG not in L[i + 1]:
                    L.insert(i + 1, "        if (g_if1_unst_audio) return;   " + TAG)
                n += 1
                break
for f, text, addr, lab, off in NOPS:
    L = get(f)
    hits = []
    for i, l in enumerate(L):
        if l.strip() == text:   # check its address: `off` instruction lines after label `lab`
            j, k = i - 1, 0
            while not L[j].startswith("loc_") and "(ppu_context* ctx) {" not in L[j]:
                s = L[j].strip()
                if s and not s.startswith("uint64_t _cs_"): k += 1
                j -= 1
            if L[j].startswith("loc_%s:" % lab) and k == off: hits.append(i)
    already = [i for i, l in enumerate(L) if ("if1 unstable audio 0x" + addr) in l]
    if already: n += 1; continue
    if len(hits) != 1: sys.exit("%s %s: %d matches" % (f, addr, len(hits)))
    i = hits[0]; ind = L[i][:len(L[i]) - len(L[i].lstrip())]
    L[i] = ind + "if (!g_if1_unst_audio) { %s }   /* if1 unstable audio 0x%s */" % (text, addr)
    n += 1
for f, L in files.items():
    open(os.path.join(R, f), "w").write("\n".join(L))
h = os.path.join(R, "ppu_recomp.h"); t = open(h).read()
if "g_if1_unst_audio" not in t:
    t += "\n/* if1 unstable audio (tools/patch_if1_unstable_audio.py) */\n#ifdef __cplusplus\nextern \"C\"\n#endif\nint g_if1_unst_audio;\n"
    open(h, "w").write(t)
print("if1 unstable audio: %d of 13 sites patched" % n)
