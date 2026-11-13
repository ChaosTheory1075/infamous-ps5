#!/usr/bin/env python3
# if1 spurs2 spus: inFAMOUS 1 creates its second SPURS instance (0x7D0380, the WWS job manager; SPU
# group 0x1001, prio 255) with ONE SPU, and that one SPU thread is the game's critical path on the
# console (spu 8197 busy 97-98% of every window while the main PPU waits on it and the five SPUs of
# group 0x1000 are 45-64% busy; 21:22 run of 2026-11-03). PS3_IF1_SPURS2_SPUS=<n> (2..4) asks the
# real (LLE) SPURS for n SPUs for that instance at initialize time, so SPURS and the job manager set
# themselves up for n SPUs (the 11-03 attempt cloned threads onto a 1-SPU SPURS and hung).
# Matched by nSpus == 1 and spuPriority == 255 in cellSpursAttributeInitialize (libsre 0x73C4:
# r6 nSpus, r7 spuPriority) and cellSpursInitialize (0x8578: r4, r5). Unset = old (1 SPU).
#   if1_spurs2_spus.py [~/if1/infamous2-lle]   (idempotent)
import sys, pathlib
root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else __import__("os").path.expanduser("~") + "/if1/infamous2-lle")
f = root / "lle" / "libsre" / "libsre_recomp_000.cpp"
s = f.read_text()
if "if1_spurs2_spus" in s:
    print("if1 spurs2 spus: already applied"); sys.exit(0)
HELPER = '''
/* if1 spurs2 spus (tools/if1_spurs2_spus.py) */
#include <cstdlib>
#include <cstdio>
static int if1_spurs2_spus(void)
{
    static int v = -1;
    if (v < 0) { const char* e = getenv("PS3_IF1_SPURS2_SPUS"); v = e ? atoi(e) : 0; if (v > 4) v = 4; }
    return v;
}
static void if1_spurs2_fix(ppu_context* ctx, int nreg, int preg, const char* fn)
{
    const int n = if1_spurs2_spus();
    if (n >= 2 && (uint32_t)ctx->gpr[nreg] == 1u && (uint32_t)ctx->gpr[preg] == 255u) {
        fprintf(stderr, "[if1 spurs2] %s: nSpus 1 -> %d (spuPriority 255)\\n", fn, n);
        ctx->gpr[nreg] = (uint64_t)n;
    }
}
'''
for addr, nreg, preg, name in (("301073C4", 6, 7, "cellSpursAttributeInitialize"),
                               ("30108578", 4, 5, "cellSpursInitialize")):
    head = "void libsre_func_%s(ppu_context* ctx) {\n" % addr
    assert s.count(head) == 1, head
    s = s.replace(head, head + "        if1_spurs2_fix(ctx, %d, %d, \"%s\");   /* if1 spurs2 spus */\n" % (nreg, preg, name), 1)
first = s.index("void libsre_func_")
s = s[:first] + HELPER + s[first:]
f.write_text(s)
print("if1 spurs2 spus: applied to", f)
