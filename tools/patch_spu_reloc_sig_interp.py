# spu reloc sig interp: the interpreter adopts as well, at every taken branch (pc != previous + 4). Job 209 calls the
# modules from its own unlifted code too (its LS 0xE000 page runs interpreted), and the interpreter follows those
# calls by itself: neither dispatch hook ever saw them, so modules 331/334 at LS 0x30F30.. stayed interpreted.
edit("runtime/spu/spu_interp.c",
     '''    uint32_t ring[64]; int rc=0, rn=0;
    for (;;) {''',
     '''    uint32_t ring[64]; int rc=0, rn=0;
    uint32_t _ra_prev = ~0u;   /* spu reloc sig interp */
    for (;;) {
        if (ctx->pc != _ra_prev + 4u && ctx->image_id >= 0) {
            extern int spu_reloc_sig_adopt(spu_context*, uint32_t);
            (void)spu_reloc_sig_adopt(ctx, ctx->pc);
        }
        _ra_prev = ctx->pc;''',
     "spu reloc sig interp")
