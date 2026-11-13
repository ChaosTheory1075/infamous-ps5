# ib stats: where spu_indirect_branch's time goes. inFAMOUS 1's one-SPU group thread spends ~52% of
# its samples in dispatch (spu_lookup / spu_indirect_branch / spu_drain_call / depth guard) and ~29%
# in lifted game code (console profile, 2026-11-01), with the inline cache on. Per SPU thread
# (thread-local, no shared cache line): calls, cache hits, misses by cause (empty / other pc / ib_gen
# changed / reg_gen / image-ovl-task / stale slot), the slow path by reason. Every 2^21 calls on a
# thread one "[ibstat]" line. PS3_SPU_IBSTAT=0 turns the counting off.
CHN = "runtime/spu/spu_channels.c"
edit(CHN,
     '''void spu_indirect_branch(spu_context* ctx)
{
    const uint32_t pc = ctx->pc & SPU_LS_MASK;''',
     '''/* ib stats (tools/patch_ibstat.py) */
enum { IBS_CALL, IBS_HIT, IBS_M_EMPTY, IBS_M_PC, IBS_M_GEN, IBS_M_REG, IBS_M_CTX, IBS_M_STALE, IBS_NOCACHE,
       IBS_S_STOP, IBS_S_PC, IBS_S_RESOLVER, IBS_S_JOB, IBS_S_POLICY, IBS_S_TASK, IBS_S_DIAG, IBS_S_NOFN, IBS_N };
static __thread unsigned long t_ibs[IBS_N];
static int s_ibs_on = -1;
static __attribute__((noinline, cold)) void ibs_report(const spu_context* ctx)
{
    static const char* const nm[IBS_N] = { "calls", "hit", "miss-empty", "miss-pc", "miss-ibgen", "miss-reggen",
        "miss-img/ovl/task", "miss-stale", "no-cache", "slow-stop/irq", "slow-pc", "slow-resolver", "slow-job",
        "slow-policy", "slow-task", "slow-diag", "slow-nofn" };
    char b[700]; int k = snprintf(b, sizeof b, "[ibstat] spu %X img %d ovl %d:", ctx->spu_id, ctx->image_id, ctx->resident_ovl);
    for (int i = 0; i < IBS_N && k < (int)sizeof b - 40; i++)
        if (t_ibs[i]) k += snprintf(b + k, sizeof b - (size_t)k, " %s %lu", nm[i], t_ibs[i]);
    fprintf(stderr, "%s\\n", b);
    memset(t_ibs, 0, sizeof t_ibs);
}
#define IBS(x) do { if (__builtin_expect(s_ibs_on, 1)) t_ibs[x]++; } while (0)

void spu_indirect_branch(spu_context* ctx)
{
    const uint32_t pc = ctx->pc & SPU_LS_MASK;
    if (__builtin_expect(s_ibs_on < 0, 0)) { const char* e = getenv("PS3_SPU_IBSTAT"); s_ibs_on = !(e && *e == '0'); }
    if (s_ibs_on && ++t_ibs[IBS_CALL] >= (1ul << 21)) ibs_report(ctx);''',
     "ibstat: counters")
edit(CHN,
     '''        (!ctx->policy_mode && pc == SPU_JOB_RETURN_LS) || spu_ib_diag_enabled())
        goto slow;
    {''',
     '''        (!ctx->policy_mode && pc == SPU_JOB_RETURN_LS) || spu_ib_diag_enabled()) {
        if (s_ibs_on) {
            if (__atomic_load_n(&ctx->stop_request, __ATOMIC_RELAXED) || ctx->irq_saved) IBS(IBS_S_STOP);
            else if (ctx->image_id == SPU_RESOLVER_ONLY_IMAGE_ID) IBS(IBS_S_RESOLVER);
            else if (ctx->resident_ovl >= 200 && spu_job_slow_routing()) IBS(IBS_S_JOB);
            else if (ctx->policy_mode) IBS(IBS_S_POLICY);
            else if (spu_ib_diag_enabled()) IBS(IBS_S_DIAG);
            else IBS(IBS_S_PC);
        }
        goto slow;
    }
    {''',
     "ibstat: slow reasons")
edit(CHN,
     '''            if (ti && !rt && ctx->host_depth && !ctx->policy_mode)
                goto slow;                            /* may unwind to the driver */''',
     '''            if (ti && !rt && ctx->host_depth && !ctx->policy_mode) {
                IBS(IBS_S_TASK);
                goto slow;                            /* may unwind to the driver */
            }''',
     "ibstat: task")
edit(CHN,
     '''            ce = &ctx->ib_cache[(pc >> 2) & (SPU_IB_CACHE_SIZE - 1)];
            if (ce->fn && ce->pc == pc && ce->gen == ctx->ib_gen && ce->reg_gen == reg_gen &&
                ce->img == ctx->image_id && ce->ovl == ctx->resident_ovl && ce->task == ctx->resident_task) {
                const int cs = ce->slot;
                if (cs < 0 || !spu_slot_word_stale(ctx, (unsigned)cs, pc)) {
                    if (cs >= 0 && ctx->resident_code[cs].reloc) ctx->code_base = ctx->resident_code[cs].lsa;
                    fn = ce->fn;
                    goto have_fn;
                }
            }
        }''',
     '''            ce = &ctx->ib_cache[(pc >> 2) & (SPU_IB_CACHE_SIZE - 1)];
            if (ce->fn && ce->pc == pc && ce->gen == ctx->ib_gen && ce->reg_gen == reg_gen &&
                ce->img == ctx->image_id && ce->ovl == ctx->resident_ovl && ce->task == ctx->resident_task) {
                const int cs = ce->slot;
                if (cs < 0 || !spu_slot_word_stale(ctx, (unsigned)cs, pc)) {
                    if (cs >= 0 && ctx->resident_code[cs].reloc) ctx->code_base = ctx->resident_code[cs].lsa;
                    fn = ce->fn;
                    IBS(IBS_HIT);
                    goto have_fn;
                }
                IBS(IBS_M_STALE);
            } else if (s_ibs_on) {
                IBS(!ce->fn ? IBS_M_EMPTY : ce->pc != pc ? IBS_M_PC : ce->gen != ctx->ib_gen ? IBS_M_GEN
                    : ce->reg_gen != reg_gen ? IBS_M_REG : IBS_M_CTX);
            }
        } else IBS(IBS_NOCACHE);''',
     "ibstat: cache")
edit(CHN,
     '''        if (!fn) goto slow;
        /* A stale slot that covered pc makes the answer depend on LS words''',
     '''        if (!fn) { IBS(IBS_S_NOFN); goto slow; }
        /* A stale slot that covered pc makes the answer depend on LS words''',
     "ibstat: nofn")
