# spu interp lsdump: SPU_INTERP_LSDUMP=<dir>:<lo hex>:<hi hex> -- DIAGNOSTIC: the first 4 times the interpreter steps
# at a pc in [lo, hi) (one every 2^24 such steps), the whole local store to <dir>/interp_<n>_pc<pc>_img<id>_ovl<ovl>.bin,
# to identify the code a job runs there that nothing lifted (inFAMOUS 1 rooftop: LS 0x31000-0x34FFF).
edit("runtime/spu/spu_interp.c",
     '''        /* SPU_INTERP_WHERE=<n>: every n interpreted steps (all SPUs), print the''',
     '''        { static const char* d = (const char*)-1; static uint32_t lo, hi; static _Atomic unsigned long long cnt; static _Atomic int nd;   /* spu interp lsdump */
          if (d == (const char*)-1) { const char* e = getenv("SPU_INTERP_LSDUMP"); d = 0;
              if (e) { static char dir[400]; const char* c = strchr(e, ':');
                  if (c && (size_t)(c - e) < sizeof dir) { memcpy(dir, e, (size_t)(c - e)); dir[c - e] = 0; d = dir;
                      lo = (uint32_t)strtoul(c + 1, (char**)&c, 16); hi = (*c == ':') ? (uint32_t)strtoul(c + 1, 0, 16) : lo + 0x1000; } } }
          if (d && _tpc >= lo && _tpc < hi && nd < 4 && (cnt++ & ((1ull << 24) - 1)) == 0) {
              int k = nd++; char path[512];
              snprintf(path, sizeof path, "%s/interp_%d_pc%05X_img%d_ovl%d.bin", d, k, _tpc, ctx->image_id, ctx->resident_ovl);
              FILE* f = fopen(path, "wb"); if (f) { fwrite(ctx->ls, 1, SPU_LS_SIZE, f); fclose(f); } } }
        /* SPU_INTERP_WHERE=<n>: every n interpreted steps (all SPUs), print the''',
     "spu interp lsdump")
