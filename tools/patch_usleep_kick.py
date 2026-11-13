
# usleep kick: a short guest sys_timer_usleep waits for an SPU write to main memory instead of the host timer
# inFAMOUS 2's SPU light-task kicker and main thread poll SPU task results with usleep(3)/usleep(10).
# The host's shortest sleep is ~1 ms on Linux in practice for that loop and ~0.6 ms on the PS5, so ~300
# task handoffs a frame each waited that long. A sleep of PS3_USLEEP_KICK_US (default 50) or less now
# waits on a condition every SPU PUT / PUTLLC / PUTLLUC signals, capped at PS3_USLEEP_KICK_CAP_US
# (default 100): the poll sees the SPU's result at once, and nothing spins.
edit("runtime/spu/spu_coherency.c",
     '''#include "spu_coherency.h"''',
     '''#include "spu_coherency.h"

#include <pthread.h>
#include <time.h>

/* usleep kick: see sys_timer_usleep. g_mk_waiters is read lock-free by every SPU write to main
 * memory; only with a guest thread parked does a write take the mutex, and s_mk_pending makes
 * that at most one broadcast per round of sleepers. */
static pthread_mutex_t s_mk_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t  s_mk_cv = PTHREAD_COND_INITIALIZER;
int g_mk_waiters;
static int s_mk_pending;
unsigned long g_mk_kicks, g_mk_woken, g_mk_timeouts;

void ps3_memkick_slow(void)
{
    if (__atomic_exchange_n(&s_mk_pending, 1, __ATOMIC_ACQ_REL)) return;
    __atomic_add_fetch(&g_mk_kicks, 1, __ATOMIC_RELAXED);
    pthread_mutex_lock(&s_mk_mu);
    pthread_cond_broadcast(&s_mk_cv);
    pthread_mutex_unlock(&s_mk_mu);
}

void ps3_memkick_wait(uint64_t us)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    const uint64_t ns = (uint64_t)ts.tv_nsec + us * 1000ull;
    ts.tv_sec += (time_t)(ns / 1000000000ull);
    ts.tv_nsec = (long)(ns % 1000000000ull);
    pthread_mutex_lock(&s_mk_mu);
    __atomic_add_fetch(&g_mk_waiters, 1, __ATOMIC_SEQ_CST);
    __atomic_store_n(&s_mk_pending, 0, __ATOMIC_RELEASE);
    const int r = pthread_cond_timedwait(&s_mk_cv, &s_mk_mu, &ts);
    __atomic_sub_fetch(&g_mk_waiters, 1, __ATOMIC_SEQ_CST);
    pthread_mutex_unlock(&s_mk_mu);
    __atomic_add_fetch(r ? &g_mk_timeouts : &g_mk_woken, 1, __ATOMIC_RELAXED);
}''',
     "usleep kick core")
edit("runtime/spu/spu_coherency.h",
     '''extern unsigned long g_spu_lr_raise;''',
     '''extern unsigned long g_spu_lr_raise;

/* usleep kick (spu_coherency.c): an SPU write to main memory wakes guest threads parked in a
 * short sys_timer_usleep. ps3_memkick is the cheap check every writer makes. */
extern int g_mk_waiters;
void ps3_memkick_slow(void);
void ps3_memkick_wait(uint64_t us);
static inline void ps3_memkick(void)
{
    if (__atomic_load_n(&g_mk_waiters, __ATOMIC_RELAXED)) ps3_memkick_slow();
}''',
     "usleep kick header")
# The writers: SPU PUT (spu_dma.h), PUTLLC success and PUTLLUC (spu_channels.c).
edit("runtime/spu/spu_dma.h",
     '''        { extern void (*g_spu_put_hook)(uint32_t ea, uint32_t size);
          if (g_spu_put_hook) g_spu_put_hook((uint32_t)ea, size); }''',
     '''        { extern int g_mk_waiters; extern void ps3_memkick_slow(void);   /* usleep kick */
          if (__atomic_load_n(&g_mk_waiters, __ATOMIC_RELAXED)) ps3_memkick_slow(); }
        { extern void (*g_spu_put_hook)(uint32_t ea, uint32_t size);
          if (g_spu_put_hook) g_spu_put_hook((uint32_t)ea, size); }''',
     "usleep kick spu put")
edit("runtime/spu/spu_channels.c",
     '''        RESV_DROP(ctx);                                /* reservation consumed */
        spu_lockline_unlock_mask(llm);
        if (ctx->atomic_stat == 0 && g_spu_line_commit_hook) g_spu_line_commit_hook(ea & ~127u);''',
     '''        RESV_DROP(ctx);                                /* reservation consumed */
        spu_lockline_unlock_mask(llm);
        if (ctx->atomic_stat == 0) ps3_memkick();      /* usleep kick */
        if (ctx->atomic_stat == 0 && g_spu_line_commit_hook) g_spu_line_commit_hook(ea & ~127u);''',
     "usleep kick putllc")
edit("runtime/spu/spu_channels.c",
     '''        RESV_DROP(ctx); ctx->atomic_stat = 2;        /* PUTLLUC complete */
        spu_lockline_unlock_mask(llm);''',
     '''        RESV_DROP(ctx); ctx->atomic_stat = 2;        /* PUTLLUC complete */
        spu_lockline_unlock_mask(llm);
        ps3_memkick();                                 /* usleep kick */''',
     "usleep kick putlluc")
edit("runtime/syscalls/sys_timer.c",
     '''    { static long spin_us = -1;
      if (spin_us < 0) { const char* e = getenv("PS3_USLEEP_SPIN_US");''',
     '''    /* usleep kick (spu_coherency.c): a short sleep is a poll for another processor's result,
     * so it waits for the next SPU write to main memory, at most PS3_USLEEP_KICK_CAP_US.
     * PS3_USLEEP_KICK_US=0 restores the host sleep. The first distinct call sites are logged. */
    { static long kick_us = -1, cap_us = 100;
      if (kick_us < 0) { const char* e = getenv("PS3_USLEEP_KICK_US"); kick_us = e ? atol(e) : 50; if (kick_us < 0) kick_us = 0;
                         const char* c = getenv("PS3_USLEEP_KICK_CAP_US"); if (c && atol(c) > 0) cap_us = atol(c); }
      if (usec > 0 && usec <= (uint64_t)kick_us) {
          static uint32_t seen[16]; static int ns;
          const uint32_t key = (uint32_t)ctx->lr ^ ((uint32_t)usec << 24);
          int k = 0; while (k < ns && seen[k] != key) k++;
          if (k == ns && ns < 16) { seen[ns++] = key;
              fprintf(stderr, "[usleep kick] tid %u usleep(%llu) at lr 0x%08X waits for an SPU write (cap %ld us)\\n",
                      (unsigned)ctx->thread_id, (unsigned long long)usec, (uint32_t)ctx->lr, cap_us); }
          extern void ps3_memkick_wait(uint64_t us);
          ps3_memkick_wait(usec > (uint64_t)cap_us ? usec : (uint64_t)cap_us);
          return CELL_OK;
      } }
    { static long spin_us = -1;
      if (spin_us < 0) { const char* e = getenv("PS3_USLEEP_SPIN_US");''',
     "usleep kick sys_timer")
