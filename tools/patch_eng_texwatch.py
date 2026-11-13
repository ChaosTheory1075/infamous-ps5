
# eng texwatch: log what watched texture addresses resolve to, for every draw (effects-buffer hunt)
# PS3RECOMP_ENG_TEXWATCH=<hex>[,<hex>...] (up to 8 guest offsets): once per (fragment program, unit,
# offset, target) a line with the target surface, the texture's size/format/filter/location, the
# backend handle it resolved to, and whether that handle is an engine colour surface (an RT) or not.
# For inFAMOUS 2's soft particles / quarter-res effects (real PS3 chain: 0xF770000 512x288 depth ->
# 0xB9E000 512x288 particles -> 0xE3C000 320x180 -> full-res composite, work/ps3_if2_20261103).
edit("libs/video/rsx_draw_engine.c",
     '''    /* PS3RECOMP_ENG_SKIP_FP=<hex>[,<hex>...]: drop draws whose fragment
     * program has that structural hash (TEXSTATE's fp=).''',
     '''    /* eng texwatch: PS3RECOMP_ENG_TEXWATCH=<hex>[,..] -- what a watched texture offset resolves to */
    { static u32 wo[8]; static int nw = -1;
      if (__builtin_expect(nw < 0, 0)) { nw = 0; const char* e = getenv("PS3RECOMP_ENG_TEXWATCH");
          while (e && *e && nw < 8) { char* x; wo[nw++] = (u32)strtoul(e, &x, 16); e = (*x == ',') ? x + 1 : NULL; } }
      if (nw && n_targets) {
          static u64 seen[512]; static u32 ns;
          const eng_fp_memo* fpm = NULL;
          const u64 fk = eng_guest_programs(NULL, &fpm) && fpm ? fpm->structural : 0;
          for (u32 u = 0; u < RSX_BE_MAX_TEXTURES; u++) {
              rsx_dsp_texture t; rsx_dsp_get_texture(&g.rsx, u, &t);
              if (!t.enabled) continue;
              int hit = 0; for (int i = 0; i < nw; i++) hit |= (t.offset == wo[i]);
              if (!hit) continue;
              const u64 key = fk ^ ((u64)t.offset << 20) ^ ((u64)u << 56) ^ ((u64)g.surfaces[targets[0]].offset << 4);
              u32 k = 0; while (k < ns && seen[k] != key) k++;
              if (k < ns || ns >= 512) continue;
              seen[ns++] = key;
              int rt = -1; for (u32 i = 0; i < g.n_surfaces; i++) if (textures[u] && g.surfaces[i].handle == textures[u]) rt = (int)i;
              fprintf(stderr, "[texwatch] frame %u fp %016llx into 0x%08X %ux%u: unit %u off 0x%08X loc %u fmt 0x%02X %ux%u filter 0x%08X (min_lin %u mag_lin %u) -> h%u %s",
                      g.frames, (unsigned long long)fk, g.surfaces[targets[0]].offset, g.surfaces[targets[0]].w, g.surfaces[targets[0]].h,
                      u, t.offset, t.location, t.format, t.width, t.height, t.filter,
                      samplers[u].min_linear, samplers[u].mag_linear, textures[u], rt >= 0 ? "RT" : "not-an-RT");
              if (rt >= 0) fprintf(stderr, " (surface 0x%08X %ux%u)", g.surfaces[rt].offset, g.surfaces[rt].w, g.surfaces[rt].h);
              fprintf(stderr, " verts %u\\n", dc.n_verts);
          } } }

    /* PS3RECOMP_ENG_SKIP_FP=<hex>[,<hex>...]: drop draws whose fragment
     * program has that structural hash (TEXSTATE's fp=).''',
     "eng texwatch")
