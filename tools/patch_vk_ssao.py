
# rsx_draw_backend.ssao_pass on Vulkan: inFAMOUS 2's SSAO job on the GPU, the Metal backend's five
# passes (rsx_metal_backend.m ssao_*_fs) ported to HLSL: half-res linear depth, 12-sample AO, two
# depth-aware blurs, the 2x upsample. The engine's targets are RGBA8 only, so the half-res depth (an
# R32F on Metal) travels as its four bytes and the AO planes (R8) in .r; both read back exactly.
# Metal's 64-bit reciprocal-estimate arithmetic is the same in 32 bits ((8192|base) << 19 is always
# 2^32 + base << 19). Constants: the C block's float X[12] / Y[12] / Z[12] are tightly packed, so the
# HLSL cbuffer reads them as float4[3] each (offsets 16, 64, 112; 320 bytes in all).
VK_SSAO = r'''
/* ---- E7: the GPU SSAO passes (PS3RECOMP_ENG_GPU_SSAO) ---------------------- */
#define VK_SSAO_COMMON \
    "Texture2D    rsx_tex[16] : register(t0);\n" \
    "SamplerState rsx_samp[16] : register(s0);\n" \
    "cbuffer PSConstants : register(b1) {\n" \
    "    float4 depth_ab; float4 X4[3]; float4 Y4[3]; float4 Z4[3]; float4 M[3];\n" \
    "    float4 C0, D0, E0, F0; float4 blur; float4 up; uint4 dims;\n" \
    "};\n" \
    "struct PSInput { float4 pos:SV_Position; };\n" \
    "static const uint LUT[32] = {\n" \
    "    0x7FFBE0, 0x7F87A6, 0x70EF72, 0x708B40, 0x638B12, 0x633AEA, 0x5792C4, 0x574AA0,\n" \
    "    0x4CCA7E, 0x4C9262, 0x430A44, 0x42D62A, 0x3A2E12, 0x39FDFA, 0x3215E4, 0x31F1D2,\n" \
    "    0x2AA9BE, 0x2A85AC, 0x23D59A, 0x23BD8E, 0x1D8576, 0x1D8576, 0x17AD5A, 0x17AD5A,\n" \
    "    0x124543, 0x124543, 0x0D392D, 0x0D392D, 0x08851A, 0x08851A, 0x041D07, 0x041D07 };\n" \
    "float ssao_recip(float x) {\n" \
    "    uint b = asuint(x);\n" \
    "    uint sgn = b & 0x80000000u, e = (b >> 23) & 0xFFu;\n" \
    "    uint re = (e == 0u) ? 255u : (e >= 253u ? 0u : 253u - e);\n" \
    "    uint est = sgn | (re << 23) | (LUT[(b >> 18) & 31u] & 0x7FFFFFu);\n" \
    "    int ee = (int)((est >> 23) & 0xFFu);\n" \
    "    if (ee == 0) return 0.0;\n" \
    "    uint A = ((est >> 10) & 0x1FFFu) << 19, P = (est & 0x3FFu) * (b & 0x7FFFFu), mant;\n" \
    "    if (A >= P) mant = ((A - P) >> 9) & 0x7FFFFFu;\n" \
    "    else { ee -= 1; if (ee == 0) return 0.0; mant = ((0u - 2u * (P - A)) >> 9) & 0x7FFFFFu; }\n" \
    "    return asfloat(sgn | ((uint)ee << 23) | mant);\n" \
    "}\n" \
    "float ssao_mul_rz(float a, float b) {\n" \
    "    float p = a * b;\n" \
    "    return (mad(a, b, -p) < 0.0 && p > 0.0) ? asfloat(asuint(p) - 1u) : p;\n" \
    "}\n" \
    "float ssao_sat(float x) { return x >= 1.0 ? asfloat(0x3F7FFFFFu) : max(x, 0.0); }\n" \
    "float ssao_z24(float d01) { return (float)(uint)(clamp(d01, 0.0, 1.0) * 16777215.0); }\n" \
    "float ssao_lin(float z24, float A, float B) {\n" \
    "    float k = A * asfloat(0x33800001u);\n" \
    "    float pe = mad(A, asfloat(0x33800001u), -k);\n" \
    "    if ((pe > 0.0 && k < 0.0) || (pe < 0.0 && k > 0.0)) k = asfloat(asuint(k) - 1u);\n" \
    "    float v = mad(z24, k, B);\n" \
    "    float r = ssao_recip(v);\n" \
    "    return mad(mad(-v, r, 1.0), r, r);\n" \
    "}\n" \
    "float hdv(int2 p) { uint4 q = (uint4)round(rsx_tex[1].Load(int3(p, 0)) * 255.0);\n" \
    "                    return asfloat(q.x | (q.y << 8) | (q.z << 16) | (q.w << 24)); }\n" \
    "float aob(int2 p) { return round(rsx_tex[0].Load(int3(p, 0)).r * 255.0); }\n" \
    "float4 pack_f(float v) { uint u = asuint(v);\n" \
    "    return float4((float)(u & 255u), (float)((u >> 8) & 255u), (float)((u >> 16) & 255u), (float)(u >> 24)) / 255.0; }\n" \
    "float Xk(int k) { return X4[k >> 2][k & 3]; }\n" \
    "float Yk(int k) { return Y4[k >> 2][k & 3]; }\n" \
    "float Zk(int k) { return Z4[k >> 2][k & 3]; }\n"
/* pass 1: half-res linear depth (t0 = depth R32F) */
static const char* const s_ss_hd = VK_SSAO_COMMON
    "float4 main(PSInput input) : SV_TARGET {\n"
    "    int2 p = int2(input.pos.xy) * 2;\n"
    "    return pack_f(ssao_lin(ssao_z24(rsx_tex[0].Load(int3(p, 0)).r), depth_ab.x, depth_ab.y));\n"
    "}\n";
/* pass 2: AO (t1 = hd, t2 = normals) */
static const char* const s_ss_ao = VK_SSAO_COMMON
    "float4 main(PSInput input) : SV_TARGET {\n"
    "    int2 p = int2(input.pos.xy);\n"
    "    int2 hm = int2(dims.zw) - 1;\n"
    "    float d = hdv(p);\n"
    "    float dc = clamp(d, E0.z, E0.w);\n"
    "    float rcp = ssao_recip(dc);\n"
    "    float q = d * rcp;\n"
    "    float3 nb = round(rsx_tex[2].Load(int3(p * 2, 0)).rgb * 255.0);\n"
    "    float3 n = mad(nb * (1.0 / 256.0), float3(2.0078430175781, 2.0078430175781, 2.0078430175781), float3(-1.0, -1.0, -1.0));\n"
    "    float3 n2 = mad(float3(n.z, n.z, n.z), M[2].xyz, mad(float3(n.y, n.y, n.y), M[1].xyz, n.x * M[0].xyz));\n"
    "    float dref = mad(n2.z, q, d);\n"
    "    float bx = mad(n2.x, rcp, 0.5), by = mad(n2.y, rcp, 0.5);\n"
    "    float sx = D0.y * rcp, sy = D0.z * rcp;\n"
    "    float hz = D0.w * q;\n"
    "    float e0 = E0.x * ssao_recip(q), e1 = E0.y * q;\n"
    "    float acc = 0.0;\n"
    "    for (int k = 0; k < 12; k++) {\n"
    "        int tx = p.x + (int)floor(mad(Xk(k), sx, bx));\n"
    "        int ty = p.y + (int)floor(mad(Yk(k), sy, by));\n"
    "        float ds = hdv(clamp(int2(tx, ty), int2(0, 0), hm));\n"
    "        float h = Zk(k) * hz;\n"
    "        float t = (ds - (dref - h)) * 0.5;\n"
    "        acc += mad(ssao_sat(mad(t, e0, e1)), h, clamp(t, 0.0, h));\n"
    "    }\n"
    "    acc *= ssao_recip(D0.x * q);\n"
    "    float v = ssao_sat(mad(acc, F0.x, F0.y));\n"
    "    float o = floor(ssao_mul_rz(v, 255.0 / 256.0) * 256.0) / 255.0;\n"
    "    return float4(o, o, o, o);\n"
    "}\n";
/* passes 3-4: depth-aware blur (t0 = ao, t1 = hd); horizontal and vertical */
#define VK_SSAO_BLUR(DX, DY) VK_SSAO_COMMON \
    "float4 main(PSInput input) : SV_TARGET {\n" \
    "    int2 p = int2(input.pos.xy); int2 dir = int2(" DX ", " DY ");\n" \
    "    int2 hm = int2(dims.zw) - 1;\n" \
    "    float d0 = hdv(p);\n" \
    "    float kk = blur.x * ssao_recip(d0);\n" \
    "    float w[5], a[5];\n" \
    "    for (int o = -2; o <= 2; o++) {\n" \
    "        int2 s = clamp(p + o * dir, int2(0, 0), hm);\n" \
    "        a[o + 2] = aob(s);\n" \
    "        w[o + 2] = max(0.0, mad(-abs(hdv(s) - d0), kk, 1.0)) * ((o == -2 || o == 2) ? blur.y : blur.z);\n" \
    "    }\n" \
    "    float num = mad(w[4], a[4], mad(w[3], a[3], mad(w[1], a[1], mad(w[0], a[0], a[2]))));\n" \
    "    float den = w[4] + (w[3] + (1.0 + (w[0] + w[1])));\n" \
    "    float r = floor(ssao_mul_rz(num, ssao_recip(den))) / 255.0;\n" \
    "    return float4(r, r, r, r);\n" \
    "}\n"
static const char* const s_ss_bh = VK_SSAO_BLUR("1", "0");
static const char* const s_ss_bv = VK_SSAO_BLUR("0", "1");
/* pass 5: 2x depth-aware upsample (t0 = ao, t1 = hd, t2 = depth R32F) */
static const char* const s_ss_up = VK_SSAO_COMMON
    "float4 main(PSInput input) : SV_TARGET {\n"
    "    int2 P = int2(input.pos.xy);\n"
    "    int2 hm = int2(dims.zw) - 1;\n"
    "    float Z = ssao_lin(ssao_z24(rsx_tex[2].Load(int3(P, 0)).r), up.x, up.y);\n"
    "    float kz = up.z * ssao_recip(Z);\n"
    "    int2 b = P >> 1;\n"
    "    int2 s = int2((P.x & 1) ? 1 : -1, (P.y & 1) ? 1 : -1);\n"
    "    int2 off[4] = { int2(0, 0), int2(0, s.y), int2(s.x, 0), s };\n"
    "    float bw[4] = { 9.0, 3.0, 3.0, 1.0 };\n"
    "    float eps[4] = { asfloat(0x3A6BEDFAu), asfloat(0x399D4952u), asfloat(0x399D4952u), asfloat(0x38D1B717u) };\n"
    "    float num = 0.0, den = 0.0;\n"
    "    for (int k = 0; k < 4; k++) {\n"
    "        int2 t = clamp(b + off[k], int2(0, 0), hm);\n"
    "        float w = mad(max(0.0, mad(-abs(hdv(t) - Z), kz, 1.0)), bw[k], eps[k]);\n"
    "        num = mad(w, aob(t), num);\n"
    "        den += w;\n"
    "    }\n"
    "    float r = floor(ssao_mul_rz(num, ssao_recip(den))) / 255.0;\n"
    "    return float4(r, r, r, r);\n"
    "}\n";
static u32 s_ss_pipe[5], s_ss_tex[4], s_ss_dims[4];
static int s_ss_failed;
/* One full-screen draw into `rt` with textures t0..t2, the engine's state kept. */
static void vk_eng_fs_pass(void* user, u32 pipe_h, u32 rt, const u32* texs, u32 ntex, const void* consts, u32 cbytes)
{
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
    vk_eng_bind_pipeline(user, pipe_h);
    static const float zero16[4] = { 0.0f, 0.0f, 0.0f, 0.0f };
    vk_eng_bind_vs_constants(user, zero16, 16u);
    vk_eng_bind_ps_constants(user, consts, cbytes);
    u32 t[RSX_BE_MAX_TEXTURES] = { 0 }; rsx_be_sampler_desc sd[RSX_BE_MAX_TEXTURES];
    memset(sd, 0, sizeof sd);
    u32 m = 0;
    for (u32 i = 0; i < ntex && i < RSX_BE_MAX_TEXTURES; i++) {
        t[i] = texs[i]; sd[i].wrap_s = sd[i].wrap_t = sd[i].wrap_r = 3;
        if (texs[i]) m |= 1u << i;
    }
    vk_eng_bind_textures(user, t, sd, m);
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
}
static u32 vk_eng_ssao_pass(void* user, u32 depth, u32 normals, const void* consts, u32 const_bytes,
                            u32 fw, u32 fh, u32 hw, u32 hh)
{
    if (s_ss_failed || !s_g.on || !depth || !normals || !consts || !fw || !fh || !hw || !hh) return 0;
    if (const_bytes < 320u) return 0;
    if (!s_ss_pipe[0]) {
        const char* ps[5] = { s_ss_hd, s_ss_ao, s_ss_bh, s_ss_bv, s_ss_up };
        rsx_be_render_state rs; memset(&rs, 0, sizeof rs);
        rs.color_mask = 0xFFFFFFFFu;
        rsx_vertex_layout_plan lay; memset(&lay, 0, sizeof lay);
        lay.mask = 1u; lay.stride = 16u; lay.count = 1u;
        for (u32 i = 0; i < RSX_DSP_NUM_VERTEX_ATTR; i++) lay.slot_by_attr[i] = -1;
        lay.slot_by_attr[0] = 0;
        for (int k = 0; k < 5; k++)
            if (!(s_ss_pipe[k] = vk_eng_pipeline_create(user, s_lp_vs, ps[k], &rs, &lay, 16u, RSX_BE_FMT_R8G8B8A8, 1u))) {
                s_ss_failed = 1; VK_LOG("engine: GPU SSAO pass %d pipeline failed; the SPU job runs\n", k); return 0;
            }
        VK_LOG("engine: GPU SSAO on (five passes, RGBA8 intermediates)\n");
    }
    if (!s_ss_tex[0] || s_ss_dims[0] != fw || s_ss_dims[1] != fh || s_ss_dims[2] != hw || s_ss_dims[3] != hh) {
        for (int k = 0; k < 4; k++) {
            if (s_ss_tex[k]) vk_eng_release(user, s_ss_tex[k]);
            s_ss_tex[k] = vk_eng_color_target_create(user, RSX_BE_FMT_R8G8B8A8, k == 3 ? fw : hw, k == 3 ? fh : hh, NULL, 0);
            if (!s_ss_tex[k]) { for (int j = 0; j < 4; j++) s_ss_tex[j] = 0; return 0; }
        }
        s_ss_dims[0] = fw; s_ss_dims[1] = fh; s_ss_dims[2] = hw; s_ss_dims[3] = hh;
    }
    /* t0 / t1 / t2 per pass, as the shaders read them */
    const u32 hd = s_ss_tex[0], aA = s_ss_tex[1], aB = s_ss_tex[2], out = s_ss_tex[3];
    const u32 t_hd[3] = { depth, 0, 0 };
    const u32 t_ao[3] = { 0, hd, normals };
    const u32 t_bh[3] = { aA, hd, 0 };
    const u32 t_bv[3] = { aB, hd, 0 };
    const u32 t_up[3] = { aA, hd, depth };
    vk_eng_fs_pass(user, s_ss_pipe[0], hd,  t_hd, 1u, consts, const_bytes);
    vk_eng_fs_pass(user, s_ss_pipe[1], aA,  t_ao, 3u, consts, const_bytes);
    vk_eng_fs_pass(user, s_ss_pipe[2], aB,  t_bh, 2u, consts, const_bytes);
    vk_eng_fs_pass(user, s_ss_pipe[3], aA,  t_bv, 2u, consts, const_bytes);
    vk_eng_fs_pass(user, s_ss_pipe[4], out, t_up, 3u, consts, const_bytes);
    return out;
}
'''
edit("libs/video/rsx_vulkan_backend.c", "\nstatic const rsx_draw_backend s_vk_engine_backend = {\n",
     VK_SSAO + "\nstatic const rsx_draw_backend s_vk_engine_backend = {\n", "vk ssao: passes")
edit("libs/video/rsx_vulkan_backend.c", "    .light_pass           = vk_eng_light_pass,\n",
     "    .light_pass           = vk_eng_light_pass,\n    .ssao_pass            = vk_eng_ssao_pass,\n", "vk ssao: table")
