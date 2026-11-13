
# remap scan vec: rsx_vertex_remap_build_range's min/max scan without the early exit, so clang
# vectorises it (AVX2). The loop returned inside on a base_index mismatch, which kept it scalar: one
# cmov chain per reference, ~70% of the function's samples (perf annotate, crater run cr1), and the
# function was 6.5 ms of the RSX thread's ~65 ms frame there (PS3RECOMP_ENG_DRAWSTATS, run ds1:
# 4.26 M references a frame). Same result: a mismatch anywhere still returns 0, after the scan.
edit("libs/video/rsx_vertex_compact.c",
     '''    const u32 base = refs[0].base_index;
    u32 lo = refs[0].vertex_id, hi = lo;
    for (u32 i = 1; i < count; i++) {
        const u32 v = refs[i].vertex_id;
        if (refs[i].base_index != base) return 0;
        if (v < lo) lo = v;
        if (v > hi) hi = v;
    }
    const u64 span = (u64)hi - lo + 1u;''',
     '''    const u32 base = refs[0].base_index;
    u32 lo = refs[0].vertex_id, hi = lo, diff = 0;
    for (u32 i = 1; i < count; i++) {   /* remap scan vec: no early exit, so it vectorises */
        const u32 v = refs[i].vertex_id;
        diff |= refs[i].base_index ^ base;
        lo = v < lo ? v : lo;
        hi = v > hi ? v : hi;
    }
    if (diff) return 0;
    const u64 span = (u64)hi - lo + 1u;''',
     "remap scan vec")
