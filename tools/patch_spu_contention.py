# spu contention: no atomic writes to shared hot globals on every SPU reservation / DMA PUT
# PC FoB profile (perf_fast2): the hottest instructions of spu_wrch and coh_mark_line were the
# writes to process-wide globals that every SPU thread (and every PPU store) touches -- each one
# moves that cache line to the writing core, and on the console the six SPU threads and the main
# PPU thread sit on two core complexes:
#  - spu_wrch PUTLLC: `lock incl g_spu_putllc_count` on every PUTLLC, a counter nothing reads;
#    now only with -DSPU_PUTLLC_COUNT.
#  - coh_mark_line (every GETLLAR): an atomic OR into the reserved-line bitmap and a SEQ_CST store
#    (xchg) to s_coh_armed -- both are read inline by EVERY PPU store, so every reservation also
#    evicted those lines from the PPU core. The bit is never cleared and s_coh_armed is never reset:
#    when both are already set, only the full fence the RMW gave is kept.
#  - ps3_memkick_slow (every SPU write to main memory while a guest thread sleeps in a short
#    usleep -- the main thread, most of the frame): an atomic add to s_mk_gen and an atomic exchange
#    of s_mk_pending even when a wake-up was already pending. Now: a plain load first; the
#    generation is bumped only while someone spins on it (PS3_MK_SPIN_US > 0).
CHN = "runtime/spu/spu_channels.c"
edit(CHN,
     '''        __atomic_fetch_add(&g_spu_putllc_count, 1u, __ATOMIC_RELAXED);   /* read by the PM flow trace */''',
     '''#ifdef SPU_PUTLLC_COUNT   /* spu contention: a shared counter nothing reads */
        __atomic_fetch_add(&g_spu_putllc_count, 1u, __ATOMIC_RELAXED);   /* read by the PM flow trace */
#endif''',
     "spu contention: putllc counter")
COH = "runtime/spu/spu_coherency.c"
edit(COH,
     '''    const unsigned char bit = (unsigned char)(1u << (line & 7));
    const unsigned char was = __atomic_fetch_or(&s_coh_bitmap[line >> 3], bit, __ATOMIC_SEQ_CST);
    __atomic_store_n(&s_coh_armed, 1, __ATOMIC_SEQ_CST);
    if (!(was & bit)) spu_process_barrier();''',
     '''    const unsigned char bit = (unsigned char)(1u << (line & 7));
    /* Already marked and armed (neither is ever cleared): read-only, so the line stays shared
     * with the PPU cores that read both on every store; keep the RMW's full fence. */
    if ((__atomic_load_n(&s_coh_bitmap[line >> 3], __ATOMIC_ACQUIRE) & bit) &&
        __atomic_load_n(&s_coh_armed, __ATOMIC_ACQUIRE)) {
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        return;
    }
    const unsigned char was = __atomic_fetch_or(&s_coh_bitmap[line >> 3], bit, __ATOMIC_SEQ_CST);
    __atomic_store_n(&s_coh_armed, 1, __ATOMIC_SEQ_CST);
    if (!(was & bit)) spu_process_barrier();''',
     "spu contention: coh_mark_line")
edit(COH,
     '''static unsigned s_mk_gen;   /* every kick: a spinning waiter watches it change */
void ps3_memkick_slow(void)
{
    __atomic_add_fetch(&s_mk_gen, 1, __ATOMIC_RELEASE);
    if (__atomic_exchange_n(&s_mk_pending, 1, __ATOMIC_ACQ_REL)) return;''',
     '''static unsigned s_mk_gen;   /* every kick: a spinning waiter watches it change */
static int s_mk_spinners;   /* waiters spinning on s_mk_gen (PS3_MK_SPIN_US > 0) */
void ps3_memkick_slow(void)
{
    if (__atomic_load_n(&s_mk_spinners, __ATOMIC_ACQUIRE)) __atomic_add_fetch(&s_mk_gen, 1, __ATOMIC_RELEASE);
    if (__atomic_load_n(&s_mk_pending, __ATOMIC_ACQUIRE)) return;   /* a wake-up is already on its way */
    if (__atomic_exchange_n(&s_mk_pending, 1, __ATOMIC_ACQ_REL)) return;''',
     "spu contention: memkick")
edit(COH,
     '''            __atomic_add_fetch(&g_mk_waiters, 1, __ATOMIC_SEQ_CST);
            const unsigned g0 = __atomic_load_n(&s_mk_gen, __ATOMIC_ACQUIRE);''',
     '''            __atomic_add_fetch(&s_mk_spinners, 1, __ATOMIC_SEQ_CST);
            __atomic_add_fetch(&g_mk_waiters, 1, __ATOMIC_SEQ_CST);
            const unsigned g0 = __atomic_load_n(&s_mk_gen, __ATOMIC_ACQUIRE);''',
     "spu contention: memkick spinners in")
edit(COH,
     '''            __atomic_sub_fetch(&g_mk_waiters, 1, __ATOMIC_SEQ_CST);
            if (hit) {''',
     '''            __atomic_sub_fetch(&g_mk_waiters, 1, __ATOMIC_SEQ_CST);
            __atomic_sub_fetch(&s_mk_spinners, 1, __ATOMIC_SEQ_CST);
            if (hit) {''',
     "spu contention: memkick spinners out")
