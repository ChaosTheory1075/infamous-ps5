# lwsync cv reuse: one condition variable per thread for lwmutex/lwcond waits (the PS5 pthread pool leak)
# The console runs died after 6-12 min with "[ScePthread/System] Internal Memory is running out." (if1
# 2026-11-02 15:55, if2 21:19). BC-250 count (tools/pthread_leakcount.c, LD_PRELOAD): in ~2 min of if2,
# SleepConditionVariableSRW (sys_lwsync.c) did 14,831 pthread_mutex_init + 14,830 pthread_cond_init and
# no destroy. Each lwmutex/lwcond wait puts a waiter on the stack whose CONDITION_VARIABLE is created
# lazily on its first sleep (calloc + mutex + cond, win32_compat.h ps3_cv) and never freed: Win32
# condition variables need no cleanup, so the emulation has no delete. On the PS5 every one holds a
# libkernel pthread object until the pool runs out (on Linux, heap). Now each thread creates one
# ps3_condvar on its first wait and every later wait of that thread reuses it. A thread is in at most
# one wait at a time, and wakers run under s_lock while the waiter is queued, so a reused object never
# gets a wake meant for an earlier wait that matters (a stray generation bump is a spurious wakeup,
# which the while (!w->woken) loops already allow).
LWS = "runtime/syscalls/sys_lwsync.c"
edit(LWS,
     '''static void waiter_init(waiter* w, ppu_context* ctx)
{
    memset(w, 0, sizeof *w);
    w->tid = ctx->thread_id;
    InitializeConditionVariable(&w->cv);
}''',
     '''static __thread CONDITION_VARIABLE t_lw_cv;   /* lwsync cv reuse: this thread's one condvar */
static void waiter_init(waiter* w, ppu_context* ctx)
{
    memset(w, 0, sizeof *w);
    w->tid = ctx->thread_id;
    InitializeConditionVariable(&w->cv);
    if (!t_lw_cv) WakeConditionVariable(&t_lw_cv);   /* creates it (a wake with no waiter is a no-op) */
    w->cv = t_lw_cv;
}''',
     "lwsync cv reuse")
