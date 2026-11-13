
# PS3RECOMP_ENG_GPU_SSAO_WB=1: with the SSAO on the GPU, still write the depth and normals copies
# back to main memory (A/B: FoB's sky/clouds wash out with the GPU SSAO and the copies unwritten,
# and are right with the light pass alone).
edit("libs/video/rsx_draw_engine.c",
     '''      return ssao || (nowb && is_n); }''',
     '''      static int keepwb = -1;
      if (keepwb < 0) { const char* e = getenv("PS3RECOMP_ENG_GPU_SSAO_WB"); keepwb = e && *e == '1'; }
      return (ssao && !keepwb) || (nowb && is_n); }''',
     "eng gpu ssao wb knob")
