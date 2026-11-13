# rsx method histogram: RSX_METHOD_HIST=1 prints, every 10 s, how many FIFO method words of each
# kind the RSX thread processed (top 12 by count, NV4097 methods with the subchannel stripped) --
# what the per-word decode cost (rsx_process_method's compare chain + the draw engine's dispatch,
# ~30% of inFAMOUS 1's RSX thread at 13,500 draws per frame) is spent on.
GCM = "libs/video/cellGcmSys.c"
edit(GCM,
     '''                } else if (subch == 0 || (subch == 1 && !s1_2d)) {
                    rsx_process_method(&s_state, m, dw);''',
     '''                } else if (subch == 0 || (subch == 1 && !s1_2d)) {
                    { static int mh = -1;   /* rsx method histogram (tools/patch_rsx_mhist.py) */
                      if (mh < 0) mh = getenv("RSX_METHOD_HIST") ? 1 : 0;
                      if (mh) { static unsigned long long cnt[0x800], t0, tot; struct timespec ts;
                          cnt[(m & 0x1FFCu) >> 2]++; tot++;
                          if ((tot & 0xFFFF) == 0) { clock_gettime(CLOCK_MONOTONIC, &ts);
                              const unsigned long long now = (unsigned long long)ts.tv_sec;
                              if (!t0) t0 = now;
                              if (now - t0 >= 10) { t0 = now;
                                  fprintf(stderr, "[mhist] %llu words:", tot);
                                  for (int k = 0; k < 12; k++) { unsigned best = 0;
                                      for (unsigned j = 1; j < 0x800; j++) if (cnt[j] > cnt[best]) best = j;
                                      if (!cnt[best]) break;
                                      fprintf(stderr, " %04X=%llu", best << 2, cnt[best]); cnt[best] = 0; }
                                  fputc('\\n', stderr); memset(cnt, 0, sizeof cnt); tot = 0; } } } }
                    rsx_process_method(&s_state, m, dw);''',
     "rsx method histogram")
