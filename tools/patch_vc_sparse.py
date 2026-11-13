
# vc sparse: cheaper content checks for vertex-cache entries that already draw from a cached buffer.
# Every draw hashed its whole vertex spans (eng_hash_span) even when 99% of draws hit the cache:
# crater (run ds1, PS3RECOMP_ENG_DRAWSTATS): 13,322 hits / 136 misses a frame, 28.8 MB hashed in
# 4.2 ms of the RSX thread's ~65 ms -- and the same mesh is hashed again for each shadow cascade.
# Now, for an entry with a cached buffer whose bytes matched on its last full check:
#   - a second probe of the key in the same frame reuses that frame's hash;
#   - after 4 matching full checks, frames other than every 8th (staggered by key) take a sampled
#     hash (64 bytes of every 2 KB + the last 64 of each span, as eng_texture_sparse_hash); equal
#     to the sampled hash of the last full check = unchanged; different = full hash as before.
# A rewrite of a stable mesh is seen at once if it touches a sampled block, else within 8 frames.
# PS3RECOMP_ENG_VCACHE_SPARSE=0 = full hash on every probe (old).
edit("libs/video/rsx_draw_engine.c",
     '''typedef struct {
    u64 key, content;
    u32 vbuf, bytes, n, stride;
    u32 last_frame, seen_frame, skip_until;
    u8 seen, changes;
} eng_vc_entry;''',
     '''typedef struct {
    u64 key, content;
    u32 vbuf, bytes, n, stride;
    u32 last_frame, seen_frame, skip_until;
    u8 seen, changes;
    u8 stable;              /* vc sparse: full checks in a row that matched */
    u32 hashed_frame;       /* vc sparse: frame of the last hash, + 1 (0 = none) */
    u64 frame_hash, sparse; /* vc sparse: that hash; sampled hash at the last full check */
} eng_vc_entry;''',
     "vc sparse struct")
edit("libs/video/rsx_draw_engine.c",
     '''    u64 c = 0x51ED270B27A3F5E1ull;
    for (u32 i = 0; i < nr; ) {
        const u8* a0 = lo[i]; const u8* a1 = hi[i];
        for (i++; i < nr && lo[i] <= a1 + 64; i++) if (hi[i] > a1) a1 = hi[i];
        c = eng_hash_span(a0, (u64)(a1 - a0), c);
        ds_vc_hashed += (u64)(a1 - a0);
    }
    *content = c;
    return e;
}''',
     '''    /* vc sparse: merge the spans once; sampled / same-frame checks for settled entries */
    const u8* m0[RSX_DSP_NUM_VERTEX_ATTR]; const u8* m1[RSX_DSP_NUM_VERTEX_ATTR];
    u32 nm = 0;
    for (u32 i = 0; i < nr; ) {
        const u8* a0 = lo[i]; const u8* a1 = hi[i];
        for (i++; i < nr && lo[i] <= a1 + 64; i++) if (hi[i] > a1) a1 = hi[i];
        m0[nm] = a0; m1[nm] = a1; nm++;
    }
    static int s_sp = -1;
    if (s_sp < 0) { const char* ev = getenv("PS3RECOMP_ENG_VCACHE_SPARSE"); s_sp = (ev && *ev == '0') ? 0 : 1; }
    const int settled = s_sp && e->vbuf && e->seen && e->stable >= 1;
    if (settled && e->hashed_frame == g.frames + 1u) {   /* already checked this frame */
        *content = e->frame_hash;
        return e;
    }
    u64 sp = 0x6A09E667F3BCC908ull;
    for (u32 i = 0; i < nm; i++) {
        const u8* a0 = m0[i]; const u64 n = (u64)(m1[i] - a0);
        if (n < 64) { for (u64 j = 0; j < n; j++) { sp ^= a0[j]; sp *= 1099511628211ull; } continue; }
        for (u64 j = 0; j + 64 <= n; j += 2048) {
            u64 w[8]; memcpy(w, a0 + j, sizeof w);
            for (int k = 0; k < 8; k++) sp = (sp ^ w[k]) * 1099511628211ull;
        }
        { u64 w[8]; memcpy(w, a0 + n - 64, sizeof w);
          for (int k = 0; k < 8; k++) sp = (sp ^ w[k]) * 1099511628211ull; }
        sp ^= n;
    }
    if (settled && e->stable >= 4 && ((g.frames + (u32)key) & 7u) != 0 && sp == e->sparse) {
        e->hashed_frame = g.frames + 1u; e->frame_hash = e->content;
        *content = e->content;
        return e;
    }
    u64 c = 0x51ED270B27A3F5E1ull;
    for (u32 i = 0; i < nm; i++) {
        c = eng_hash_span(m0[i], (u64)(m1[i] - m0[i]), c);
        ds_vc_hashed += (u64)(m1[i] - m0[i]);
    }
    if (e->seen && c == e->content) { if (e->stable < 255) e->stable++; }
    else e->stable = 0;
    e->sparse = sp;
    e->hashed_frame = g.frames + 1u; e->frame_hash = c;
    *content = c;
    return e;
}''',
     "vc sparse probe")
