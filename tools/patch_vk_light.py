
# rsx_draw_backend.light_pass on Vulkan: inFAMOUS 2's SPU light job on the GPU, as the Metal backend
# does it (rsx_metal_backend.m eng_light_fs, ported line for line to HLSL). One full-screen triangle
# through the engine's own pipeline / target / texture / constant path into two persistent RGBA8
# targets (diffuse, specular), recorded in the batch like any engine draw; the engine's bound state
# and constant bytes are saved before and restored after. Without it the engine wrote the normals
# and depth back to guest memory every frame for the SPU job (a GPU sync and 7 MB each), the job
# lit 32x40 tiles on the SPUs, and every tile DMA went through the overlay checks.
VK_LIGHT = r'''
/* ---- E5: the GPU light pass (PS3RECOMP_ENG_GPU_LIGHT) --------------------- */
static const char* const s_lp_vs =
    "struct VSInput { float4 a0:ATTR0; };\n"
    "struct VSOutput { float4 pos:SV_Position; };\n"
    "VSOutput main(VSInput input) { VSOutput o; o.pos = input.a0; return o; }\n";
static const char* const s_lp_ps =
    "Texture2D    rsx_tex[16] : register(t0);\n"
    "SamplerState rsx_samp[16] : register(s0);\n"
    "struct GLight { float4 pos_type; float4 col_inner; float4 oacbn; float4 dir; };\n"
    "cbuffer PSConstants : register(b1) { float4 gl_m[4]; float4 gl_misc; GLight gl_l[128]; };\n"
    "struct PSInput { float4 pos:SV_Position; };\n"
    "struct PSOutput { float4 t0:SV_TARGET0; float4 t1:SV_TARGET1; };\n"
    "PSOutput main(PSInput input) {\n"
    "    int2 px = int2(input.pos.xy);\n"
    "    PSOutput o; o.t0 = float4(0.0, 0.0, 0.0, 0.0); o.t1 = float4(0.0, 0.0, 0.0, 0.0);\n"
    "    uint z24 = (uint)(saturate(rsx_tex[1].Load(int3(px, 0)).x) * 16777215.0);\n"
    "    if (z24 >= 0xFFFFFFu) return o;\n"
    "    float zf = (float)z24 / 16777216.0;\n"
    "    float u = (float)px.x / gl_misc.z, v = (float)px.y / gl_misc.w;\n"
    "    float4 h = u * gl_m[0] + v * gl_m[1] + zf * gl_m[2] + gl_m[3];\n"
    "    float3 P = h.xyz / h.w;\n"
    "    float4 nr = round(rsx_tex[0].Load(int3(px, 0)) * 255.0);\n"
    "    float3 N = normalize(nr.rgb * (2.0 / 255.0) - 1.0);\n"
    "    float s = exp2(nr.a * (8.0 / 255.0) - 0.88896);\n"
    "    float3 V = -normalize(P);\n"
    "    float3 acc = float3(0.0, 0.0, 0.0); float sp = 0.0;\n"
    "    int n = min((int)gl_misc.y, 128);\n"
    "    for (int k = 0; k < n; k++) {\n"
    "        GLight L = gl_l[k];\n"
    "        float3 Lv = L.pos_type.xyz - P; float d = length(Lv); float3 l = Lv / d;\n"
    "        float ndl = max(dot(N, l), 0.0);\n"
    "        float att = saturate((L.oacbn.x - d) / (L.oacbn.x - L.col_inner.w)); att *= att;\n"
    "        if (L.pos_type.w > 1.5) {\n"
    "            float c = saturate((dot(-l, L.dir.xyz) - L.oacbn.z) * -L.oacbn.y);\n"
    "            att *= c * c * (d > L.oacbn.w ? 1.0 : 0.0);\n"
    "        }\n"
    "        float w = att * ndl;\n"
    "        if (w <= 0.0) continue;\n"
    "        float3 C = L.col_inner.xyz * gl_misc.x;\n"
    "        float ndh = max(dot(N, normalize(l + V)), 0.0);\n"
    "        acc += w * C;\n"
    "        sp += w * length(C) * (1.0 + 25.0 / 27.0 * s) * pow(1.0 + s * (1.0 - ndh), -8.0);\n"
    "    }\n"
    "    const float K = 0.35355339 * 255.0;\n"
    "    float3 q = sqrt(acc);\n"
    "    float a = min(255.0, floor(max(1.0, max(q.r, max(q.g, q.b))) * K));\n"
    "    o.t0 = float4(min(float3(255.0, 255.0, 255.0), floor(q * K * 255.0 / a)), a) / 255.0;\n"
    "    o.t1 = float4(0.0, 0.0, 0.0, min(255.0, floor(sqrt(sp) * K)) / 255.0);\n"
    "    return o;\n"
    "}\n";
static u32 s_lp_pipe, s_lp_out[2], s_lp_w, s_lp_h;
static int s_lp_failed;
static u32 vk_eng_light_pass(void* user, u32 normals, u32 depth, u32 w, u32 h,
                             const void* params, u32 param_bytes, u32* spec_out)
{
    if (s_lp_failed || !s_g.on || !normals || !depth || !w || !h || !params || !spec_out) return 0;
    if (!vk_eng_get(normals, VK_ENG_TEXTURE) && !vk_eng_get(normals, VK_ENG_COLOR)) return 0;
    if (!s_lp_pipe) {
        rsx_be_render_state rs; memset(&rs, 0, sizeof rs);
        rs.color_mask = 0xFFFFFFFFu; rs.color_mask_mrt = 0xFFFFFFFFu;
        rsx_vertex_layout_plan lay; memset(&lay, 0, sizeof lay);
        lay.mask = 1u; lay.stride = 16u; lay.count = 1u; lay.attrs[0] = 0;
        for (u32 i = 0; i < RSX_DSP_NUM_VERTEX_ATTR; i++) lay.slot_by_attr[i] = -1;
        lay.slot_by_attr[0] = 0;
        s_lp_pipe = vk_eng_pipeline_create(user, s_lp_vs, s_lp_ps, &rs, &lay, 16u, RSX_BE_FMT_R8G8B8A8, 2u);
        if (!s_lp_pipe) { s_lp_failed = 1; VK_LOG("engine: GPU light pass pipeline failed; the SPU job lights\n"); return 0; }
        VK_LOG("engine: GPU light pass on (two RGBA8 targets, full-screen pass)\n");
    }
    if (!s_lp_out[0] || s_lp_w != w || s_lp_h != h) {
        for (int k = 0; k < 2; k++) {
            if (s_lp_out[k]) vk_eng_release(user, s_lp_out[k]);
            s_lp_out[k] = vk_eng_color_target_create(user, RSX_BE_FMT_R8G8B8A8, w, h, NULL, 0);
            if (!s_lp_out[k]) { s_lp_out[0] = s_lp_out[1] = 0; return 0; }
        }
        s_lp_w = w; s_lp_h = h;
    }
    /* The engine's state, kept: it rebinds only what changes between its own draws. */
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

    const u32 rts[2] = { s_lp_out[0], s_lp_out[1] };
    vk_eng_bind_targets(user, rts, 2u, 0u);
    vk_eng_bind_pipeline(user, s_lp_pipe);
    static const float one16[4] = { 0.0f, 0.0f, 0.0f, 0.0f };
    vk_eng_bind_vs_constants(user, one16, 16u);
    vk_eng_bind_ps_constants(user, params, param_bytes);
    u32 t[RSX_BE_MAX_TEXTURES] = { 0 }; rsx_be_sampler_desc sd[RSX_BE_MAX_TEXTURES];
    memset(sd, 0, sizeof sd);
    for (u32 i = 0; i < 2; i++) { sd[i].wrap_s = sd[i].wrap_t = sd[i].wrap_r = 3; sd[i].max_lod = 0.0f; }
    t[0] = normals; t[1] = depth;
    vk_eng_bind_textures(user, t, sd, 3u);
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
    *spec_out = s_lp_out[1];
    return s_lp_out[0];
}
'''
edit("libs/video/rsx_vulkan_backend.c", "static void vk_eng_bind_pipeline(void* user, u32 pipeline) { (void)user; s_e2.pipeline = pipeline; }\n",
     "static void vk_eng_bind_pipeline(void* user, u32 pipeline) { (void)user; s_e2.pipeline = pipeline; }\n"
     "/* defined with the other engine draws below */\n"
     "static void vk_eng_bind_targets(void* user, const u32* surfaces, u32 count, u32 depth);\n"
     "static void vk_eng_bind_vs_constants(void* user, const void* data, u32 bytes);\n"
     "static void vk_eng_bind_ps_constants(void* user, const void* data, u32 bytes);\n"
     "static void vk_eng_bind_textures(void* user, const u32* textures, const rsx_be_sampler_desc* samplers, u32 mask);\n"
     "static void vk_eng_draw(void* user, rsx_topology topology, const void* vertices, u32 vertex_count,\n"
     "                        u32 stride, const u32* indices, u32 index_count);\n",
     "vk light: decls")
edit("libs/video/rsx_vulkan_backend.c", "    .readback             = vk_eng_readback,\n",
     "    .readback             = vk_eng_readback,\n    .light_pass           = vk_eng_light_pass,\n",
     "vk light: table")
edit("libs/video/rsx_vulkan_backend.c", "static const rsx_draw_backend s_vk_engine_backend = {\n",
     VK_LIGHT + "\nstatic const rsx_draw_backend s_vk_engine_backend = {\n", "vk light: pass")
