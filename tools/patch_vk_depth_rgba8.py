
# depth_snapshot_rgba8 on the GPU: the depth target's R32F copy (vk_eng_depth_snapshot, recorded in
# the batch) turned into the Z24-as-A8R8G8B8 encoding by a one-target full-screen pass -- the CPU
# path's encoding exactly: d24 = (u32)(clamp(d, 0, 1) * 16777215 + 0.5); R = d[15:8], G = d[7:0],
# B = stencil (0: this depth format has no stencil aspect, as before), A = d[23:16]. The CPU path
# flushed the batch, waited for the GPU, converted w*h pixels and uploaded them again, every time
# the game sampled a depth buffer as a colour texture. PS3_VK_DEPTH_RGBA8_GPU=0 keeps the CPU path;
# any failure here falls back to it.
VK_DEPTH8 = r'''
/* ---- E6: depth -> A8R8G8B8 on the GPU ------------------------------------- */
static const char* const s_dz_ps =
    "Texture2D    rsx_tex[16] : register(t0);\n"
    "SamplerState rsx_samp[16] : register(s0);\n"
    "struct PSInput { float4 pos:SV_Position; };\n"
    "float4 main(PSInput input) : SV_TARGET {\n"
    "    float d = saturate(rsx_tex[0].Load(int3(int2(input.pos.xy), 0)).x);\n"
    "    uint v = (uint)(d * 16777215.0 + 0.5);\n"
    "    return float4((float)((v >> 8) & 255u), (float)(v & 255u), 0.0, (float)((v >> 16) & 255u)) / 255.0;\n"
    "}\n";
static u32 s_dz_pipe;
static int s_dz_failed = -1;
static struct { u32 depth, w, h, rt; } s_dz_cache[32];
static u32 vk_eng_depth_rgba8_gpu(void* user, u32 depth, u32 w, u32 h)
{
    if (s_dz_failed < 0) { const char* e = getenv("PS3_VK_DEPTH_RGBA8_GPU"); s_dz_failed = (e && *e == '0') ? 1 : 0; }
    if (s_dz_failed || !s_g.on) return 0;
    vk_eng_obj* z = vk_eng_get(depth, VK_ENG_DEPTH);
    if (!z || s_vk.depth_format != VK_FORMAT_D32_SFLOAT) return 0;
    if (w > z->w) w = z->w;
    if (h > z->h) h = z->h;
    if (!w || !h) return 0;
    if (!s_dz_pipe) {
        rsx_be_render_state rs; memset(&rs, 0, sizeof rs);
        rs.color_mask = 0xFFFFFFFFu;
        rsx_vertex_layout_plan lay; memset(&lay, 0, sizeof lay);
        lay.mask = 1u; lay.stride = 16u; lay.count = 1u;
        for (u32 i = 0; i < RSX_DSP_NUM_VERTEX_ATTR; i++) lay.slot_by_attr[i] = -1;
        lay.slot_by_attr[0] = 0;
        s_dz_pipe = vk_eng_pipeline_create(user, s_lp_vs, s_dz_ps, &rs, &lay, 16u, RSX_BE_FMT_R8G8B8A8, 1u);
        if (!s_dz_pipe) { s_dz_failed = 1; VK_LOG("engine: GPU depth->RGBA8 pipeline failed; the CPU converts\n"); return 0; }
        VK_LOG("engine: depth->RGBA8 snapshots on the GPU\n");
    }
    /* One RGBA8 target per (depth target, size): sampled by draws already recorded, so never
     * reused for another depth target while it may be in flight; evicted round robin. */
    int slot = -1;
    for (int i = 0; i < 32; i++)
        if (s_dz_cache[i].rt && s_dz_cache[i].depth == depth && s_dz_cache[i].w == w && s_dz_cache[i].h == h
            && vk_eng_get(s_dz_cache[i].rt, VK_ENG_COLOR)) { slot = i; break; }
    if (slot < 0) {
        static int next;
        slot = next++ & 31;
        if (s_dz_cache[slot].rt) vk_eng_release(user, s_dz_cache[slot].rt);
        s_dz_cache[slot].rt = vk_eng_color_target_create(user, RSX_BE_FMT_R8G8B8A8, w, h, NULL, 0);
        if (!s_dz_cache[slot].rt) { s_dz_cache[slot].depth = 0; return 0; }
        s_dz_cache[slot].depth = depth; s_dz_cache[slot].w = w; s_dz_cache[slot].h = h;
    }
    const u32 src = vk_eng_depth_snapshot(user, depth, z->w, z->h);
    if (!src) return 0;
    const u32 rt = s_dz_cache[slot].rt;

    static u8 vs_save[VK_VPCONST_BYTES], ps_save[(RSX_FP_MAX_INLINE_CONSTANTS + 1u) * 16u];
    __typeof__(s_eng_bound) bound = s_eng_bound;
    const u32 pipe = s_e2.pipeline, vsb = s_e2.vs_bytes, psb = s_e2.ps_bytes, mask = s_e2.tex_mask;
    u32 tex[RSX_BE_MAX_TEXTURES]; rsx_be_sampler_desc samp[RSX_BE_MAX_TEXTURES];
    memcpy(tex, s_e2.tex, sizeof tex); memcpy(samp, s_e2.samp, sizeof samp);
    float vp[4]; u32 sc[4]; memcpy(vp, s_e2.vp, sizeof vp); memcpy(sc, s_e2.sc, sizeof sc);
    const int have_vp = s_e2.have_vp, have_sc = s_e2.have_sc;
    const u32 sref = s_e2.stencil_ref;
    if (vsb && vsb <= sizeof vs_save) memcpy(vs_save, s_g.ubo.ptr, vsb);
    if (psb && psb <= sizeof ps_save) memcpy(ps_save, (u8*)s_g.ubo.ptr + s_g.ps_off, psb);

    vk_eng_bind_targets(user, &rt, 1u, 0u);
    vk_eng_bind_pipeline(user, s_dz_pipe);
    static const float zero16[4] = { 0.0f, 0.0f, 0.0f, 0.0f };
    vk_eng_bind_vs_constants(user, zero16, 16u);
    vk_eng_bind_ps_constants(user, zero16, 16u);
    u32 t[RSX_BE_MAX_TEXTURES] = { 0 }; rsx_be_sampler_desc sd[RSX_BE_MAX_TEXTURES];
    memset(sd, 0, sizeof sd);
    sd[0].wrap_s = sd[0].wrap_t = sd[0].wrap_r = 3;
    t[0] = src;
    vk_eng_bind_textures(user, t, sd, 1u);
    s_e2.have_vp = 0; s_e2.have_sc = 0; s_e2.stencil_ref = 0;
    static const float tri[12] = { -1.0f, -1.0f, 0.0f, 1.0f,  3.0f, -1.0f, 0.0f, 1.0f,  -1.0f, 3.0f, 0.0f, 1.0f };
    vk_eng_draw(user, RSX_TOPOLOGY_TRIANGLES, tri, 3u, 16u, NULL, 0u);

    s_eng_bound = bound;
    s_e2.pipeline = pipe; s_e2.vs_bytes = vsb; s_e2.ps_bytes = psb; s_e2.tex_mask = mask;
    memcpy(s_e2.tex, tex, sizeof tex); memcpy(s_e2.samp, samp, sizeof samp);
    memcpy(s_e2.vp, vp, sizeof vp); memcpy(s_e2.sc, sc, sizeof sc);
    s_e2.have_vp = have_vp; s_e2.have_sc = have_sc; s_e2.stencil_ref = sref;
    if (vsb && vsb <= sizeof vs_save) memcpy(s_g.ubo.ptr, vs_save, vsb);
    if (psb && psb <= sizeof ps_save) memcpy((u8*)s_g.ubo.ptr + s_g.ps_off, ps_save, psb);
    return rt;
}
'''
edit("libs/video/rsx_vulkan_backend.c",
     "static u32 vk_eng_depth_snapshot_rgba8(void* user, u32 depth, u32 w, u32 h)\n{\n",
     "static u32 vk_eng_depth_rgba8_gpu(void* user, u32 depth, u32 w, u32 h);   /* E6, below */\n"
     "static u32 vk_eng_depth_snapshot_rgba8(void* user, u32 depth, u32 w, u32 h)\n{\n"
     "    { const u32 g = vk_eng_depth_rgba8_gpu(user, depth, w, h); if (g) return g; }\n",
     "vk depth8: hook")
edit("libs/video/rsx_vulkan_backend.c", "\nstatic const rsx_draw_backend s_vk_engine_backend = {\n",
     VK_DEPTH8 + "\nstatic const rsx_draw_backend s_vk_engine_backend = {\n", "vk depth8: pass")
