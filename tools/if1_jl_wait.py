#!/usr/bin/env python3
# if1 job-list wait: func_0041FC38 (inFAMOUS 1's WWS job-list wait) spins on func_0041D028 (the
# "done" check: min of the list's 7 u16 counters >= target) until the SPUs finish -- 0.26 cores of
# the main PPU thread in the crater (c1on), and on the CPU-saturated PS5 a thread that takes run time
# from the SPU threads it is waiting for. After 64 tries the loop now sleeps in ps3_memkick_wait
# (woken by the next SPU atomic commit, or after PS3_IF1_JL_WAIT_US microseconds, default 30)
# before checking again. The check itself is unchanged. default off (PS3_IF1_JL_WAIT_US=30 = on).
#   if1_jl_wait.py [~/if1/infamous2-lle]   (idempotent; re-run after the PPU code is regenerated)
import sys, pathlib
root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else __import__("os").path.expanduser("~") + "/if1/infamous2-lle")
f = root / "recompiled" / "ppu_recomp_007.cpp"
s = f.read_text()
if "if1_jl_backoff" in s:
    print("if1 jl wait: already applied"); sys.exit(0)
HELPER = '''
/* if1 job-list wait (tools/if1_jl_wait.py) */
#include <cstdlib>
extern "C" void ps3_memkick_wait(uint64_t us);
static int if1_jl_wait_us(void)
{
    static int v = -1;
    if (v < 0) { const char* e = getenv("PS3_IF1_JL_WAIT_US"); v = e ? atoi(e) : 0; }   /* default off: no measurable gain on route1 */
    return v;
}
static inline void if1_jl_backoff(unsigned* n)
{
    if (++*n >= 64u) { const int us = if1_jl_wait_us(); if (us > 0) ps3_memkick_wait((uint64_t)us); }
}
'''
head = "void func_0041FC38(ppu_context* ctx) {\n"
loop = "        if (((ctx->cr >> 1) & 1)) goto loc_0041FC60;\n"
assert s.count(head) == 1, "func_0041FC38 not found once"
i = s.index(head)
j = s.index(loop, i)
assert j - i < 4000, "loop branch not inside func_0041FC38"
s = s[:i] + HELPER + head + "        unsigned _jl_n = 0;   /* if1 jl wait */\n" + s[i + len(head):]
j = s.index(loop, s.index(head))
s = s[:j] + "        if (((ctx->cr >> 1) & 1)) { if1_jl_backoff(&_jl_n); goto loc_0041FC60; }\n" + s[j + len(loop):]
f.write_text(s)
print("if1 jl wait: applied to", f)
