
# PS3RECOMP_ENG_BLIT_LOG=1, second form: each distinct write-back (source, destination) once (up to
# 96), so the per-frame world blits show up after the menus' repeats.
edit("libs/video/rsx_draw_engine.c",
     '''      if (lg && n++ < 48)
          fprintf(''',
     '''      static u32 seen[96][2]; static unsigned ns;
      int fresh = 0;
      if (lg) {
          static pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;
          pthread_mutex_lock(&m);
          unsigned k = 0;
          while (k < ns && !(seen[k][0] == offset && seen[k][1] == dst_offset)) k++;
          if (k == ns && ns < 96) { seen[ns][0] = offset; seen[ns][1] = dst_offset; ns++; fresh = 1; }
          pthread_mutex_unlock(&m);
      }
      if (fresh && ++n)
          fprintf(''',
     "eng blit log: distinct")
