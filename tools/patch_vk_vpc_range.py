# vk vpc range: only the vertex-constant rows the bound program reads reach the GPU on Vulkan.
# The draw engine already computes them per vertex program (vpc_lo/vpc_n, rsx_vp_analyze_constants;
# relative addressing keeps the whole block) and calls bind_vs_constants_range when a backend has it
# (Metal did; Vulkan did not). Without it every draw copied the full 514-row block (8.2 KB) four
# times: engine copy, CPU shadow, mapped UBO, per-draw ring. inFAMOUS 1's crater (BC-250, 2026-11-01):
# 13,500 draws per frame, "vs-const 111 MB" staged per frame, RSX thread 98% of a core at 11.7 fps.
# Now the rows [first, first + count) and the viewport tail go into the shadow and the UBO, and the
# per-draw ring copy takes only those (the rest of the ring block is never read by that program).
# A full bind (bind_vs_constants: helper draws, relative-addressing programs) copies everything as
# before. PS3RECOMP_ENG_VPC_FULL=1 turns ranges off (draw engine A/B switch).
VKB = "libs/video/rsx_vulkan_backend.c"
edit(VKB,
     '''    u32          vs_bytes, ps_bytes;
    u32          tex[RSX_BE_MAX_TEXTURES];''',
     '''    u32          vs_bytes, ps_bytes;
    u32          vs_ranged, vs_lo, vs_n, vs_tail;      /* vk vpc range: rows the program reads */
    u32          tex[RSX_BE_MAX_TEXTURES];''',
     "vk vpc range: state")
edit(VKB,
     '''    vk_ubo_put(0, data, bytes);
    s_e2.vs_bytes = bytes;
}''',
     '''    vk_ubo_put(0, data, bytes);
    s_e2.vs_bytes = bytes;
    s_e2.vs_ranged = 0;
}
/* vk vpc range (tools/patch_vk_vpc_range.py): rows [first, first + count) and the tail at row 512. */
static void vk_eng_bind_vs_constants_range(void* user, const void* rows, u32 first, u32 count,
                                           const void* tail, u32 tail_bytes, u32 total_bytes)
{
    const u32 tail_off = RSX_MAX_VERTEX_CONSTANTS * 16u;
    if (!s_g.on || !rows || first > RSX_MAX_VERTEX_CONSTANTS || count > RSX_MAX_VERTEX_CONSTANTS - first ||
        total_bytes > (u32)s_g.ps_off || tail_off + tail_bytes > total_bytes) {
        /* not representable: the whole block, as before */
        static u8 blk[VK_VPCONST_BYTES];
        if (!rows || total_bytes > sizeof blk || tail_off + tail_bytes > total_bytes) { vk_eng_bind_vs_constants(user, NULL, 0); return; }
        memcpy(blk, rows, tail_off);
        memcpy(blk + tail_off, tail, tail_bytes);
        vk_eng_bind_vs_constants(user, blk, total_bytes);
        return;
    }
    (void)user;
    if (count) vk_ubo_put((size_t)first * 16u, (const u8*)rows + first * 16u, count * 16u);
    if (tail_bytes) vk_ubo_put(tail_off, tail, tail_bytes);
    s_e2.vs_bytes = total_bytes;
    s_e2.vs_ranged = 1; s_e2.vs_lo = first; s_e2.vs_n = count; s_e2.vs_tail = tail_bytes;
}''',
     "vk vpc range: bind")
edit(VKB,
     '''    memcpy(vk_ring_alloc(vs_bytes, s_ubo_align, &vs_off), s_ubo_cpu, vs_bytes);''',
     '''    {   u8* const vd = (u8*)vk_ring_alloc(vs_bytes, s_ubo_align, &vs_off);
        if (s_e2.vs_ranged && s_e2.vs_bytes == vs_bytes) {   /* vk vpc range: only what the program reads */
            const u32 tail_off = RSX_MAX_VERTEX_CONSTANTS * 16u;
            if (s_e2.vs_n) memcpy(vd + s_e2.vs_lo * 16u, s_ubo_cpu + s_e2.vs_lo * 16u, s_e2.vs_n * 16u);
            if (s_e2.vs_tail) memcpy(vd + tail_off, s_ubo_cpu + tail_off, s_e2.vs_tail);
        } else
            memcpy(vd, s_ubo_cpu, vs_bytes);
    }''',
     "vk vpc range: ring copy")
edit(VKB,
     '''    .bind_vs_constants    = vk_eng_bind_vs_constants,''',
     '''    .bind_vs_constants    = vk_eng_bind_vs_constants,
    .bind_vs_constants_range = vk_eng_bind_vs_constants_range,''',
     "vk vpc range: hook")
