# spu contention A/B switch: -DSPU_NO_CONTENTION_FIX (or #define at the file top) restores the old
# hot-path atomics of patch_spu_contention.py (putllc counter, coh_mark_line RMW, memkick add/xchg),
# so the fix can be measured against the same build.
edit(CHN,
     '''#ifdef SPU_PUTLLC_COUNT   /* spu contention: a shared counter nothing reads */''',
     '''#if defined(SPU_PUTLLC_COUNT) || defined(SPU_NO_CONTENTION_FIX)   /* spu contention: a shared counter nothing reads */''',
     "spu contention ab: putllc")
edit(COH,
     '''    if ((__atomic_load_n(&s_coh_bitmap[line >> 3], __ATOMIC_ACQUIRE) & bit) &&
        __atomic_load_n(&s_coh_armed, __ATOMIC_ACQUIRE)) {
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        return;
    }''',
     '''#ifndef SPU_NO_CONTENTION_FIX
    if ((__atomic_load_n(&s_coh_bitmap[line >> 3], __ATOMIC_ACQUIRE) & bit) &&
        __atomic_load_n(&s_coh_armed, __ATOMIC_ACQUIRE)) {
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        return;
    }
#endif''',
     "spu contention ab: coh_mark_line")
edit(COH,
     '''    if (__atomic_load_n(&s_mk_spinners, __ATOMIC_ACQUIRE)) __atomic_add_fetch(&s_mk_gen, 1, __ATOMIC_RELEASE);
    if (__atomic_load_n(&s_mk_pending, __ATOMIC_ACQUIRE)) return;   /* a wake-up is already on its way */''',
     '''#ifndef SPU_NO_CONTENTION_FIX
    if (__atomic_load_n(&s_mk_spinners, __ATOMIC_ACQUIRE)) __atomic_add_fetch(&s_mk_gen, 1, __ATOMIC_RELEASE);
    if (__atomic_load_n(&s_mk_pending, __ATOMIC_ACQUIRE)) return;   /* a wake-up is already on its way */
#else
    __atomic_add_fetch(&s_mk_gen, 1, __ATOMIC_RELEASE);
#endif''',
     "spu contention ab: memkick")
