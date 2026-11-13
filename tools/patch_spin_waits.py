# spin waits: SPU channel waits and the PPU's usleep-kick waits spin briefly before sleeping in the OS
# The console's waits are the frame limiter: the main PPU thread waited ~8,500-14,600 times a second
# (ps3_memkick_wait) and each SPU thread ~1,000 times a second (spu_ch_wait), with the CPU mostly
# idle (2-3 cores busy of 13; RPCS3 on the PS5 keeps ~7 busy at 30-40 fps on inFAMOUS). Every one
# of those was a condition-variable sleep and an OS wake-up. Now each first spins (pause loop) for
# up to PS3_SPU_SPIN_US / PS3_MK_SPIN_US microseconds (40 / 40; 0 = off), checking the same thing
# it would be woken for, and sleeps only when that does not happen in time. Both are also read from
# the toggle file (PS3_TOGGLE_FILE) every few thousand waits, so a running game can be A/B tested.
SPC = "runtime/spu/spu_channels.c"
edit(SPC,
     '''/* Block the calling SPU host thread until `channel` is readable. */
static void spu_ch_wait(spu_context* ctx, uint32_t channel, const char* op)
{
    if (!yz_ch_block() || spu_ch_ready(ctx, channel)) return;''',
     '''/* The spin before a channel sleep (PS3_SPU_SPIN_US, default 40; also live from the toggle file). */
static int spu_spin_us(void)
{
    static _Atomic unsigned n;
    static _Atomic int us = -1;
    if ((__atomic_fetch_add(&n, 1, __ATOMIC_RELAXED) & 4095u) == 0 || us < 0) {
        const char* e = getenv("PS3_SPU_SPIN_US");
        us = ps3_toggle_get("PS3_SPU_SPIN_US", e ? atoi(e) : 40);
    }
    return us;
}
static _Atomic unsigned long s_spin_hit, s_spin_miss;

/* Block the calling SPU host thread until `channel` is readable. */
static void spu_ch_wait(spu_context* ctx, uint32_t channel, const char* op)
{
    if (!yz_ch_block() || spu_ch_ready(ctx, channel)) return;
#if defined(__x86_64__)
    {   const int us = spu_spin_us();
        if (us > 0) {
            const uint64_t t0 = ps3_ft_now(), lim = (uint64_t)us * 1000ull;
            for (unsigned k = 1;; k++) {
                for (int i = 0; i < 8; i++) __builtin_ia32_pause();
                if (spu_ch_ready(ctx, channel)) {
                    __atomic_add_fetch(&s_spin_hit, 1, __ATOMIC_RELAXED);
                    return;
                }
                if (__atomic_load_n(&ctx->stop_request, __ATOMIC_RELAXED)) break;
                if (!(k & 7u) && ps3_ft_now() - t0 > lim) break;
            }
            const unsigned long m = __atomic_add_fetch(&s_spin_miss, 1, __ATOMIC_RELAXED);
            if ((m & 65535u) == 0)
                fprintf(stderr, "[spin] spu channel waits: %lu answered while spinning, %lu slept (spin %d us)\\n",
                        (unsigned long)s_spin_hit, m, us);
        }
    }
#endif''',
     "spin waits: spu")

SCO = "runtime/spu/spu_coherency.c"
edit(SCO,
     '''void ps3_memkick_slow(void)
{
    if (__atomic_exchange_n(&s_mk_pending, 1, __ATOMIC_ACQ_REL)) return;''',
     '''static unsigned s_mk_gen;   /* every kick: a spinning waiter watches it change */
void ps3_memkick_slow(void)
{
    __atomic_add_fetch(&s_mk_gen, 1, __ATOMIC_RELEASE);
    if (__atomic_exchange_n(&s_mk_pending, 1, __ATOMIC_ACQ_REL)) return;''',
     "spin waits: kick gen")
edit(SCO,
     '''void ps3_memkick_wait(uint64_t us)
{
    struct timespec ts;''',
     '''/* The spin before a usleep-kick sleep (PS3_MK_SPIN_US, default 40; also live from the toggle file). */
#include "ps3emu/ps3_toggles.h"
static int mk_spin_us(void)
{
    static unsigned n;
    static int v = -1;
    if ((__atomic_fetch_add(&n, 1, __ATOMIC_RELAXED) & 4095u) == 0 || v < 0) {
        const char* e = getenv("PS3_MK_SPIN_US");
        v = ps3_toggle_get("PS3_MK_SPIN_US", e ? atoi(e) : 40);
    }
    return v;
}
static unsigned long s_mk_spin_hit, s_mk_spin_miss;
static uint64_t mk_now_ns(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec;
}

void ps3_memkick_wait(uint64_t us)
{
#if defined(__x86_64__)
    {   const int sp = mk_spin_us();
        if (sp > 0) {
            /* A waiter makes every SPU write call ps3_memkick_slow, which bumps the generation. */
            __atomic_add_fetch(&g_mk_waiters, 1, __ATOMIC_SEQ_CST);
            const unsigned g0 = __atomic_load_n(&s_mk_gen, __ATOMIC_ACQUIRE);
            const uint64_t t0 = mk_now_ns(), lim = (uint64_t)(sp < (int)us ? sp : (int)us) * 1000ull;
            int hit = 0;
            for (unsigned k = 1;; k++) {
                for (int i = 0; i < 8; i++) __builtin_ia32_pause();
                if (__atomic_load_n(&s_mk_gen, __ATOMIC_ACQUIRE) != g0) { hit = 1; break; }
                if (!(k & 7u) && mk_now_ns() - t0 > lim) break;
            }
            __atomic_sub_fetch(&g_mk_waiters, 1, __ATOMIC_SEQ_CST);
            if (hit) {
                __atomic_add_fetch(&g_mk_woken, 1, __ATOMIC_RELAXED);
                __atomic_add_fetch(&s_mk_spin_hit, 1, __ATOMIC_RELAXED);
                return;
            }
            const unsigned long m = __atomic_add_fetch(&s_mk_spin_miss, 1, __ATOMIC_RELAXED);
            if ((m & 65535u) == 0)
                fprintf(stderr, "[spin] usleep-kick waits: %lu answered while spinning, %lu slept (spin %d us)\\n",
                        s_mk_spin_hit, m, sp);
        }
    }
#endif
    struct timespec ts;''',
     "spin waits: memkick")
