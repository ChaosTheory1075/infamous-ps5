# spu reloc sig fast: (1) the indirect-branch fast path adopts too (job 209's lifted code calls the modules through
# bisl; that path went straight to the interpreter on a miss, so the first version adopted almost nothing and its
# scan, run on every drain-path miss, cost 28% of the run: rooftop 15.5 -> 11.8 fps); (2) the scan is cheap: window =
# the largest registered span, a 1024-bit prefilter on each candidate word, and a 512-entry negative cache keyed by
# (pc, the two words at pc) -- a stale entry can only mean interpreting, never running the wrong lift.
edit("runtime/spu/spu_channels.c",
     '''int spu_reloc_sig_adopt(spu_context* ctx, uint32_t pc)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3_SPU_RELOC_SIG"); on = !(e && e[0] == '0'); }
    if (!on || !s_rsig_n || !ctx->ls) return 0;
    pc &= SPU_LS_MASK;
    const uint32_t lo = pc > 0x8000u ? pc - 0x8000u : 0u;
    for (uint32_t pos = pc & ~15u; ; pos -= 16) {
        uint32_t w; memcpy(&w, ctx->ls + pos, 4);
        for (int i = 0; i < s_rsig_n; i++) {''',
     '''static uint64_t s_rsig_bits[16]; static uint32_t s_rsig_maxspan;   /* spu reloc sig fast */
static struct { uint32_t pc, w0, w1; } s_rsig_neg[512];
static inline unsigned rsig_h(uint32_t w) { return (w * 2654435761u) >> 22; }
int spu_reloc_sig_adopt(spu_context* ctx, uint32_t pc)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3_SPU_RELOC_SIG"); on = !(e && e[0] == '0'); }
    if (!on || !s_rsig_n || !ctx->ls) return 0;
    pc &= SPU_LS_MASK;
    if (pc + 8 > SPU_LS_SIZE) return 0;
    if (!s_rsig_maxspan) {   /* registration is done before any SPU runs */
        for (int i = 0; i < s_rsig_n; i++) { uint32_t sw; memcpy(&sw, s_rsig[i].sig, 4);
            const unsigned h = rsig_h(sw); s_rsig_bits[h >> 6] |= 1ull << (h & 63);
            if (s_rsig[i].span > s_rsig_maxspan) s_rsig_maxspan = s_rsig[i].span; } }
    uint32_t w0, w1; memcpy(&w0, ctx->ls + pc, 4); memcpy(&w1, ctx->ls + pc + 4, 4);
    const unsigned nk = ((pc >> 2) ^ w0) & 511u;
    if (s_rsig_neg[nk].pc == pc && s_rsig_neg[nk].w0 == w0 && s_rsig_neg[nk].w1 == w1) return 0;
    const uint32_t lo = pc > s_rsig_maxspan ? pc - s_rsig_maxspan : 0u;
    for (uint32_t pos = pc & ~15u; ; pos -= 16) {
        uint32_t w; memcpy(&w, ctx->ls + pos, 4);
        { const unsigned h = rsig_h(w);
          if (!((s_rsig_bits[h >> 6] >> (h & 63)) & 1)) { if (pos <= lo || pos < 16) break; continue; } }
        for (int i = 0; i < s_rsig_n; i++) {''',
     "spu reloc sig fast: scan")
edit("runtime/spu/spu_channels.c",
     '''            return (int)pick + 1;
        }
        if (pos <= lo || pos < 16) return 0;
    }
}''',
     '''            return (int)pick + 1;
        }
        if (pos <= lo || pos < 16) break;
    }
    s_rsig_neg[nk].pc = pc; s_rsig_neg[nk].w0 = w0; s_rsig_neg[nk].w1 = w1;
    return 0;
}''',
     "spu reloc sig fast: negative cache")
edit("runtime/spu/spu_channels.c",
     '''        if (!fn && (fn = spu_lazy_ovl_adopt(ctx, pc))) stale_seen = 1;   /* not cached: ovl changed */''',
     '''        if (!fn && (fn = spu_lazy_ovl_adopt(ctx, pc))) stale_seen = 1;   /* not cached: ovl changed */
        if (!fn && code_owner >= 0) {   /* spu reloc sig fast: a module job 209 copied here, called through bisl */
            extern int spu_reloc_sig_adopt(spu_context*, uint32_t);
            const int s1 = spu_reloc_sig_adopt(ctx, pc);
            if (s1 && (fn = spu_lookup(pc - ctx->resident_code[s1 - 1].lsa, ctx->resident_code[s1 - 1].image_id))) {
                ctx->code_base = ctx->resident_code[s1 - 1].lsa; stale_seen = 1; }
        }''',
     "spu reloc sig fast: indirect branch")
