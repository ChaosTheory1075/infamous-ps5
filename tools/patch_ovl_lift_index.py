# ovl lift index: spu_overlay_note_get (every DMA GET) walks only the sources that can still match.
# After the quick reject (ovl_cannot_match), a GET into the job-module area (LS 0x4000+: every lifted
# job module is a fixed-address source there) walked all registered overlay sources (up to 128).
# When the GET's first word cannot start any signature and its EA is no address source -- the same
# hash bits the quick reject uses -- only fixed-address lifts can match, and those are now walked
# from their own index list in the original order, so the first hit is the same one.
# inFAMOUS 1 crater gameplay (BC-250 perf, 2026-11-02): spu_overlay_note_get was the hottest single
# symbol over all SPU threads (2.8% of all samples), mostly the loop over the source table.
CHN = "runtime/spu/spu_channels.c"
edit(CHN,
     '''static uint64_t s_ovl_lift_pages[4];        /* 256 x 1 KB pages of LS */''',
     '''static uint64_t s_ovl_lift_pages[4];        /* 256 x 1 KB pages of LS */
static unsigned char s_ovl_lift_idx[SPU_OVL_SRC_MAX];   /* ovl lift index: the fixed-address sources, in order */
static int s_ovl_lift_n;''',
     "ovl lift index: decl")
edit(CHN,
     '''        if (o->lift_lsa) {
            if (o->lift_lsa < lo) lo = o->lift_lsa;''',
     '''        if (o->lift_lsa) {
            s_ovl_lift_idx[s_ovl_lift_n++] = (unsigned char)i;   /* ovl lift index */
            if (o->lift_lsa < lo) lo = o->lift_lsa;''',
     "ovl lift index: fill")
edit(CHN,
     '''    memset(s_ovl_lift_pages, 0, sizeof s_ovl_lift_pages);
    uint32_t lo = 0xFFFFFFFFu, hi = 0;''',
     '''    memset(s_ovl_lift_pages, 0, sizeof s_ovl_lift_pages);
    s_ovl_lift_n = 0;   /* ovl lift index */
    uint32_t lo = 0xFFFFFFFFu, hi = 0;''',
     "ovl lift index: reset")
edit(CHN,
     '''    if (ovl_cannot_match(ea, ls, lsa, size)) return;
    for (int i = 0; i < s_ovl_src_count; i++) {
        const spu_ovl_src* o = &s_ovl_src[i];''',
     '''    if (ovl_cannot_match(ea, ls, lsa, size)) return;
    /* ovl lift index (tools/patch_ovl_lift_index.py): no signature or address source can match ->
     * walk only the fixed-address lifts (summary is current: ovl_cannot_match rebuilt it) */
    int lift_only = 0;
    {   const unsigned he = ovl_ea_hash(ea);
        int sig_may = 0;
        if (size >= 512) { uint32_t w; memcpy(&w, ls, 4); const unsigned hs = ovl_ea_hash(w);
                           sig_may = (s_ovl_sig_bits[hs >> 6] >> (hs & 63)) & 1; }
        lift_only = !sig_may && !((s_ovl_ea_bits[he >> 6] >> (he & 63)) & 1) &&
                    __atomic_load_n(&s_ovl_summary_n, __ATOMIC_ACQUIRE) == s_ovl_src_count;
    }
    const int n_walk = lift_only ? s_ovl_lift_n : s_ovl_src_count;
    for (int ii = 0; ii < n_walk; ii++) {
        const int i = lift_only ? s_ovl_lift_idx[ii] : ii;
        const spu_ovl_src* o = &s_ovl_src[i];''',
     "ovl lift index: walk")
