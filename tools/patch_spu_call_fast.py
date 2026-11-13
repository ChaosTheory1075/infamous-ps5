
# spu call fast: a lifted brsl/bisl call bracket ends in spu_drain_call(ctx, ret) + spu_img_restore -- two
# out-of-line calls (+ spu_depth_guard inside) after EVERY SPU function call, ~0.35 cores in the if1 crater
# (c1on: drain 0.20, depth guard 0.07, ...). When the callee simply returned (no pending transfer, pc == the
# return pc) the drain loop does nothing but clear drain_ret_pc, so do that inline. The depth limit is still
# honoured (over it -> the slow path, which halts as before); the depth ring just does not record these
# plain returns. spu_img_restore becomes inline (same body). default off since 2026-11-04 (PS3_SPU_CALL_FAST=1 = on; every return
# through spu_drain_call).
edit("runtime/spu/spu_context.h",
     '''/* Drain a translated call up to its explicit architectural return PC. */
void spu_drain_call(spu_context* ctx, uint32_t return_pc);''',
     '''/* Drain a translated call up to its explicit architectural return PC. */
void spu_drain_call_slow(spu_context* ctx, uint32_t return_pc);
/* spu call fast (PS3_SPU_CALL_FAST, default on): 0 until spu_drain_call_slow's first run reads it. */
extern int g_spu_call_fast;
extern uint32_t g_spu_depth_max;
static inline __attribute__((always_inline)) void spu_drain_call(spu_context* ctx, uint32_t return_pc)
{
    /* the callee returned to us: nothing for the drain loop to run */
    if (__builtin_expect(g_spu_call_fast > 0 && !ctx->tramp_fn &&
                         ((ctx->pc ^ return_pc) & SPU_LS_MASK) == 0 &&
                         ctx->host_depth < g_spu_depth_max, 1)) {
        ctx->drain_ret_pc = 0;
        return;
    }
    spu_drain_call_slow(ctx, return_pc);
}''',
     "spu call fast: inline drain")
edit("runtime/spu/spu_context.h",
     '''void spu_img_restore(spu_context* ctx, int32_t saved_img);
/* Wake a host thread''',
     '''static inline __attribute__((always_inline)) void spu_img_restore(spu_context* ctx, int32_t saved_img)
{
    ctx->image_id = ctx->module_img_a00 ? ctx->module_img_a00 : saved_img;   /* spu call fast: inline */
}
/* Wake a host thread''',
     "spu call fast: inline img restore")
edit("runtime/spu/spu_drain.c",
     '''void spu_img_restore(spu_context* ctx, int32_t saved_img)
{
    ctx->image_id = ctx->module_img_a00 ? ctx->module_img_a00 : saved_img;
}''',
     '''/* (spu_img_restore: inline in spu_context.h, spu call fast) */''',
     "spu call fast: img restore moved")
edit("runtime/spu/spu_drain.c",
     '''void spu_drain_call(spu_context* ctx, uint32_t return_pc)
{
    if (__builtin_expect(g_spu_direct < 0, 0)) spu_direct_init();''',
     '''int g_spu_call_fast = 0;            /* spu call fast */
uint32_t g_spu_depth_max = 2000u;
void spu_drain_call_slow(spu_context* ctx, uint32_t return_pc)
{
    if (__builtin_expect(g_spu_direct < 0, 0)) spu_direct_init();
    { static int s_cf = -1;         /* spu call fast: read once, the same limit spu_depth_guard uses */
      if (s_cf < 0) {
          const char* e = getenv("SPU_HOST_DEPTH_MAX");
          g_spu_depth_max = e ? (uint32_t)strtoul(e, 0, 0) : 2000u;
          const char* c = getenv("PS3_SPU_CALL_FAST");
          s_cf = c && c[0] == '1';   /* default off: no measurable gain on route1 (2026-11-04) */
          __atomic_store_n(&g_spu_call_fast, s_cf, __ATOMIC_RELAXED);
      } }''',
     "spu call fast: slow drain")
