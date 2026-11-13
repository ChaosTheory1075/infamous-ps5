
# idx memo multi: the index memo for draws of several index batches too. One DRAW_INDEX_ARRAY
# carries at most 256 indices, so every larger mesh arrives as a series of batches; with only
# one-batch draws eligible, run im1 had ~8.9k hits a frame of ~13.5k draws and remap still
# 2.8 ms. Batches that follow each other exactly (each first = previous first + count) decode
# into the same references as one run of their total count, so they are keyed as that run.
edit("libs/video/rsx_draw_engine.c",
     '''    const u32 first = dc.idx[0].first, count = dc.idx[0].count;
    const u64 start = (u64)ia.offset + (u64)first * esz, bytes = (u64)count * esz;''',
     '''    const u32 first = dc.idx[0].first;
    u64 count64 = dc.idx[0].count;   /* idx memo multi: contiguous batches = one run */
    for (u32 b = 1; b < dc.n_idx; b++) {
        if ((u64)dc.idx[b].first != (u64)first + count64) return;
        count64 += dc.idx[b].count;
    }
    if (count64 > 0xFFFFFFFFull) return;
    const u32 count = (u32)count64;
    const u64 start = (u64)ia.offset + (u64)first * esz, bytes = (u64)count * esz;''',
     "idx memo multi lookup")
edit("libs/video/rsx_draw_engine.c",
     '''    if (allow_remap && eng_im_on() && !dc.n_arr && dc.n_idx == 1 && !dc.inl && dc.idx[0].count > 1 && dc.fetch_ok)''',
     '''    if (allow_remap && eng_im_on() && !dc.n_arr && dc.n_idx >= 1 && !dc.inl && dc.fetch_ok &&
        (dc.n_idx > 1 || dc.idx[0].count > 1))   /* idx memo multi */''',
     "idx memo multi gate")
