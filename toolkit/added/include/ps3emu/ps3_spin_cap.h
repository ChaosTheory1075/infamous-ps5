/*
 * ps3_spin_cap.h -- wake storm (2026-11-11): one cap for every thread that spins before it sleeps.
 *
 * The console profile (work/agent_ps5prof/report.md 3.1) has 40-66 thousand condition-variable sleep/wake pairs a
 * second, ~8-9 us of CPU each (5-6 on the sleeper, 2.5-3 on whoever wakes it), most of them shorter than the
 * hand-off itself. A short spin on the real predicate answers most of those without the kernel -- but every game
 * thread on the PS5 is SCHED_FIFO at one priority, so a spinner never yields: 13 of them (one per hardware thread)
 * hung the console (memory: ps5-fifo-spin-hang). So spinning goes through this header and nowhere else:
 *
 *   - at most PS3_WS_SPIN_CAP threads (default 3, never more than PS3_WS_CAP_MAX = 6) spin at the same moment, in
 *     the whole process. A thread that finds the cap reached does not wait for a slot: it takes its site's
 *     ordinary sleep, exactly as without the patch;
 *   - a spin ends on the spinner's OWN clock (CLOCK_MONOTONIC, read every 8 turns), never on a flag another thread
 *     has to set, and on a turn count as well (ps3_ws_turn) should the clock ever stand still. No spin is longer
 *     than PS3_WS_MAX_US = 200 us whatever the site's knob says;
 *   - a slot is only held between ps3_ws_spin_begin and ps3_ws_spin_end, with no lock, no call that can block and
 *     no way out of the loop in between;
 *   - a site (or thread) whose spins mostly run out is turned down by itself (ps3_ws_site): under one hit in
 *     three it only probes every 16th wait, so a spin that does not pay costs nothing.
 *
 * PS3_WS=1 turns the wake-storm changes on (default off: every site sleeps, spins and wakes exactly as before):
 *   PS3_WS_SPIN_CAP=<n>   threads spinning at once, 1..6 (default 3); 0 = nobody spins
 *   PS3_WS_LAZY=0         keep waking sleepers that are not asleep (default with PS3_WS=1: skip those calls)
 * and the sites' own knobs: PS3_MK_SPIN_US (spu_coherency.c), PS3_SPU_SPIN_US / PS3_SPU_IDLE_DWELL_US
 * (spu_channels.c), PS3_BA_SPIN_US (rsx_be_async.c).
 * Not under the cap (count it as one more spinner when it is on): PS3_RSX_SPIN_US, the frame clock's own spin in
 * the runner's main.cpp (default off).
 *
 * "Lazy" wakes (signal only when somebody sleeps) use the ps3_ws_sleeper_* trio below where sleeper and waker do
 * not share a mutex. It is the store-then-load handshake the rsx doorbell and the lock-line bitmap already use:
 *     sleeper:  ps3_ws_sleeper_set(f);  look at the predicate again;  sleep;  ps3_ws_sleeper_clear(f)
 *     waker:    make the predicate true;  if (ps3_ws_sleeper_seen(f)) wake
 * The set is a LOCK'd add and the waker fences before its load, so one of the two always sees the other.
 *
 * Header-only state (one weak object, as in ps3_ftrace.h / ps3_toggles.h): no new link dependency.
 */
#ifndef PS3EMU_PS3_SPIN_CAP_H
#define PS3EMU_PS3_SPIN_CAP_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(_MSC_VER) && !defined(__clang__)
#  define PS3_WS_SHARED __declspec(selectany)
#else
#  define PS3_WS_SHARED __attribute__((weak))
#endif

#define PS3_WS_CAP_MAX   6      /* never more spinners than this, whatever the environment says (13 hung the PS5) */
#define PS3_WS_MAX_US    200    /* never a longer spin than this */
#define PS3_WS_DEBT_MAX  64     /* ps3_ws_site: see ps3_ws_spin_begin */
#define PS3_WS_DEBT_OFF  32

typedef struct {
    int on;                     /* -1 unread, 0 off, 1 on (PS3_WS) */
    int cap;                    /* PS3_WS_SPIN_CAP */
    int lazy;                   /* PS3_WS_LAZY */
    int spinners;               /* threads between spin_begin and spin_end right now: never above cap */
    int said;
    unsigned long n_hit, n_miss, n_capped, n_peak;
} ps3_ws_state;

PS3_WS_SHARED ps3_ws_state g_ps3_ws = { -1, 0, 0, 0, 0, 0, 0, 0, 0 };

/* Adaptive state of one spinning site: one per thread (__thread) or one per site with a single waiter. Plain
 * ints written by their owner only. */
typedef struct { int debt; unsigned calls; } ps3_ws_site;

static inline uint64_t ps3_ws_now_ns(void)
{
#ifdef _WIN32
    return 0;   /* no spinning through this header on Windows: ps3_ws_on() is 0 there */
#else
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec;
#endif
}

static inline void ps3_ws_pause(void)
{
#if defined(__x86_64__) || defined(__i386__)
    __builtin_ia32_pause();
#elif defined(__aarch64__)
    __asm__ __volatile__("yield" ::: "memory");
#endif
}

/* A full StoreLoad barrier (lock or on the stack: 13 cycles on Zen 2 against 69 for mfence, guest_mem_atomic.h). */
static inline void ps3_ws_fence(void)
{
#if defined(__x86_64__) && (defined(__GNUC__) || defined(__clang__))
    __asm__ __volatile__("lock; orq $0, -8(%%rsp)" : : : "memory", "cc");
#else
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
#endif
}

#if defined(__GNUC__) || defined(__clang__)
__attribute__((noinline, cold))
#endif
static inline int ps3_ws_init(void)   /* inline only so that a file which never asks is not warned about it */
{
#ifdef _WIN32
    __atomic_store_n(&g_ps3_ws.on, 0, __ATOMIC_RELEASE);
    return 0;
#else
    const char* e = getenv("PS3_WS");
    const char* c = getenv("PS3_WS_SPIN_CAP");
    const char* l = getenv("PS3_WS_LAZY");
    const int on = e && atoi(e) > 0;
    int cap = c && *c ? atoi(c) : 3;
    if (cap < 0) cap = 0;
    if (cap > PS3_WS_CAP_MAX) cap = PS3_WS_CAP_MAX;
    /* every thread that gets here writes the same values; `on` goes last */
    __atomic_store_n(&g_ps3_ws.cap, cap, __ATOMIC_RELEASE);
    __atomic_store_n(&g_ps3_ws.lazy, on && !(l && *l == '0'), __ATOMIC_RELEASE);
    __atomic_store_n(&g_ps3_ws.on, on, __ATOMIC_RELEASE);
    if (on && !__atomic_exchange_n(&g_ps3_ws.said, 1, __ATOMIC_ACQ_REL))
        fprintf(stderr, "[wake storm] on: at most %d threads spin at once (each at most %d us), wakes for nobody %s\n",
                cap, PS3_WS_MAX_US, (l && *l == '0') ? "kept" : "skipped");
    return on;
#endif
}

/* 1 = PS3_WS=1. */
static inline int ps3_ws_on(void)
{
    const int on = __atomic_load_n(&g_ps3_ws.on, __ATOMIC_ACQUIRE);
    return __builtin_expect(on < 0, 0) ? ps3_ws_init() : on;
}
static inline int ps3_ws_lazy(void) { return ps3_ws_on() > 0 && __atomic_load_n(&g_ps3_ws.lazy, __ATOMIC_RELAXED); }

/* May this thread spin now? 1 = yes, and it holds one of the cap's slots until ps3_ws_spin_end (which must follow
 * on every path, with nothing that can block in between). 0 = sleep the ordinary way: the wake-storm switch is
 * off, the cap is reached, or this site's spins have not been paying (it then probes one wait in 16). */
static inline int ps3_ws_spin_begin(ps3_ws_site* s)
{
    if (ps3_ws_on() <= 0) return 0;
    if (s && s->debt >= PS3_WS_DEBT_OFF && (++s->calls & 15u)) return 0;
    const int cap = __atomic_load_n(&g_ps3_ws.cap, __ATOMIC_RELAXED);
    int n = __atomic_load_n(&g_ps3_ws.spinners, __ATOMIC_RELAXED);
    for (int tries = 0; tries < 4; tries++) {          /* bounded: losing the race four times is "cap reached" too */
        if (n >= cap) break;
        if (__atomic_compare_exchange_n(&g_ps3_ws.spinners, &n, n + 1, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)) {
            if ((unsigned long)(n + 1) > __atomic_load_n(&g_ps3_ws.n_peak, __ATOMIC_RELAXED))
                __atomic_store_n(&g_ps3_ws.n_peak, (unsigned long)(n + 1), __ATOMIC_RELAXED);
            return 1;
        }
    }
    __atomic_fetch_add(&g_ps3_ws.n_capped, 1ul, __ATOMIC_RELAXED);
    return 0;
}

/* Give the slot back. hit = the predicate came true while spinning. A miss adds one to the site's debt, a hit takes
 * two off: under one hit in three the debt climbs to PS3_WS_DEBT_OFF and the site stops spinning (probes aside). */
static inline void ps3_ws_spin_end(ps3_ws_site* s, int hit)
{
    __atomic_fetch_sub(&g_ps3_ws.spinners, 1, __ATOMIC_RELEASE);
    if (s) {
        if (hit) s->debt = s->debt > 2 ? s->debt - 2 : 0;
        else if (s->debt < PS3_WS_DEBT_MAX) s->debt++;
    }
    const unsigned long n = __atomic_add_fetch(hit ? &g_ps3_ws.n_hit : &g_ps3_ws.n_miss, 1ul, __ATOMIC_RELAXED);
    if (!hit && (n & 0xFFFFul) == 0)
        fprintf(stderr, "[wake storm] spins: %lu answered, %lu ran out, %lu not started (cap %d reached); most at once %lu\n",
                __atomic_load_n(&g_ps3_ws.n_hit, __ATOMIC_RELAXED), n,
                __atomic_load_n(&g_ps3_ws.n_capped, __ATOMIC_RELAXED),
                __atomic_load_n(&g_ps3_ws.cap, __ATOMIC_RELAXED),
                __atomic_load_n(&g_ps3_ws.n_peak, __ATOMIC_RELAXED));
}

/* The spinner's own stop: a clock deadline and a turn limit. */
typedef struct { uint64_t t0, lim_ns; unsigned k, kmax; } ps3_ws_clock;

static inline unsigned ps3_ws_clamp_us(int us)
{
    return us <= 0 ? 0u : us > PS3_WS_MAX_US ? (unsigned)PS3_WS_MAX_US : (unsigned)us;
}
/* Turns (8 pauses each) a spin of `us` may take at most. A turn is ~0.15 us on Zen 2, so the clock ends the spin
 * long before this does; it is there for a clock that stands still. */
static inline unsigned ps3_ws_turn_limit(unsigned us) { return us * 64u + 64u; }

static inline void ps3_ws_clock_start(ps3_ws_clock* c, int us)
{
    const unsigned u = ps3_ws_clamp_us(us);
    c->t0 = ps3_ws_now_ns();
    c->lim_ns = (uint64_t)u * 1000ull;
    c->k = 0;
    c->kmax = ps3_ws_turn_limit(u);
}
/* One turn of a spin: 8 pauses. 0 = time is up. Use as: do { if (predicate) { hit = 1; break; } } while (ps3_ws_turn(&c)); */
static inline int ps3_ws_turn(ps3_ws_clock* c)
{
    for (int i = 0; i < 8; i++) ps3_ws_pause();
    if (++c->k >= c->kmax) return 0;
    if (!(c->k & 7u) && ps3_ws_now_ns() - c->t0 > c->lim_ns) return 0;
    return 1;
}

/* Sleeper flags for a wake that is skipped when nobody sleeps (see the top of this file). */
static inline void ps3_ws_sleeper_set(int* f)   { __atomic_fetch_add(f, 1, __ATOMIC_SEQ_CST); }
static inline void ps3_ws_sleeper_clear(int* f) { __atomic_fetch_sub(f, 1, __ATOMIC_SEQ_CST); }
static inline int  ps3_ws_sleeper_seen(int* f)  { ps3_ws_fence(); return __atomic_load_n(f, __ATOMIC_SEQ_CST) != 0; }

#ifdef __cplusplus
}
#endif

#endif /* PS3EMU_PS3_SPIN_CAP_H */
