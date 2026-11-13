
# PS3RECOMP_ENG_BLIT_LOG=1: log the first 48 RSX write-backs (blits of a render target to another
# surface), source and destination. How a game's light-job input buffers are found (the offsets
# PS3RECOMP_ENG_GPU_LIGHT takes): they are the two per-frame blits into main memory.
edit("libs/video/rsx_draw_engine.c",
     '''    if (!g.ready || !g.be->readback || !g.be->submit_and_wait) return 0;
    if (eng_gpu_light_blit(local ? RSX_LOCATION_LOCAL : RSX_LOCATION_MAIN, offset, pitch,''',
     '''    if (!g.ready || !g.be->readback || !g.be->submit_and_wait) return 0;
    { static int lg = -1; static _Atomic unsigned n;
      if (lg < 0) lg = getenv("PS3RECOMP_ENG_BLIT_LOG") ? 1 : 0;
      if (lg && n++ < 48)
          fprintf(stderr, "[blit log] %s 0x%08X pitch %u -> %s 0x%08X\\n", local ? "local" : "main",
                  offset, pitch, dst_local < 0 ? "self" : dst_local ? "local" : "main", dst_offset); }
    if (eng_gpu_light_blit(local ? RSX_LOCATION_LOCAL : RSX_LOCATION_MAIN, offset, pitch,''',
     "eng blit log")
