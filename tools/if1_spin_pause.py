"""if1_spin_pause.py <port dir>: a pause instruction in inFAMOUS 1's WWS job-list wait spin.
# REVERTED 2026-11-02: no gain on the BC-250 crater (12.4-12.5 fps vs 12.6-12.9 without). Not applied.

func_0041FC38 waits for a job list by calling the "done yet?" check func_0041D028 in a tight loop
(the PS3 PPU spins there too). On x86 the spin takes execution resources from the SMT sibling --
on the BC-250 an SPU thread (crater gameplay: main PPU 0.67 core, half of it this spin, with all six
SPU threads at 0.8-0.98 core on 6 cores / 12 threads). `pause` is a hint only: the loop, its exit
and its timing to the guest are unchanged. Idempotent; run after the PPU code is regenerated.
"""
import sys
from pathlib import Path

src = Path(sys.argv[1]) / "recompiled" / "ppu_recomp_007.cpp"
s = src.read_text()
call = "        ctx->lr = 0x0041FC70; func_0041D028(ctx); DRAIN_TRAMPOLINE(ctx);\n"
loop = "        if (((ctx->cr >> 1) & 1)) goto loc_0041FC60;\n"
new = "        if (((ctx->cr >> 1) & 1)) { __builtin_ia32_pause(); goto loc_0041FC60; }   /* tools/if1_spin_pause.py */\n"
if new in s:
    sys.exit(0)
i = s.index(call)
j = s.index(loop, i)
if j - i > 600:
    sys.exit("if1_spin_pause: loop branch not right after the call")
src.write_text(s[:j] + new + s[j + len(loop):])
print("if1_spin_pause: patched", src)
