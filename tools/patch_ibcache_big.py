# ib cache 4096: the indirect-branch inline cache had 256 direct-mapped entries (one per 1 KiB of LS).
# inFAMOUS 1's one-SPU group thread (spu 2005, group 0x1001) makes ~3x the indirect branches of the
# other SPUs and 8.5% of them missed because another branch held the slot ("miss-pc", [ibstat],
# console 2026-11-01). 4096 entries = one per 16 KiB of LS. The array is the last member of
# spu_context, so nothing else moves; +144 KiB per context (some contexts live on a host stack).
# ib stats also keep the 8 most frequent LS addresses that had no lifted function (they run on the
# interpreter: spu_step / spu_smc_microstep were ~14% of that thread) and print them with each line.
CTXH = "runtime/spu/spu_context.h"
edit(CTXH,
     '''#define SPU_IB_CACHE_SIZE 256   /* spu_indirect_branch inline cache entries (power of two) */''',
     '''#define SPU_IB_CACHE_SIZE 4096  /* spu_indirect_branch inline cache entries (power of two; was 256) */''',
     "ib cache 4096: size")
edit(CHN,
     '''static __thread unsigned long t_ibs[IBS_N];''',
     '''static __thread unsigned long t_ibs[IBS_N];
static __thread struct { uint32_t pc; uint32_t n; } t_ibs_nofn[8];   /* the hottest no-lift addresses */
static void ibs_nofn(uint32_t pc)
{
    int lo = 0;
    for (int i = 0; i < 8; i++) {
        if (t_ibs_nofn[i].pc == pc && t_ibs_nofn[i].n) { t_ibs_nofn[i].n++; return; }
        if (t_ibs_nofn[i].n < t_ibs_nofn[lo].n) lo = i;
    }
    t_ibs_nofn[lo].pc = pc; t_ibs_nofn[lo].n = 1;   /* replaces the least frequent (a rough top 8) */
}''',
     "ib cache 4096: nofn table")
edit(CHN,
     '''    for (int i = 0; i < IBS_N && k < (int)sizeof b - 40; i++)
        if (t_ibs[i]) k += snprintf(b + k, sizeof b - (size_t)k, " %s %lu", nm[i], t_ibs[i]);''',
     '''    for (int i = 0; i < IBS_N && k < (int)sizeof b - 40; i++)
        if (t_ibs[i]) k += snprintf(b + k, sizeof b - (size_t)k, " %s %lu", nm[i], t_ibs[i]);
    if (t_ibs[IBS_S_NOFN]) {
        k += snprintf(b + k, sizeof b - (size_t)k, " | nofn pcs:");
        for (int i = 0; i < 8 && k < (int)sizeof b - 24; i++)
            if (t_ibs_nofn[i].n) k += snprintf(b + k, sizeof b - (size_t)k, " %05X*%u", t_ibs_nofn[i].pc, t_ibs_nofn[i].n);
    }
    memset(t_ibs_nofn, 0, sizeof t_ibs_nofn);''',
     "ib cache 4096: report nofn")
edit(CHN,
     '''        if (!fn) { IBS(IBS_S_NOFN); goto slow; }''',
     '''        if (!fn) { IBS(IBS_S_NOFN); if (s_ibs_on) ibs_nofn(pc); goto slow; }''',
     "ib cache 4096: count nofn")
