# spu unlifted lsdump: SPU_UNLIFTED_LSDUMP=<dir> -- DIAGNOSTIC: the first time each 16 KB LS page is branched into
# unlifted, the whole 256 KB local store to <dir>/ls_img<id>_ovl<ovl>_pc<pc>.bin, so code a job loads at run time
# can be found in guest memory/game files and lifted (inFAMOUS 1 rooftop: LS 0x31000-0x35000, 84% of interpreted steps).
edit("runtime/spu/spu_channels.c",
     '''            const char* e_iu = getenv("SPU_INTERP_UNLIFTED");
            int interp = !(e_iu && e_iu[0] == '0') && w0;''',
     '''            const char* e_iu = getenv("SPU_INTERP_UNLIFTED");
            int interp = !(e_iu && e_iu[0] == '0') && w0;
            { static const char* ud = (const char*)-1; static uint32_t pages;   /* spu unlifted lsdump */
              if (ud == (const char*)-1) ud = getenv("SPU_UNLIFTED_LSDUMP");
              const uint32_t bit = 1u << ((p0 >> 14) & 15);
              if (ud && !(__atomic_fetch_or(&pages, bit, __ATOMIC_ACQ_REL) & bit)) {
                  char path[512]; snprintf(path, sizeof path, "%s/ls_img%d_ovl%d_pc%05X.bin", ud, ctx->image_id, ctx->resident_ovl, p0);
                  FILE* f = fopen(path, "wb"); if (f) { fwrite(ctx->ls, 1, SPU_LS_SIZE, f); fclose(f); } } }''',
     "spu unlifted lsdump")
