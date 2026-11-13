
# eng zprobe: PS3RECOMP_ENG_ZPROBE=<sec>:<zeta hex>:<x>:<y> -- one frame, which draw changes the depth at one pixel
# DIAGNOSTIC (inFAMOUS 2 sky depth hunt, 2026-11-03: the sky reads 0 in our full-res depth, 1.0 on the
# real RSX). <sec> seconds into the run, for one frame: before every draw into that zeta, the depth at
# (x, y) is read back through the depth->RGBA8 copy (a flush per draw: debugging only) and every change
# is printed with the previous draw's fragment program, depth func/write/clamp state and vertex count.
edit("libs/video/rsx_draw_engine.c",
     '''    const u32 depth_handle = (zslot != ENG_INVALID) ? g.zdepths[zslot].handle : 0;
    if (zslot != ENG_INVALID && !g.zdepths[zslot].cleared) {''',
     '''    /* eng zprobe */
    { static int zi; static long zsec = -1; static u32 zoff, zx, zy, zframe = ~0u; static int zdone;
      static unsigned long long zt0; static float zlast = -1.0f; static u64 zprev_fp; static u32 zprev_n, zprev_zs;
      if (!zi) { zi = 1; const char* e = getenv("PS3RECOMP_ENG_ZPROBE");
          if (e) { char* d; zsec = strtol(e, &d, 10); if (*d == ':') zoff = (u32)strtoul(d + 1, &d, 16);
                   if (*d == ':') zx = (u32)strtoul(d + 1, &d, 10); if (*d == ':') zy = (u32)strtoul(d + 1, &d, 10); } }
      if (zsec >= 0 && !zdone && zslot != ENG_INVALID && g.be->readback) {
          extern unsigned long long ps3_ms_now(void);
          if (!zt0) zt0 = ps3_ms_now();
          if (zframe == ~0u && ps3_ms_now() - zt0 >= (unsigned long long)zsec * 1000ull) zframe = g.frames + 1u;
          if (zframe != ~0u && g.frames > zframe) { zdone = 1; fprintf(stderr, "[zprobe] frame %u done\\n", zframe); }
          else if (g.frames == zframe && g.zdepths[zslot].offset == zoff) {
              const eng_zdepth* z = &g.zdepths[zslot];
              float v = -2.0f;   /* -2: no copy (nothing written since the clear) */
              if (zx < z->w && zy < z->h) {
                  eng_zdepth* zw = &g.zdepths[zslot]; const int hw = zw->had_write;
                  if (!hw) { zw->had_write = 1; zw->snapshot_rgba_valid = 0; }   /* eng zprobe: read the cleared image too */
                  const u32 snap = eng_zdepth_snapshot_rgba8(zslot);
                  if (!hw) { zw->had_write = 0; zw->snapshot_rgba_valid = 0; }
                  u8 px[4] = { 0 };
                  if (snap) { g.be->readback(g.be->user, snap, zx, zy, 1, 1, px, 4);
                              v = px[3] / 256.0f + px[0] / 65536.0f + px[1] / 16777216.0f; }
              }
              if (v != zlast)
                  fprintf(stderr, "[zprobe] frame %u depth at (%u,%u) %.6f -> %.6f after fp %016llx (n %u, ztest/zwrite/zfunc/clamp 0x%X)\\n",
                          g.frames, zx, zy, zlast, v, (unsigned long long)zprev_fp, zprev_n, zprev_zs);
              zlast = v;
              zprev_fp = eng_current_fp_structural(); zprev_n = dc.n_verts;
              zprev_zs = (rs.depth_test << 24) | (rs.depth_write << 20) | (rs.depth_func & 0xFFFu) << 4 | (rsx_dsp_reg(&g.rsx, 0x1D78) & 0xFu);
          } } }
    const u32 depth_handle = (zslot != ENG_INVALID) ? g.zdepths[zslot].handle : 0;
    if (zslot != ENG_INVALID && !g.zdepths[zslot].cleared) {''',
     "eng zprobe")
