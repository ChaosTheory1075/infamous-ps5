# slow pipe: split a slow engine pipeline miss into vp decompile / fp decompile+patches / backend build
edit("libs/video/rsx_draw_engine.c",
     '''    const uint64_t ft_c0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    u32 handle = 0;
    int vi = 1, fi = 1;''',
     '''    const uint64_t ft_c0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    /* A miss over 100 ms says where it went ("[rsx engine] slow pipeline" lines): inFAMOUS 2's
     * cutscenes stalled 0.8-1.9 s in single misses whose SPIR-V compile took 10 ms. */
    const uint64_t sp0 = ps3_ft_now();
    uint64_t sp_vp = sp0, sp_fp = sp0;
    u32 handle = 0;
    int vi = 1, fi = 1;''',
     "slow pipe: start")
edit("libs/video/rsx_draw_engine.c",
     '''        fi = rsx_fp_decompile_buffered_shadow_color_expand_vol_ex(fp_uc, fp_size, fp_ctrl, cube_mask, vol_mask,''',
     '''        sp_vp = ps3_ft_now();
        fi = rsx_fp_decompile_buffered_shadow_color_expand_vol_ex(fp_uc, fp_size, fp_ctrl, cube_mask, vol_mask,''',
     "slow pipe: vp done")
edit("libs/video/rsx_draw_engine.c",
     '''    if (vi > 0 && fi > 0)
        handle = g.be->pipeline_create(g.be->user, s_vs_hlsl, s_ps_hlsl, rs,''',
     '''    sp_fp = ps3_ft_now();
    if (sp_vp == sp0) sp_vp = sp_fp;   /* the fixed-function pair: no decompile */
    if (vi > 0 && fi > 0)
        handle = g.be->pipeline_create(g.be->user, s_vs_hlsl, s_ps_hlsl, rs,''',
     "slow pipe: fp done")
edit("libs/video/rsx_draw_engine.c",
     '''    if (ft_c0) ps3_ft_span(PS3_FT_COMPILE, 0, handle != 0, 0, ft_c0, ps3_ft_now());''',
     '''    if (ft_c0) ps3_ft_span(PS3_FT_COMPILE, 0, handle != 0, 0, ft_c0, ps3_ft_now());
    {   const uint64_t sp1 = ps3_ft_now();
        static u32 said;
        if (sp1 - sp0 > 100000000ull && said < 200) { said++;
            fprintf(stderr, "[rsx engine] slow pipeline miss %.0f ms: vp decompile %.0f ms (%u instrs, %zu chars), "
                            "fp decompile+patches %.0f ms (%u bytes, %zu chars), backend %.0f ms%s\\n",
                    (sp1 - sp0) / 1e6, (sp_vp - sp0) / 1e6, (unsigned)vp_instrs, strlen(s_vs_hlsl),
                    (sp_fp - sp_vp) / 1e6, (unsigned)fp_size, strlen(s_ps_hlsl), (sp1 - sp_fp) / 1e6,
                    handle ? "" : " (failed)"); } }''',
     "slow pipe: report")
