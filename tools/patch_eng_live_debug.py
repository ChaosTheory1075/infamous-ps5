
# eng live debug: a live frame capture and render-state overrides through PS3_TOGGLE_FILE
# PS3RECOMP_ENG_CAPTURE=<n>: when the file sets a new value n > 0, the next n frames log every draw
#   ("[cap]": programs, primitive, vertex count, target, depth/cull/blend/alpha-test state, colour
#   mask and the CPU-side position range) and every dropped draw with its reason.
# PS3RECOMP_ENG_DBG_RS=<bits>: force, for every draw from the next one on: 1 alpha test off,
#   2 depth test off, 4 culling off, 8 blending off, 16 colour mask all channels, 32 depth write on.
# Both read once a frame; the overrides change the pipeline key, so new pipelines are built.
edit("libs/video/rsx_draw_engine.c",
     '''static void eng_drop(const char* why, u32 prim)
{
    static int on = -1; static u32 from;''',
     '''static u32 s_cap_until;   /* PS3RECOMP_ENG_CAPTURE: frames below this log every draw */
static int s_dbg_rs;        /* PS3RECOMP_ENG_DBG_RS: render-state override bits */
static void eng_live_debug_frame(void)
{
    static u32 last_frame = ~0u; static int last_cap;
    if (g.frames == last_frame) return;
    last_frame = g.frames;
    const int cap = ps3_toggle_get("PS3RECOMP_ENG_CAPTURE", 0);
    if (cap != last_cap) {
        last_cap = cap;
        if (cap > 0) { s_cap_until = g.frames + (u32)cap; fprintf(stderr, "[cap] capture of %d frames from frame %u\\n", cap, g.frames); }
    }
    s_dbg_rs = ps3_toggle_get("PS3RECOMP_ENG_DBG_RS", 0);
}
static void eng_drop(const char* why, u32 prim)
{
    if (g.frames < s_cap_until)
        fprintf(stderr, "[cap] f=%u d=%u DROP %s prim=%u verts=%u fetch_ok=%d\\n", g.frames, g.guest_draws, why, prim,
                dc.n_verts, dc.fetch_ok);
    static int on = -1; static u32 from;''',
     "eng live debug core")
edit("libs/video/rsx_draw_engine.c",
     '''    DS_MARK(ns_tex);
    int pipeline_is_fixed = 1;''',
     '''    eng_live_debug_frame();
    if (s_dbg_rs) {   /* PS3RECOMP_ENG_DBG_RS */
        if (s_dbg_rs & 1) rs.alpha_test_enable = 0;
        if (s_dbg_rs & 2) rs.depth_test = 0;
        if (s_dbg_rs & 4) rs.cull_enable = 0;
        if (s_dbg_rs & 8) { rs.blend_enable = 0; rs.blend_mrt = 0; }
        if (s_dbg_rs & 16) { rs.color_mask = 0x01010101u; rs.color_mask_mrt = 0xFFFFu; }
        if (s_dbg_rs & 32) rs.depth_write = 1;
    }
    DS_MARK(ns_tex);
    int pipeline_is_fixed = 1;''',
     "eng live debug rs")
edit("libs/video/rsx_draw_engine.c",
     '''    /* PS3_ASPECT_HUD_AFTER=<fp hex>[,<fp hex>..]: the title's 2D overlay for''',
     '''    if (g.frames < s_cap_until) {   /* PS3RECOMP_ENG_CAPTURE */
        const eng_vp_memo* vpm = NULL; const eng_fp_memo* fpm = NULL;
        eng_guest_programs(&vpm, &fpm);
        float mn[4] = { 1e30f, 1e30f, 1e30f, 1e30f }, mx[4] = { -1e30f, -1e30f, -1e30f, -1e30f };
        const s8 ps = layout.slot_by_attr[0];
        if (ps >= 0 && dc.verts && !(dc.vbuf_hit && indexed))
            for (u32 v = 0; v < uploaded_hud_n(dc.n_verts, n_draw, indexed); v++) {
                const float* q = (const float*)((const u8*)dc.verts + (size_t)v * layout.stride + (size_t)ps * 16u);
                for (int c = 0; c < 4; c++) { if (q[c] < mn[c]) mn[c] = q[c]; if (q[c] > mx[c]) mx[c] = q[c]; } }
        fprintf(stderr, "[cap] f=%u d=%u p=%u prim=%u n=%u nt=%u rt=0x%08X %ux%u vp=%016llx fp=%016llx"
                        " z=%u/%u/0x%X cull=%u/0x%X/0x%X cmask=0x%08X/0x%X blend=%u/0x%X at=%u/0x%X/0x%X vtex=0x%X"
                        " pos x[%g,%g] y[%g,%g] z[%g,%g] w[%g,%g]\\n",
                g.frames, g.guest_draws, pipeline, prim, dc.n_verts, n_targets, g.surfaces[target].offset,
                g.surfaces[target].w, g.surfaces[target].h,
                (unsigned long long)(vpm ? vpm->hash : 0), (unsigned long long)(fpm ? fpm->structural : 0),
                rs.depth_test, rs.depth_write, rs.depth_func, rs.cull_enable, rs.cull_face, rs.front_face,
                rs.color_mask, rs.color_mask_mrt, rs.blend_enable, rs.blend_mrt,
                rs.alpha_test_enable, rs.alpha_func, rs.alpha_ref_raw, vtex_mask,
                mn[0], mx[0], mn[1], mx[1], mn[2], mx[2], mn[3], mx[3]);
    }
    /* PS3_ASPECT_HUD_AFTER=<fp hex>[,<fp hex>..]: the title's 2D overlay for''',
     "eng live debug capture")
