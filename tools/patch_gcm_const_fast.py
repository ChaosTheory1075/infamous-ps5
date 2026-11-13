
# gcm const fast: a vertex-constant burst (one incrementing packet: SET_TRANSFORM_CONSTANT_LOAD 0x1EFC
# + up to 32 words into the 0x1F00 window) is stored in one call instead of word by word through
# the whole FIFO walker body (debug checks, rsx_draw_engine_method, rsx_dispatch_method's range,
# empty-draw, seen/regs, upload-window tests). Crater, RSX_METHOD_HIST (run mh1): ~408k FIFO words a
# frame, about half of them in that window (0x1EFC and 0x1F00..0x1F0C ~3.1M each per 10 s); the
# walker was ~24% of the RSX thread (perf pf1). The 0x1EFC word still takes the normal path; the
# window words do exactly what rsx_dispatch_method does for them (seen++, regs, constants[slot]).
# Taken only for subchannel 0, a burst inside 0x1EFC..0x1F7C, one contiguous IO mapping, the draw
# engine on and every per-word diagnostic / legacy / live-draw path off. PS3_GCM_CONST_FAST=0 = old.
edit("libs/video/rsx_dispatch.h",
     '''void rsx_dispatch_method(rsx_dispatch* rsx, u32 method, u32 arg);''',
     '''void rsx_dispatch_method(rsx_dispatch* rsx, u32 method, u32 arg);
/* gcm const fast: n words into the transform-constant window from `method` on, as n
 * rsx_dispatch_method calls would store them (method + 4n <= M_VP_UPLOAD_CONST + 128). */
void rsx_dispatch_const_words(rsx_dispatch* rsx, u32 method, const u32* words, u32 n);''',
     "gcm const fast decl")
edit("libs/video/rsx_dispatch.c",
     '''void rsx_dispatch_method(rsx_dispatch* rsx, u32 method, u32 arg)
{''',
     '''void rsx_dispatch_const_words(rsx_dispatch* rsx, u32 method, const u32* words, u32 n)
{   /* gcm const fast: the transform-constant window branch of rsx_dispatch_method, n times */
    const u32 base = rsx->regs[M_VP_UPLOAD_CONST_ID >> 2];
    for (u32 i = 0; i < n; i++) {
        const u32 m = method + i * 4u, idx = m >> 2;
        rsx->seen[idx]++;
        rsx->regs[idx] = words[i];
        const u32 word = (m - M_VP_UPLOAD_CONST) >> 2;
        const u32 slot = base + (word >> 2);
        if (slot < RSX_DSP_NUM_CONSTANTS)
            rsx->constants[slot][word & 3] = words[i];
    }
}

void rsx_dispatch_method(rsx_dispatch* rsx, u32 method, u32 arg)
{''',
     "gcm const fast dispatch")
edit("libs/video/rsx_draw_engine.h",
     '''void rsx_draw_engine_method(u32 method, u32 arg);''',
     '''void rsx_draw_engine_method(u32 method, u32 arg);
/* gcm const fast: a transform-constant window burst (subchannel 0, 0x1F00..0x1F7C) */
void rsx_draw_engine_const_words(u32 method, const u32* words, u32 n);''',
     "gcm const fast engine decl")
edit("libs/video/rsx_draw_engine.c",
     '''void rsx_draw_engine_method(u32 method, u32 arg)
{''',
     '''void rsx_draw_engine_const_words(u32 method, const u32* words, u32 n)
{   /* gcm const fast */
    if (!g.ready) return;
    rsx_dispatch_const_words(&g.rsx, method, words, n);
}

void rsx_draw_engine_method(u32 method, u32 arg)
{''',
     "gcm const fast engine")
edit("libs/video/cellGcmSys.c",
     '''            const int fifo_dbg = gcm_fifo_dbg();
            for (u32 i = 0; i < count; i++) {''',
     '''            const int fifo_dbg = gcm_fifo_dbg();
            /* gcm const fast: a whole vertex-constant burst in one store */
            { static int cf = -1;
              if (cf < 0) {
                  const char* e = getenv("PS3_GCM_CONST_FAST");
                  const char* lg = getenv("GCM_CONST_LEGACY");
                  cf = !(e && *e == '0') && rsx_draw_engine_enabled() && !rsx_live_draw_enabled() &&
                       !(lg && *lg == '1') && !getenv("RSX_METHOD_HIST") && !getenv("TCONST_FIFO") &&
                       !getenv("RSX_CONST_LOG") && !getenv("RSX_EMPTY_DRAW_LOG");
                  if (cf) fprintf(stderr, "[cellGcmSys] vertex-constant bursts: one store per packet (PS3_GCM_CONST_FAST=0 = per word)\\n");
              }
              if (cf && type == 0 && subch == 0 && !fifo_dbg && count >= 2 && count <= 33 &&
                  method >= 0x1EFCu && method + count * 4u <= 0x1F80u) {
                  const u32 ea0 = gcm_io2ea(s_fifo_getoff + 4);
                  const u32 ean = gcm_io2ea(s_fifo_getoff + 4 + (count - 1) * 4);
                  if (ea0 && ean == ea0 + (count - 1) * 4) {
                      u32 i0 = 0;
                      if (method == 0x1EFCu) {   /* SET_TRANSFORM_CONSTANT_LOAD: the normal path */
                          const u32 dw = vm_read32(ea0);
                          rsx_draw_engine_method(method, dw);
                          rsx_process_method(&s_state, method, dw);
                          i0 = 1;
                      }
                      u32 buf[33];
                      for (u32 i = i0; i < count; i++) buf[i - i0] = vm_read32(ea0 + i * 4);
                      rsx_draw_engine_const_words(method + i0 * 4, buf, count - i0);
                      s_fifo_getoff += 4 + count * 4;
                      continue;
                  }
              } }
            for (u32 i = 0; i < count; i++) {''',
     "gcm const fast walker")
