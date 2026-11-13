
# A blocked SPU channel read re-checks its predicate every PS3_SPU_CHWAIT_MS (default 1, was a fixed
# 10): the lost-reservation event is polled (spu_resv_lost_poll: "the ceiling is one poll of wake
# latency"), so a writer the store hooks miss cost up to 10 ms per SPURS handoff. One 128-byte
# compare per millisecond per blocked SPU.
edit("runtime/spu/spu_channels.c",
     '''                SleepConditionVariableSRW((CONDITION_VARIABLE*)&ctx->ch_wait_cv,
                                          (SRWLOCK*)&ctx->ch_wait_lock, 10, 0);''',
     '''                SleepConditionVariableSRW((CONDITION_VARIABLE*)&ctx->ch_wait_cv,
                                          (SRWLOCK*)&ctx->ch_wait_lock, spu_chwait_ms(), 0);''',
     "spu chwait: poll")
edit("runtime/spu/spu_channels.c",
     '''/* Block the calling SPU host thread until `channel` is readable. */
static void spu_ch_wait(''',
     '''static unsigned spu_chwait_ms(void)
{
    static _Atomic int ms = -1;
    if (ms < 0) { const char* e = getenv("PS3_SPU_CHWAIT_MS"); ms = e && atoi(e) > 0 ? atoi(e) : 1; }
    return (unsigned)ms;
}

/* Block the calling SPU host thread until `channel` is readable. */
static void spu_ch_wait(''',
     "spu chwait: knob")
