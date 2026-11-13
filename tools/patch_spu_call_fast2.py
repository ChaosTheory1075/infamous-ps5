
# spu call fast 2: a callee that returns through a jump (bi on a non-link register, a jump table) leaves
# tramp_fn = spu_indirect_branch with pc already at the return pc; spu_drain_call_slow's first check
# clears it and returns, nothing else. Do that inline too. (route1 r3b: drain_call_slow still 0.11 cores
# with spu call fast on.) Same switch: PS3_SPU_CALL_FAST=0 = old.
edit("runtime/spu/spu_context.h",
     '''    if (__builtin_expect(g_spu_call_fast > 0 && !ctx->tramp_fn &&
                         ((ctx->pc ^ return_pc) & SPU_LS_MASK) == 0 &&
                         ctx->host_depth < g_spu_depth_max, 1)) {
        ctx->drain_ret_pc = 0;
        return;
    }''',
     '''    if (__builtin_expect(g_spu_call_fast > 0 &&
                         (!ctx->tramp_fn || ctx->tramp_fn == spu_indirect_branch) &&
                         ((ctx->pc ^ return_pc) & SPU_LS_MASK) == 0 &&
                         ctx->host_depth < g_spu_depth_max, 1)) {
        ctx->tramp_fn = 0;   /* spu call fast 2: a jump back to the return pc */
        ctx->drain_ret_pc = 0;
        return;
    }''',
     "spu call fast 2: jump return")
