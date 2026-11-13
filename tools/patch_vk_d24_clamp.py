
# vk d24 clamp: depth 1.0 -> 0xFFFFFF in the depth->A8R8G8B8 copies (it wrapped to 0: the sky read as nearest)
# Both copies computed (uint)(d * 16777215 + 0.5); for d = 1.0 that is 16777215.5, which in float32
# rounds to 16777216 = 0x1000000, whose low 24 bits are 0. Every far-plane / cleared pixel (the whole
# sky) came out as depth 0 in the A8R8G8B8 view inFAMOUS 2 decodes: its soft particles discard where
# scene <= particle depth, so all smoke, fire and glow in front of the sky was thrown away and the rest
# was cut along building silhouettes at the 512x288 grid -- the console's "solid blocks with
# stair-stepped edges" (BC-250 proof: work/occ6 depth copy 0 in the sky, real RSX 1.0 there;
# PS3RECOMP_ENG_ZPROBE read 0 right after the 1.0 clear). Clamped to 0xFFFFFF.
# PS3_VK_D24_CLAMP=0 is the old (wrapping) GPU shader; the CPU fallback is always fixed.
edit("libs/video/rsx_vulkan_backend.c",
     '''            const u32 d24 = (u32)(v * 16777215.0f + 0.5f);''',
     '''            u32 d24 = (u32)(v * 16777215.0f + 0.5f);
            if (d24 > 0xFFFFFFu) d24 = 0xFFFFFFu;   /* vk d24 clamp: 1.0 rounded to 0x1000000 */''',
     "vk d24 clamp cpu")
edit("libs/video/rsx_vulkan_backend.c",
     '''    "    uint v = (uint)(d * 16777215.0 + 0.5);\\n"
    "    return float4((float)((v >> 8) & 255u), (float)(v & 255u), 0.0, (float)((v >> 16) & 255u)) / 255.0;\\n"
    "}\\n";''',
     '''    "    uint v = min((uint)(d * 16777215.0 + 0.5), 16777215u);\\n"   /* vk d24 clamp */
    "    return float4((float)((v >> 8) & 255u), (float)(v & 255u), 0.0, (float)((v >> 16) & 255u)) / 255.0;\\n"
    "}\\n";
static const char* const s_dz_ps_old =   /* PS3_VK_D24_CLAMP=0: the wrapping original */
    "Texture2D    rsx_tex[16] : register(t0);\\n"
    "SamplerState rsx_samp[16] : register(s0);\\n"
    "struct PSInput { float4 pos:SV_Position; };\\n"
    "float4 main(PSInput input) : SV_TARGET {\\n"
    "    float d = saturate(rsx_tex[0].Load(int3(int2(input.pos.xy), 0)).x);\\n"
    "    uint v = (uint)(d * 16777215.0 + 0.5);\\n"
    "    return float4((float)((v >> 8) & 255u), (float)(v & 255u), 0.0, (float)((v >> 16) & 255u)) / 255.0;\\n"
    "}\\n";''',
     "vk d24 clamp gpu")
edit("libs/video/rsx_vulkan_backend.c",
     '''        s_dz_pipe = vk_eng_pipeline_create(user, s_lp_vs, s_dz_ps, &rs, &lay, 16u, RSX_BE_FMT_R8G8B8A8, 1u);''',
     '''        { const char* e = getenv("PS3_VK_D24_CLAMP");   /* vk d24 clamp */
          s_dz_pipe = vk_eng_pipeline_create(user, s_lp_vs, (e && *e == '0') ? s_dz_ps_old : s_dz_ps, &rs, &lay, 16u, RSX_BE_FMT_R8G8B8A8, 1u); }''',
     "vk d24 clamp switch")
