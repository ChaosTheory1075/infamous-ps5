
# eng clearlog: PS3RECOMP_ENG_CLEARLOG=<n> -- the first n depth/stencil clears: mask, colour targets, zeta, value, frame
# DIAGNOSTIC for the inFAMOUS 2 sky-depth hunt (2026-11-03): reports a depth clear that sink_clear drops
# because no colour target is bound (the early return), as well as the ones it applies.
edit("libs/video/rsx_draw_engine.c",
     '''    u32 targets[RSX_BE_MAX_COLOR_TARGETS];
    const u32 n_targets = eng_current_target_set(targets);
    if (!n_targets) return;

    /* PS3RECOMP_ENG_MRTLOG=2: each distinct colour clear''',
     '''    u32 targets[RSX_BE_MAX_COLOR_TARGETS];
    const u32 n_targets = eng_current_target_set(targets);
    { static int cl = -1; if (cl < 0) { const char* e = getenv("PS3RECOMP_ENG_CLEARLOG"); cl = e ? atoi(e) : 0; }   /* eng clearlog */
      if (cl > 0 && (mask & (RSX_CLEAR_DEPTH | RSX_CLEAR_STENCIL))) { cl--;
          rsx_dsp_surface sf; rsx_dsp_get_surface(&g.rsx, &sf);
          fprintf(stderr, "[clearlog] frame %u mask 0x%02X targets %u zeta 0x%08X clip %ux%u value 0x%08X%s\\n", g.frames, mask,
                  n_targets, sf.zeta_offset, sf.clip_w, sf.clip_h, rsx_dsp_reg(&g.rsx, M_ZSTENCIL_CLEAR), n_targets ? "" : " DROPPED (no colour target)"); } }
    if (!n_targets) return;

    /* PS3RECOMP_ENG_MRTLOG=2: each distinct colour clear''',
     "eng clearlog")
