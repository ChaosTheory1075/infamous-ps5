
# idx memo sparse: the index memo's content check sampled for settled entries, as the vertex
# cache's (vc sparse). The full 64-bit hash of every hit's index bytes (~8.6 MB a frame in the
# crater) cost more than the decode it replaced (im2: refs stage 2.5 -> 3.3 ms; crater imB/imA
# 19.3 -> 19.5 fps). After 4 full checks in a row that matched, frames other than every 8th
# (staggered by key) compare a sampled hash (64 bytes of every 2 KB + the last 64) against the
# one taken at the last full check; a sampled mismatch takes the full hash. A rewrite of a
# settled index buffer is seen at once if it touches a sampled block, else within 8 frames.
# PS3RECOMP_ENG_IDXMEMO_SPARSE=0 = full hash every draw.
edit("libs/video/rsx_draw_engine.c",
     '''    u8 complete;
    u32* idx;
} eng_im_entry;''',
     '''    u8 complete;
    u8 stable;      /* idx memo sparse: full checks in a row that matched */
    u64 sparse;     /* idx memo sparse: sampled hash at the last full check */
    u32* idx;
} eng_im_entry;''',
     "idx memo sparse struct")
edit("libs/video/rsx_draw_engine.c",
     '''    const u64 key = eng_fnv1a(f, sizeof f, 1469598103934665603ull);
    const u64 c = eng_hash_span(run, bytes, 0x51ED270B27A3F5E1ull);
    eng_im_entry* e = &s_im[key & (ENG_IM_N - 1u)];
    if (e->complete && e->key == key && !memcmp(e->f, f, sizeof f) && e->content == c) {
        e->last_frame = g.frames;
        dc.im_hit = e;
        ds_im_hit++;
        return;
    }
    e->key = key; memcpy(e->f, f, sizeof f); e->content = c; e->complete = 0;''',
     '''    const u64 key = eng_fnv1a(f, sizeof f, 1469598103934665603ull);
    eng_im_entry* e = &s_im[key & (ENG_IM_N - 1u)];
    const int same = e->complete && e->key == key && !memcmp(e->f, f, sizeof f);
    /* idx memo sparse: sampled hash (as eng_vc_probe's) */
    static int s_sp = -1;
    if (s_sp < 0) { const char* ev = getenv("PS3RECOMP_ENG_IDXMEMO_SPARSE"); s_sp = !(ev && *ev == '0'); }
    u64 sp = 0x6A09E667F3BCC908ull;
    if (s_sp) {
        if (bytes < 64) { for (u64 j = 0; j < bytes; j++) { sp ^= run[j]; sp *= 1099511628211ull; } }
        else {
            for (u64 j = 0; j + 64 <= bytes; j += 2048) {
                u64 w[8]; memcpy(w, run + j, sizeof w);
                for (int k = 0; k < 8; k++) sp = (sp ^ w[k]) * 1099511628211ull;
            }
            u64 w[8]; memcpy(w, run + bytes - 64, sizeof w);
            for (int k = 0; k < 8; k++) sp = (sp ^ w[k]) * 1099511628211ull;
        }
        sp ^= bytes;
        if (same && e->stable >= 4 && ((g.frames + (u32)key) & 7u) != 0 && sp == e->sparse) {
            e->last_frame = g.frames;
            dc.im_hit = e;
            ds_im_hit++;
            return;
        }
    }
    const u64 c = eng_hash_span(run, bytes, 0x51ED270B27A3F5E1ull);
    if (same && e->content == c) {
        if (e->stable < 255) e->stable++;
        e->sparse = sp;
        e->last_frame = g.frames;
        dc.im_hit = e;
        ds_im_hit++;
        return;
    }
    e->stable = 0; e->sparse = sp;
    e->key = key; memcpy(e->f, f, sizeof f); e->content = c; e->complete = 0;''',
     "idx memo sparse lookup")
