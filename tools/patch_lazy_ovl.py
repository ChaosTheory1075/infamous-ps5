# lazy ovl: a job module whose load was never seen still runs lifted.
# Overlay residency is noted when a DMA GET of >= 512 bytes lands a registered module's first 16
# bytes (spu_overlay_note_get). On inFAMOUS 1's one-SPU group thread (spu 0x2005, group 0x1001) that
# never happens: its jobs (e.g. jobmod_44377568bd76 / 542edebc6499 at LS 0x4000, both lifted and
# registered by signature) stayed "ovl 0", so every branch into them missed and ran on the
# interpreter (spu_step + spu_smc_microstep ~14% of that thread; [ibstat] nofn pcs 0x043A0...).
# Now: when an indirect branch at/above LS 0x4000 finds no lifted function, the 16 bytes at LS 0x4000
# are matched against the registered signatures; a match makes that module resident for this
# context. The adoption is remembered per host thread with its signature, and every later indirect
# branch on that thread re-checks those 16 bytes first: when another job has replaced the module
# the adoption is dropped before any lookup, so a new job never runs the old job's lifted code.
# PS3_SPU_LAZY_OVL=1 turns it on (off by default since 2026-11-02: it never adopted a module on the
# BC-250 crater runs; the 0x4xxx no-lift addresses there do not carry a registered signature).
edit(CHN,
     '''/* ib stats (tools/patch_ibstat.py) */''',
     '''/* lazy ovl (tools/patch_lazy_ovl.py) */
#define LAZY_OVL_LSA 0x4000u
static int s_lazy_ovl = -1;
static __thread int t_lazy_ovl;                 /* image adopted on this thread, 0 = none */
static __thread uint8_t t_lazy_sig[16];
static __thread unsigned long t_lazy_n;
int spu_overlay_match_sig(const uint8_t hdr[16]);
static __attribute__((noinline)) spu_fn spu_lazy_ovl_adopt(spu_context* ctx, uint32_t pc)
{
    if (s_lazy_ovl < 0) { const char* e = getenv("PS3_SPU_LAZY_OVL"); s_lazy_ovl = e && *e == '1'; }   /* off by default: never adopted in a measured run */
    if (!s_lazy_ovl || pc < LAZY_OVL_LSA || !ctx->ls) return NULL;
    const int ov = spu_overlay_match_sig(ctx->ls + LAZY_OVL_LSA);
    if (!ov || ov == ctx->resident_ovl) return NULL;
    spu_fn fn = spu_lookup(pc, ov);
    if (!fn) return NULL;
    ctx->resident_ovl = ov;
    ctx->ib_gen++;
    t_lazy_ovl = ov;
    memcpy(t_lazy_sig, ctx->ls + LAZY_OVL_LSA, 16);
    if (t_lazy_n++ < 8 || (t_lazy_n & 0xFFFF) == 0)
        fprintf(stderr, "[spu-ovl] spu %X: job image %d at LS 0x%05X adopted by signature (pc 0x%05X, #%lu)\\n",
                ctx->spu_id, ov, LAZY_OVL_LSA, pc, t_lazy_n);
    return fn;
}

/* ib stats (tools/patch_ibstat.py) */''',
     "lazy ovl: adopt")
edit(CHN,
     '''    if (s_ibs_on && ++t_ibs[IBS_CALL] >= (1ul << 21)) ibs_report(ctx);''',
     '''    if (s_ibs_on && ++t_ibs[IBS_CALL] >= (1ul << 21)) ibs_report(ctx);
    /* lazy ovl: an adopted job module stays resident only while its signature is still at LS 0x4000 */
    if (__builtin_expect(t_lazy_ovl != 0, 0) &&
        (ctx->resident_ovl != t_lazy_ovl || memcmp(ctx->ls + LAZY_OVL_LSA, t_lazy_sig, 16))) {
        if (ctx->resident_ovl == t_lazy_ovl) { ctx->resident_ovl = 0; ctx->ib_gen++; }
        t_lazy_ovl = 0;
    }''',
     "lazy ovl: revalidate")
edit(CHN,
     '''        if (!fn) { IBS(IBS_S_NOFN); if (s_ibs_on) ibs_nofn(pc); goto slow; }''',
     '''        if (!fn && (fn = spu_lazy_ovl_adopt(ctx, pc))) stale_seen = 1;   /* not cached: ovl changed */
        if (!fn) { IBS(IBS_S_NOFN); if (s_ibs_on) ibs_nofn(pc); goto slow; }''',
     "lazy ovl: on miss")
