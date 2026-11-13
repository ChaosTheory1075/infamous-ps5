#!/usr/bin/env python3
# if1 spurs prio8: SPURS runs a workload on an SPU only where the workload's per-SPU priority byte is non-zero;
# inFAMOUS 1 fills 5 bytes (its SPU count) and leaves 6-8 zero, so the three SPUs PS3_IF1_SPURS1_SPUS=8 added
# never got its job chains (console trace 2026-11-06: SPUs 6-8 at 0%). At libsre's two attribute initializers
# (NID 0xEFEB2679 _cellSpursWorkloadAttributeInitialize = 0x3010A000: r9 = priority[8], maxContention at
# r1+116; NID 0x3548F483 _cellSpursJobChainAttributeInitialize = 0x30118568: r9 = priorityTable[8], r10 =
# maxContention, initialRequestSpuCount at r1+156) copy priority[from-1] into bytes from..to-1 when they are
# zero and raise the contention / request counts equal to <from> to <to>. SPURS_MAXCONT_FIX=<from>:<to> (the
# same switch the runtime's contention fix-up reads); unset = untouched.
#   if1_spurs_prio8.py [~/if1/infamous2-lle]   (idempotent)
import sys, pathlib
root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else __import__("os").path.expanduser("~") + "/if1/infamous2-lle")
f = root / "lle" / "libsre" / "libsre_recomp_000.cpp"
s = f.read_text()
if "if1_spurs_prio8" in s:
    print("if1 spurs prio8: already applied"); sys.exit(0)
HELPER = r'''
/* if1 spurs prio8 (tools/if1_spurs_prio8.py) */
static int if1_prio8_from, if1_prio8_to = -1;
static void if1_prio8_env(void)
{
    if (if1_prio8_to >= 0) return;
    const char* e = getenv("SPURS_MAXCONT_FIX"); unsigned a = 0, b = 0;
    if (e && sscanf(e, "%u:%u", &a, &b) == 2 && a >= 1 && b > a && b <= 8) { if1_prio8_from = (int)a; if1_prio8_to = (int)b; }
    else if1_prio8_to = 0;
}
static void if1_prio8_fill(uint32_t prio_ea, const char* fn)
{
    if (!prio_ea) return;
    uint8_t p[8]; for (int i = 0; i < 8; i++) p[i] = vm_read8(prio_ea + (uint32_t)i);
    int zero = 1; for (int i = if1_prio8_from; i < if1_prio8_to; i++) if (p[i]) zero = 0;
    if (!p[if1_prio8_from - 1] || !zero) return;
    for (int i = if1_prio8_from; i < if1_prio8_to; i++) vm_write8(prio_ea + (uint32_t)i, p[if1_prio8_from - 1]);
    static int n; if (n++ < 24)
        fprintf(stderr, "[if1 spurs prio8] %s: priority %u %u %u %u %u %u %u %u -> SPUs %d-%d get %u\n", fn,
                p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], if1_prio8_from, if1_prio8_to - 1, p[if1_prio8_from - 1]);
}
static void if1_prio8_workload(ppu_context* ctx)   /* _cellSpursWorkloadAttributeInitialize */
{
    if1_prio8_env(); if (!if1_prio8_to) return;
    if1_prio8_fill((uint32_t)ctx->gpr[9], "workload");
    const uint64_t sp = ctx->gpr[1] + 112 + 4;   /* maxContention: the 9th argument, low word of its stack slot */
    if (vm_read32(sp) == (uint32_t)if1_prio8_from) vm_write32(sp, (uint32_t)if1_prio8_to);
}
static void if1_prio8_jobchain(ppu_context* ctx)   /* _cellSpursJobChainAttributeInitialize */
{
    if1_prio8_env(); if (!if1_prio8_to) return;
    if1_prio8_fill((uint32_t)ctx->gpr[9], "job chain");
    if ((uint32_t)ctx->gpr[10] == (uint32_t)if1_prio8_from) ctx->gpr[10] = (uint64_t)if1_prio8_to;   /* maxContention */
    const uint64_t rq = ctx->gpr[1] + 152 + 4;   /* initialRequestSpuCount: the 14th argument */
    if (vm_read32(rq) == (uint32_t)if1_prio8_from) vm_write32(rq, (uint32_t)if1_prio8_to);
}
'''
for addr, call in (("3010A000", "if1_prio8_workload(ctx);"), ("30118568", "if1_prio8_jobchain(ctx);")):
    head = "void libsre_func_%s(ppu_context* ctx) {\n" % addr
    assert s.count(head) == 1, head
    s = s.replace(head, head + "        %s   /* if1 spurs prio8 */\n" % call, 1)
first = s.index("void libsre_func_")
s = s[:first] + HELPER + s[first:]
f.write_text(s)
print("if1 spurs prio8: applied to", f)
