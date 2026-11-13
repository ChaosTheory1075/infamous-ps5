/* be async: the draw engine's backend calls recorded on a worker thread.
 *
 * On the console the RSX thread is the frame's limit in dense scenes (inFAMOUS 1: FIFO drain 80-100%
 * of each second), and about a quarter of its per-draw time is the backend turning a draw into Vulkan
 * commands. This proxy sits between the engine and the real backend: calls that return nothing (binds,
 * state, draws, clears, releases) are copied into blocks the worker replays in order; every call that
 * returns something (creates, snapshots, views, readbacks, present, submit) first waits until the worker
 * has replayed everything queued and is idle, then runs on the caller's thread. So the backend only ever
 * runs on one thread at a time, in the order the engine issued, and handles come back exactly as before.
 * The worker sleeps on a condition variable when there is nothing to do (no spinning: the console hangs
 * with too many spinning FIFO threads).
 *
 * PS3RECOMP_BE_ASYNC=1 turns it on (rsx_draw_engine_set_backend wraps the backend). */
#include "rsx_draw_engine.h"
#include "ps3emu/ps3_spin_cap.h"   /* wake storm: the shared spinner cap */
#include "rsx_vs_delta.h"           /* ba vs delta */
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <time.h>      /* be present async limit: clock_gettime; ba view direct: drain timing */
#include <unistd.h>
#include "rsx_ba_replayop.h"         /* ba replay op */
#ifdef __linux__
#include <sys/syscall.h>
#define BA_TID() ((long)syscall(SYS_gettid))
#else
#define BA_TID() 0L
#endif

enum {
    OP_BIND_TARGETS = 1, OP_BIND_PIPELINE, OP_BIND_VS, OP_BIND_PS, OP_BIND_TEX, OP_BIND_VTEX,
    OP_VIEWPORT, OP_SCISSOR, OP_STENCIL_REF, OP_DRAW, OP_CLEAR_COLOR, OP_CLEAR_DS, OP_VS_RANGE,
    OP_DRAW_VBUF, OP_DRAW_VBUF_IB, OP_SET_HUD, OP_DEPTH_BIAS, OP_DEPTH_CLAMP,
    OP_TEX_RELEASE, OP_CT_RELEASE, OP_DT_RELEASE, OP_PIPE_RELEASE, OP_VBUF_RELEASE, OP_CSNAP, OP_TEX_UPLOAD, OP_PRESENT,
    OP_OCCQ_BEGIN, OP_OCCQ_END,  /* occ query */
    OP_DD_MARK,                  /* ba dedup: no backend call; the worker's verify state restarts here */
    OP_VBUF_CREATE, OP_VB_CHECK, /* ba vbuf async */
    OP_DRAW_VBUF_REF,            /* ba idx ref */
    OP_VS_DELTA                  /* ba vs delta */
};
#define BA_OP_DD 0x80000000u     /* ba dedup verify: set on an op the proxy would have skipped */

#define BA_BLOCK   (512u << 10)   /* bytes per block */
#define BA_BLOCKS  48u            /* in flight at most (24 MB) */
#define BA_KICK    96u            /* ops per block before it goes to the worker (default; PS3_BA_KICK=<n>: ba handoff) */

typedef struct ba_block { struct ba_block* next; u32 used, ops; unsigned long long seq; u8 data[BA_BLOCK]; } ba_block;   /* seq: ba idx ref */

static rsx_draw_backend s_real, s_proxy;
static pthread_mutex_t s_mu = PTHREAD_MUTEX_INITIALIZER;     /* queue, free list, idle flag */
static pthread_mutex_t s_prod = PTHREAD_MUTEX_INITIALIZER;   /* one producer at a time */
static pthread_cond_t s_cv_work = PTHREAD_COND_INITIALIZER, s_cv_done = PTHREAD_COND_INITIALIZER;
static ba_block *s_head, *s_tail, *s_free, *s_cur;
static u32 s_nblocks;
static int s_busy;            /* worker is replaying a block */
static u8 s_vs_rows[512 * 16];   /* the worker's copy of the constant rows (ranged uploads) */
static unsigned long long s_n_ops, s_n_sync, s_n_blocks_sent;
static unsigned s_sync_by[32];   /* waits by caller (stats) */
static unsigned s_csnap_q, s_csnap_bad;   /* colour snapshots queued, replays that returned another handle */
enum { SY_TEXC, SY_TEXU, SY_VIEW, SY_SNAP, SY_PIPE, SY_PRESENT, SY_VBUF, SY_OTHER, SY_ZSNAP, SY_ZRGBA, SY_N };
static const char* const s_sync_name[SY_N] = { "texture_create", "texture_upload", "surface_view", "snapshot", "pipeline_create", "present", "vbuf_create", "other", "depth_snapshot", "depth_rgba8" };

#define ALIGN8(x) (((x) + 7u) & ~7u)

/* ba handoff (2026-11-10): two switches, both default off, for the cost of handing blocks to the worker
 * (~785 futex wakes a frame on the BC-250 at 96 ops a block, one mutex pair per op).
 *  PS3_BA_KICK=<n>   ops per block before it goes to the worker (1..1048576, default BA_KICK = 96). Only the
 *                    threshold in ba_put changes: every place that needs the worker to catch up or to start
 *                    (ba_drain = every synchronous call: creates, views, snapshots, readbacks, submit_and_wait,
 *                    present, init/shutdown, the "does not fit a block" fallbacks; the queued present; a block
 *                    out of room) still sends the partial block through ba_send_cur, which has no threshold.
 *  PS3_BA_NOLOCK=1   no s_prod lock/unlock around each op. Sound because there is one producer: every proxy is
 *                    reached only through g.be in rsx_draw_engine.c, and the engine's backend-calling entry
 *                    points (method/const_words/write_back_to from the FIFO drain, present, init, shutdown,
 *                    readback_center) are all called from the one thread that runs the game's main loop
 *                    (main.cpp: rsx_backend_init, cellGcm_rsx_process_fifo, rsx_backend_present; the drain is
 *                    also under s_gcm_fifo_lock). The texhash helper, gpu_light/gpu_ssao data and
 *                    set_display_buffer never call the backend. Producer -> worker hand-off stays under s_mu,
 *                    which is what orders the block's bytes and the worker's backend state between the threads.
 *                    If a second thread ever produces, the ba producer guard below turns the lock back on for good.
 * With either on, a "[ba handoff]" line every 600 presents: ops, blocks, wakes (signals that found the worker
 * asleep). */
static u32 s_kick = BA_KICK;
static int s_nolock, s_ho_stats;
static int s_waiting;                               /* worker is in cond_wait for work (s_mu) */
static unsigned long long s_ho_ops, s_ho_blocks, s_ho_wakes;   /* blocks/wakes under s_mu, ops producer only */
#include <stdint.h>    /* ba producer guard: uintptr_t (here, not at the top: the patch applies to t34 and t35) */
#include <time.h>      /* ba producer guard: clock_gettime */

/* ba producer guard (2026-11-12): PS3_BA_NOLOCK=1 stays sound if a second producer thread ever appears.
 * The first producer thread owns the lock-free path. Every other thread, on its first op, turns the lock back on for
 * good (as if PS3_BA_NOLOCK=0), logs once, and starts its op only when the owner can no longer be inside a lock-free
 * op; from then on every op of every thread takes s_prod. So no block, cursor or proxy state is ever written by two
 * threads at once.
 *  - Ids: a thread's token is the address of its thread-local t_ba_own (gettid() prints 0 on the PS5). t_ba_own is
 *    1 in the owner, 0 (zero-initialised TLS, no relocation in the TLS image) in every other thread; it picks the
 *    thread's slot: s_ba_slot[1] the owner's, s_ba_slot[0] shared by all others and read by nobody.
 *  - Owner fast path (ba_nl_lock): store 1 to its slot's in_sec, then ONE branch on the atomic load s_ba_fast ==
 *    its slot. ba_nl_unlock: one compare (s_prod_locker is not this thread) and a release store of in_sec = 0.
 *  - A second thread (ba_nl_lock_slow): under s_ba_ctl stores s_ba_fast = NULL and s_ba_lockreq = 1 (seq_cst), takes
 *    s_prod, then ba_handover_wait: it goes on when
 *      (a) the owner has acknowledged (s_ba_acked): the owner sets it in its NEXT ba_nl_lock, which fails (it reads
 *          s_ba_fast == NULL), i.e. after every lock-free op it ever started has ended (program order + release /
 *          acquire), and it then queues behind s_prod like everyone else; or
 *      (b) the owner is idle: BA_HO_GRACE_NS after its own store, the owner's in_sec reads 0 (acquire; pairs with the
 *          release at the end of the owner's op). The owner stores in_sec = 1 BEFORE it loads s_ba_fast, so an op it
 *          started on the old value has its 1 out of the store buffer long before the grace is over, and any op it
 *          starts later reads NULL and takes s_prod. An owner that never produces again therefore costs the second
 *          thread one grace period, not a hang.
 *    While the owner is inside an op (in_sec 1, a long synchronous call), it waits (sleeping 100 us steps, never
 *    spinning; logs at 20 ms, 1 s, then every 10 s): that op always ends, and the wait with it.
 *  - Lock mode (PS3_BA_NOLOCK unset/0) is today's code path: the s_nolock branch, then pthread_mutex_lock/unlock.
 * The "[ba handoff]" line: producer changes (second-producer detections), lock back on, how the hand-over ended. */
typedef struct { int in_sec; int pad[15]; } ba_slot;
static ba_slot s_ba_slot[2] __attribute__((aligned(64)));   /* [1] the owner's, [0] everybody else's */
#define s_ba_owner_slot (s_ba_slot[1])
static _Thread_local int t_ba_own;                  /* 1 = this thread is the owner */
static ba_slot* s_ba_fast;                          /* atomic: the owner's slot while the lock-free path is on, else NULL */
static uintptr_t s_prod_locker;                     /* atomic: &t_ba_own of the thread holding s_prod (nolock mode) */
static int s_ba_claimed, s_ba_lockreq, s_ba_acked, s_ba_hodone;   /* claimed: under s_ba_ctl; the rest atomic */
static unsigned s_owner_changes;                    /* second-producer detections (under s_ba_ctl) */
static int s_ba_ho_how;                             /* 1 acknowledged, 2 owner idle (s_prod held) */
static unsigned long long s_ba_req_ns, s_ba_ho_us;
static pthread_mutex_t s_ba_ctl = PTHREAD_MUTEX_INITIALIZER;
#define BA_HO_GRACE_NS 1000000ull                   /* 1 ms: far beyond a store buffer's drain */
static unsigned long long ba_ho_ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (unsigned long long)t.tv_sec * 1000000000ull + (unsigned long long)t.tv_nsec; }
static void ba_handover_wait(void)
{
    unsigned long long now = ba_ho_ns(), next_log = 20000000ull;
    for (;;) {
        if (__atomic_load_n(&s_ba_acked, __ATOMIC_ACQUIRE)) { s_ba_ho_how = 1; break; }
        now = ba_ho_ns();
        if (now - s_ba_req_ns >= BA_HO_GRACE_NS && !__atomic_load_n(&s_ba_owner_slot.in_sec, __ATOMIC_SEQ_CST)) { s_ba_ho_how = 2; break; }
        if (now - s_ba_req_ns >= next_log) {
            fprintf(stderr, "[ba handoff] second producer: the owner is still inside one op after %llu ms, waiting\n", (now - s_ba_req_ns) / 1000000ull);
            next_log = next_log < 1000000000ull ? 1000000000ull : next_log + 10000000000ull;
        }
        usleep(100);
    }
    s_ba_ho_us = (now - s_ba_req_ns) / 1000ull;
    __atomic_store_n(&s_ba_hodone, 1, __ATOMIC_RELEASE);
    fprintf(stderr, "[ba handoff] hand-over done after %llu us (%s): every producer op takes the lock now\n",
            s_ba_ho_us, s_ba_ho_how == 1 ? "owner acknowledged" : "owner idle");
}
static void __attribute__((noinline)) ba_nl_lock_slow(ba_slot* p)
{
    __atomic_store_n(&p->in_sec, 0, __ATOMIC_RELEASE);   /* not a lock-free op after all */
    if (!__atomic_load_n(&s_ba_lockreq, __ATOMIC_ACQUIRE)) {
        pthread_mutex_lock(&s_ba_ctl);
        if (!s_ba_claimed && !__atomic_load_n(&s_ba_lockreq, __ATOMIC_RELAXED)) {   /* the first producer: the owner */
            s_ba_claimed = 1;
            t_ba_own = 1;
            __atomic_store_n(&s_ba_owner_slot.in_sec, 1, __ATOMIC_RELAXED);
            __atomic_store_n(&s_ba_fast, &s_ba_owner_slot, __ATOMIC_SEQ_CST);
            pthread_mutex_unlock(&s_ba_ctl);
            return;                                      /* this op lock-free, ended by ba_nl_unlock */
        }
        if (p != &s_ba_owner_slot && !__atomic_load_n(&s_ba_lockreq, __ATOMIC_RELAXED)) {   /* a second producer */
            s_ba_req_ns = ba_ho_ns();                    /* before lockreq: a third producer that sees lockreq sees the time too (guard review, defect B) */
            __atomic_store_n(&s_ba_fast, (ba_slot*)NULL, __ATOMIC_SEQ_CST);
            __atomic_store_n(&s_ba_lockreq, 1, __ATOMIC_SEQ_CST);
            s_owner_changes++;
            fprintf(stderr, "[ba handoff] WARNING: second producer thread seen: producer lock back on (thread token %p)\n", (void*)&t_ba_own);
        }
        pthread_mutex_unlock(&s_ba_ctl);
    }
    const int req = __atomic_load_n(&s_ba_lockreq, __ATOMIC_ACQUIRE);
    if (p == &s_ba_owner_slot && req && !__atomic_load_n(&s_ba_acked, __ATOMIC_RELAXED))
        __atomic_store_n(&s_ba_acked, 1, __ATOMIC_RELEASE);   /* the owner: all its lock-free ops are over */
    pthread_mutex_lock(&s_prod);
    __atomic_store_n(&s_prod_locker, (uintptr_t)&t_ba_own, __ATOMIC_RELAXED);
    if (req && !__atomic_load_n(&s_ba_hodone, __ATOMIC_ACQUIRE)) ba_handover_wait();
}
static inline void ba_nl_lock(void)
{
    ba_slot* const p = &s_ba_slot[t_ba_own];
    __atomic_store_n(&p->in_sec, 1, __ATOMIC_RELAXED);
    __atomic_signal_fence(__ATOMIC_SEQ_CST);           /* compiler: the store stays before the load */
    /* guard review, defect A: this store is NOT a seq_cst (locked) store on purpose: one xchg per queued op would cost the single
     * producer ~0.1-0.2 ms a frame. The hand-over therefore relies on the 1 ms grace in ba_handover_wait outlasting this thread's
     * store buffer (nanoseconds on x86; a context switch drains it). Not an ordering proof. */
    if (__builtin_expect(__atomic_load_n(&s_ba_fast, __ATOMIC_ACQUIRE) == p, 1)) return;
    ba_nl_lock_slow(p);
}
static inline void ba_nl_unlock(void)
{
    if (__builtin_expect(__atomic_load_n(&s_prod_locker, __ATOMIC_RELAXED) != (uintptr_t)&t_ba_own, 1)) {
        __atomic_store_n(&s_ba_owner_slot.in_sec, 0, __ATOMIC_RELEASE);   /* the owner's lock-free op ends */
        return;
    }
    __atomic_store_n(&s_prod_locker, (uintptr_t)0, __ATOMIC_RELAXED);
    pthread_mutex_unlock(&s_prod);
}
#define PROD_LOCK()   do { if (__builtin_expect(!s_nolock, 1)) pthread_mutex_lock(&s_prod); else ba_nl_lock(); } while (0)
#define PROD_UNLOCK() do { if (__builtin_expect(!s_nolock, 1)) pthread_mutex_unlock(&s_prod); else ba_nl_unlock(); } while (0)

/* wake storm (2026-11-11; PS3_WS=1, default off): the hand-off without the kernel where nobody sleeps.
 * Console profile: the worker went back to sleep after nearly every block (14-19 thousand cond_wait/signal pairs a
 * second at 96 ops a block, ~8 us each, 2.5-3 of them on the RSX thread), and each of the ~800 synchronous calls a
 * second parked the RSX thread for 27 us on average.
 *  - lazy (PS3_WS_LAZY, on with PS3_WS=1): pthread_cond_signal(s_cv_work) only when the worker is in its cond_wait
 *    (s_waiting), pthread_cond_broadcast(s_cv_done) only when somebody is in a cond_wait on it (s_done_waiters).
 *    Both flags are written and read under s_mu, the mutex those waits release, so "flag clear" means "nobody is
 *    or can be waiting for this change": exactly the calls that woke no one are dropped.
 *  - PS3_BA_SPIN_US=<us> (default 0): the worker, out of blocks, first looks for the next one for that long, and
 *    ba_drain looks for the idle worker for that long, both WITHOUT s_mu and through the spinner cap
 *    (ps3_spin_cap.h: own clock, at most PS3_WS_SPIN_CAP threads at once, turned down when it does not pay). The
 *    unlocked look is only a hint to stop spinning: each then takes s_mu and decides under it as before -- sleep
 *    only if the predicate is still false there -- so a hand-off can not be missed whatever the hint read.
 * The "[ba handoff]" line's wakes are the signals really sent. */
static int s_ws_lazy, s_ws_spin_us;
static int s_done_waiters;                          /* threads in cond_wait on s_cv_done (s_mu) */
static ps3_ws_site s_ws_worker, s_ws_drain;         /* one waiter each: the worker, the producer */

static void* ba_put(u32 op, u32 bytes);

/* ba dedup (2026-11-11; PS3_BA_DEDUP, default 0 = off, every call queued as before): a state call whose arguments
 * equal the last queued call of the same kind is not queued. On the console the RSX thread queues ~11 ops a draw
 * (~90k a frame) and ~80% of the draws are draw-fast replays that bind exactly the previous draw's targets, pipeline,
 * fragment constants, textures, viewport, scissor, stencil ref and depth bias again; each costs a ba_put, a copy into
 * the block and a replay on the worker. Sound because the Vulkan backend's handlers for these kinds are pure setters
 * (s_e2 / s_eng_bound fields, the fragment-constant UBO shadow) that only the same kind writes: the backend's own
 * passes (fs/light/ssao) restore everything they change, and they run synchronously, i.e. after ba_drain. So the
 * last-queued shadow is forgotten (s_dd_valid = 0) at every ba_drain (every synchronous call) and at every queued
 * op other than these kinds, the vertex constants and the draws (releases, clears, present, snapshots, uploads,
 * occlusion queries, hud...). The depth clamp is a kind too (vk depth clamp: a pure setter).
 *  PS3_BA_DEDUP=1  skip the repeats.
 *  PS3_BA_DEDUP=2  verify: queue everything; an op that =1 would skip carries BA_OP_DD and the worker checks that
 *                  its payload equals the last one of its kind it replayed since the last reset (same reset rules,
 *                  plus OP_DD_MARK for the synchronous calls it cannot see). "[ba dedup]" every 300 presents:
 *                  would-skip / eligible ops, worker checks / mismatches (must stay 0). */
enum { DD_TARGETS, DD_PIPE, DD_PS, DD_TEX, DD_VTEX, DD_VP, DD_SC, DD_SREF, DD_ZBIAS, DD_ZCLAMP, DD_N };   /* vk depth clamp: DD_ZCLAMP */
#define DD_CAP 2048u
static int s_dd;                                   /* PS3_BA_DEDUP, read once before the worker exists */
/* ba replay op (rsx_ba_replayop.h): the engine reads the dedup memory's validity, skip count and epoch.
 * g_rsx_ba_ro.ep moves at every change of the memory: dd_reset, and dd_check's record / too-big paths. */
rsx_ba_ro g_rsx_ba_ro = { 1ull, 0ull, 0u, 0u, 0, 0ull, 0ull, 0ull, 0ull, 0u };
#define s_dd_valid (g_rsx_ba_ro.dd_valid)          /* producer: bit k = s_dd_buf[k] is the last queued kind k */
static int s_dd_markp;                             /* producer, verify: a reset the worker has not seen yet */
static u32 s_dd_len[DD_N];
static u8 s_dd_buf[DD_N][DD_CAP] __attribute__((aligned(16)));
static unsigned long long s_dd_seen;               /* producer stats */
#define s_dd_skip (g_rsx_ba_ro.dropped)            /* producer stats (ba replay op: its verify reads it) */
static unsigned s_dd_vchk, s_dd_vbad;              /* worker stats (read racily for the log line) */
typedef struct { const void* p; u32 n; } dd_piece; /* p NULL = n zero bytes (what the proxy queues for NULL) */
static void dd_reset(void) { if (s_dd) { s_dd_valid = 0; g_rsx_ba_ro.ep++; if (s_dd == 2) s_dd_markp = 1; } }   /* ba replay op: ep */
static int dd_zero(const u8* b, u32 n) { for (u32 i = 0; i < n; i++) if (b[i]) return 0; return 1; }
/* 1 = this call's arguments equal the last queued call of kind k (skip it); else remembers them. */
static int dd_check(u32 k, const dd_piece* pc, int np)
{
    if (s_dd_markp) { s_dd_markp = 0; void* m = ba_put(OP_DD_MARK, 0); (void)m; }
    u32 tot = 0;
    for (int i = 0; i < np; i++) tot += pc[i].n;
    s_dd_seen++;
    if (tot > DD_CAP) { s_dd_valid &= ~(1u << k); g_rsx_ba_ro.ep++; return 0; }   /* ba replay op: ep */
    u8* const b = s_dd_buf[k];
    if (((s_dd_valid >> k) & 1u) && s_dd_len[k] == tot) {
        u32 o = 0; int same = 1;
        for (int i = 0; same && i < np; o += pc[i].n, i++)
            if (pc[i].n) same = pc[i].p ? !memcmp(b + o, pc[i].p, pc[i].n) : dd_zero(b + o, pc[i].n);
        if (same) { s_dd_skip++; return 1; }
    }
    u32 o = 0;
    for (int i = 0; i < np; o += pc[i].n, i++) {
        if (!pc[i].n) continue;
        if (pc[i].p) memcpy(b + o, pc[i].p, pc[i].n); else memset(b + o, 0, pc[i].n);
    }
    s_dd_len[k] = tot; s_dd_valid |= 1u << k;
    g_rsx_ba_ro.ep++;   /* ba replay op: kind k's memory changed */
    return 0;
}
/* The op word for a dedup-eligible call: 0 = skip it (PS3_BA_DEDUP=1), else op (| BA_OP_DD in verify mode). */
static u32 dd_op(u32 op, u32 k, const dd_piece* pc, int np)
{
    if (!s_dd) return op;
    if (!dd_check(k, pc, np)) return op;
    return s_dd == 1 ? 0u : (op | BA_OP_DD);
}
/* worker side of PS3_BA_DEDUP=2 */
static int dd_kind_of(u32 op)
{
    switch (op) {
    case OP_BIND_TARGETS: return DD_TARGETS; case OP_BIND_PIPELINE: return DD_PIPE; case OP_BIND_PS: return DD_PS;
    case OP_BIND_TEX: return DD_TEX; case OP_BIND_VTEX: return DD_VTEX; case OP_VIEWPORT: return DD_VP;
    case OP_SCISSOR: return DD_SC; case OP_STENCIL_REF: return DD_SREF; case OP_DEPTH_BIAS: return DD_ZBIAS;
    case OP_DEPTH_CLAMP: return DD_ZCLAMP;   /* vk depth clamp */
    case OP_BIND_VS: case OP_VS_RANGE: case OP_DRAW: case OP_DRAW_VBUF: case OP_DRAW_VBUF_IB: return -1;   /* neutral */
    /* perfstack (ba dedup + ba vbuf async): the id check reads only the worker's id map -> neutral (it precedes
     * every draw in PS3_BA_VBUF_ASYNC=2; a reset there would void every verify). The draws stay neutral when they
     * are translated (id -> backend number, or draw() from a kept copy, or dropped): vk_eng_draw_vbuf /
     * _draw_vbuf_ib / vk_eng_draw_from write no bound state (s_e2 / s_eng_bound / UBO ps shadow). OP_VBUF_CREATE
     * and OP_VBUF_RELEASE reset (default), and the proxy resets with them (px_vbuf_create / px_vbuf_release). */
    case OP_VB_CHECK: return -1;
    case OP_DRAW_VBUF_REF: return -1;   /* ba idx ref: a draw like OP_DRAW_VBUF (its payload holds an address: never compared) */
    case OP_VS_DELTA: return -1;        /* ba vs delta: OP_VS_RANGE in another form (the proxy never dd_resets for either) */
    default: return -2;                                                                                /* resets */
    }
}
static void dd_verify(u32 op, u32 flagged, const u8* a, u32 len)
{
    static u32 valid, wlen[DD_N];
    static u8 wbuf[DD_N][DD_CAP + 16];
    const int k = dd_kind_of(op);
    if (k == -2) { valid = 0; return; }
    if (k < 0) return;
    if (flagged) {
        __atomic_fetch_add(&s_dd_vchk, 1u, __ATOMIC_RELAXED);
        if (!((valid >> k) & 1u) || wlen[k] != len || memcmp(wbuf[k], a, len))
            __atomic_fetch_add(&s_dd_vbad, 1u, __ATOMIC_RELAXED);
    }
    if (len > sizeof wbuf[k]) { valid &= ~(1u << k); return; }
    memcpy(wbuf[k], a, len); wlen[k] = len; valid |= 1u << k;
}

/* ba vbuf async (2026-11-11; PS3_BA_VBUF_ASYNC=1, default off; =2 adds a per-draw self-check).
 * vbuf_create (the vertex cache's persistent buffers, the resident index buffers) waited for the worker only to learn
 * the backend's number: 19.5 of the 41.6 waits a frame in the console's slow windows. A vertex buffer number is only
 * ever handed back through draw_vbuf / draw_vbuf_ib / vbuf_release (nothing else in the engine or backend names it, and
 * the backend never frees one on its own), so the proxy numbers them itself and the worker maps its numbers ("ids")
 * to the backend's when it replays those ops. The create is an ordered op carrying a COPY of the bytes (the engine
 * reuses dc.verts / the index memo at once).
 *  - Ids: fresh ones first (1..65536), then the OLDEST released one (FIFO ring), never the newest: a holder that kept
 *    an id past its release (the texguard bug class: lowest/newest-free reuse makes a stale number name the next
 *    object at once) names a dead id for ~65536 - live creates, so its draws are dropped and counted instead of
 *    drawing someone else's mesh. An id goes on the ring when its release is RECORDED: every op that can name it
 *    again (the create that takes it) is queued behind that release in the one FIFO the worker replays.
 *  - Order: one producer queue, one worker, replayed in order. A draw recorded after create(id) replays after it; the
 *    engine draws an id only between its create and its release, and the next create(id) is recorded after the
 *    release -> a draw never sees an id before its create nor after its release (bar an engine use-after-release,
 *    which today draws whatever the backend gave the number to, and here finds the id dead: dropped, counted).
 *  - Too big for a block, or the next 600 creates after a create failed on the worker: synchronous as before (worker
 *    drained, the producer fills the id map itself) and a failure returns 0 to the engine exactly as today.
 *  - A create failing on the worker (out of slab memory / backend numbers): the engine already holds the id, as
 *    resident. The worker keeps a copy of the bytes (up to VB_KEEP_MAX in all) and draws that id's draws with draw()
 *    from it -- the picture the engine itself makes when vbuf_create returns 0 (it fetches the same bytes again and
 *    calls draw(); the cache entry only exists while its content hash is unchanged). No copy room: dropped, counted.
 *    There is no "backend freed it" notification for vertex buffers to tell the engine (texguard is textures only).
 *  - =2 (verify): each draw_vbuf / draw_vbuf_ib is preceded by OP_VB_CHECK (id, create generation, bytes the draw
 *    reads) and the worker checks the id is live with that generation and size; and the backend's number for a new
 *    create must not already belong to another live id. Any mismatch is counted and the first 8 are logged.
 * Off: the old proxies and replays, unchanged. */
#define VB_MAX 65536u
#define VB_KEEP_MAX (64u << 20)
typedef struct { u32 h, bytes, gen, failed; void* copy; } ba_vbw;   /* failed: its create failed on the worker */
static int s_vbasync;                                    /* 0 off, 1 on, 2 on + verify (read-only after wrap) */
static ba_vbw* s_vbw;                                    /* worker (or the producer with the worker drained): id -> backend */
static u32* s_vb_rev;                                    /* worker, verify: backend number -> id */
static size_t s_vb_kept;                                 /* worker: bytes of kept copies */
static unsigned long long s_vb_wdone;                    /* atomic: creates the worker (or a sync path) has run */
static unsigned s_vb_wfail, s_vb_wcopy, s_vb_wdrop, s_vb_wbad, s_vb_walias;   /* worker stats (atomic, run totals) */
static u32 s_vb_n, s_vb_rhead, s_vb_rn;                  /* producer: fresh ids used, FIFO ring of released ids */
static u32* s_vb_ring; static u8* s_vb_live; static u32* s_vb_pgen;
static u32 s_vb_nlive, s_vb_nlive_max, s_vb_infl_max, s_vb_sync_left;
static unsigned long long s_vb_qn, s_vb_qbytes;
static unsigned s_vbq, s_vbbig, s_vbsync, s_vbnoid, s_vb_deadrel, s_vb_deaddraw, s_vb_wfail_seen;
static void vb_release_w(u32 id)
{
    if (!id || id > VB_MAX) return;
    ba_vbw* v = &s_vbw[id];
    if (v->h) { if (s_vb_rev && v->h <= VB_MAX) s_vb_rev[v->h] = 0; s_real.vbuf_release(s_real.user, v->h); }
    if (v->copy) { free(v->copy); s_vb_kept -= v->bytes; }
    v->h = 0; v->copy = NULL; v->bytes = 0; v->failed = 0;
}
static void vb_set_w(u32 id, u32 gen, u32 r, u32 bytes)   /* id now names backend buffer r (r may be 0: failed) */
{
    ba_vbw* v = &s_vbw[id];
    if (v->h || v->copy) { __atomic_fetch_add(&s_vb_wbad, 1u, __ATOMIC_RELAXED); vb_release_w(id); }   /* never: reuse follows a release */
    v->h = r; v->bytes = bytes; v->gen = gen; v->copy = NULL; v->failed = 0;
    if (r && s_vb_rev && r <= VB_MAX) {
        if (s_vb_rev[r] && s_vb_rev[r] != id) {
            const unsigned n = __atomic_fetch_add(&s_vb_walias, 1u, __ATOMIC_RELAXED);
            if (n < 8u) fprintf(stderr, "[be async] vbuf verify: backend buffer %u given to id %u is still id %u's\n", r, id, s_vb_rev[r]);
        }
        s_vb_rev[r] = id;
    }
}
static void vb_create_w(u32 id, u32 gen, const void* data, u32 bytes)
{
    if (id && id <= VB_MAX) {
        const u32 r = s_real.vbuf_create(s_real.user, data, bytes);
        vb_set_w(id, gen, r, bytes);
        if (!r) {
            __atomic_fetch_add(&s_vb_wfail, 1u, __ATOMIC_RELAXED);
            ba_vbw* v = &s_vbw[id]; v->failed = 1;
            if (s_vb_kept + bytes <= VB_KEEP_MAX && (v->copy = malloc(bytes)) != NULL) { memcpy(v->copy, data, bytes); s_vb_kept += bytes; }
        }
    }
    __atomic_fetch_add(&s_vb_wdone, 1ull, __ATOMIC_RELEASE);
}
static void vb_draw_w(rsx_topology t, u32 id, u32 vc, u32 stride, const u32* idx, u32 ic)   /* draw_vbuf, mapped */
{
    const ba_vbw* v = id && id <= VB_MAX ? &s_vbw[id] : NULL;
    if (v && v->h) { s_real.draw_vbuf(s_real.user, t, v->h, vc, stride, idx, ic); return; }
    if (v && v->copy && (unsigned long long)vc * stride <= v->bytes) {
        s_real.draw(s_real.user, t, v->copy, vc, stride, idx, idx ? ic : 0u);
        __atomic_fetch_add(&s_vb_wcopy, 1u, __ATOMIC_RELAXED); return; }
    __atomic_fetch_add(&s_vb_wdrop, 1u, __ATOMIC_RELAXED);   /* dead id (today: the backend skips a free number) */
}
static void vb_draw_ib_w(rsx_topology t, u32 id, u32 vc, u32 stride, u32 ib, u32 ic)   /* draw_vbuf_ib, mapped */
{
    if (!ic) return;   /* as vk_eng_draw_vbuf_ib */
    const ba_vbw* v = id && id <= VB_MAX ? &s_vbw[id] : NULL;
    const ba_vbw* i = ib && ib <= VB_MAX ? &s_vbw[ib] : NULL;
    if (v && v->h && i && i->h) { s_real.draw_vbuf_ib(s_real.user, t, v->h, vc, stride, i->h, ic); return; }
    if (i && !i->h && i->copy && (unsigned long long)ic * 4u <= i->bytes) { vb_draw_w(t, id, vc, stride, (const u32*)i->copy, ic); return; }
    __atomic_fetch_add(&s_vb_wdrop, 1u, __ATOMIC_RELAXED);   /* an id dead, or the vertices failed and the indices live only on the GPU */
}
static void vb_check_w(const u32* w)   /* verify: id gen bytes, ibuf igen ibytes */
{
    for (u32 k = 0; k < 2u; k++) {
        const u32 id = w[k * 3u], gen = w[k * 3u + 1u], need = w[k * 3u + 2u];
        if (k == 1u && !id) break;
        const ba_vbw* v = id && id <= VB_MAX ? &s_vbw[id] : NULL;
        if (v && (v->h || v->failed) && v->gen == gen && need <= v->bytes) continue;   /* failed: counted as such, order right */
        const unsigned n = __atomic_fetch_add(&s_vb_wbad, 1u, __ATOMIC_RELAXED);
        if (n < 8u) fprintf(stderr, "[be async] vbuf verify: draw %s id %u gen %u needs %u bytes; worker has %s gen %u, %u bytes\n",
                            k ? "index" : "vertex", id, gen, need, !v ? "no such id" : v->h ? "live" : v->failed ? "failed" : "dead",
                            v ? v->gen : 0u, v ? v->bytes : 0u);
        return;
    }
}
static u32 vb_number(void)   /* producer */
{
    u32 id = 0;
    if (s_vb_n < VB_MAX) id = ++s_vb_n;
    else if (s_vb_rn) { id = s_vb_ring[s_vb_rhead]; s_vb_rhead = (s_vb_rhead + 1u) % VB_MAX; s_vb_rn--; }
    if (id) { s_vb_live[id] = 1; s_vb_pgen[id]++; if (++s_vb_nlive > s_vb_nlive_max) s_vb_nlive_max = s_vb_nlive; }
    return id;
}
static void vb_unnumber(u32 id)   /* producer: its release is recorded (or its synchronous create failed) */
{
    s_vb_live[id] = 0; s_vb_nlive--;
    s_vb_ring[(s_vb_rhead + s_vb_rn) % VB_MAX] = id; s_vb_rn++;   /* at most VB_MAX ids are ever off the live set */
}
static void vb_check_put(u32 id, unsigned long long vbytes, u32 ib, unsigned long long ibytes)   /* producer, verify */
{
    u32* c = (u32*)ba_put(OP_VB_CHECK, 24);
    c[0] = id; c[1] = id && id <= VB_MAX ? s_vb_pgen[id] : 0u; c[2] = vbytes > 0xFFFFFFFFull ? 0xFFFFFFFFu : (u32)vbytes;
    c[3] = ib; c[4] = ib && ib <= VB_MAX ? s_vb_pgen[ib] : 0u; c[5] = ibytes > 0xFFFFFFFFull ? 0xFFFFFFFFu : (u32)ibytes;
}
static void vb_note_draw(u32 id)   /* producer */
{
    if (!id || id > VB_MAX || !s_vb_live[id]) { s_vb_deaddraw++; dd_reset(); }   /* perfstack: a dropped draw -> ba dedup forgets */
}

/* ba idx ref (2026-11-11; PS3_BA_IDX_REF, default 0 = off: every draw's indices are copied into the block as before).
 * ~80% of the console's draws (draw-fast / caster-fast replays, full-path idx memo hits) draw the indices of an idx memo
 * entry (rsx_draw_engine.c eng_im_entry.idx): a heap array that outlives the draw. Copying them into the block (~1.27 KB
 * a draw, ~10 MB a frame) is the largest single copy on the RSX thread, and the worker copies them again into the Vulkan
 * ring inside draw_vbuf (synchronously: vk_eng_draw_from), so it needs the array only until that op is replayed.
 *  - rsx_be_async_idxref_draw(): OP_DRAW_VBUF_REF {topology vbuf vcount stride icount verify, address} instead of
 *    OP_DRAW_VBUF + the indices, and *tk = the op's TICKET: the number its block will be sent with. ba_send_cur numbers
 *    blocks 1, 2, ... (s_ir_sent, producer); the worker publishes the number of the block it has just replayed
 *    (s_ir_done, release) and replays them in send order; the op sits in s_cur, which is the next block sent.
 *  - Invariant: an array named by a queued OP_DRAW_VBUF_REF with ticket t is neither written nor freed while
 *    s_ir_done < t. The engine keeps per memo entry the latest ticket of its array (tickets only grow) and, at the one
 *    place an entry's indices are rewritten (the idx memo store; nothing else writes, reallocs or frees them), asks
 *    rsx_be_async_idxref_busy(tk): busy -> a fresh array, and the old one goes to rsx_be_async_idxref_retire(p, tk)
 *    (freed here once s_ir_done >= tk); not busy -> every op that named it is replayed: rewritten in place as before.
 *  - The deferred list is capped (IR_DEFER_N entries / IR_DEFER_BYTES): over the cap the producer drains the worker
 *    (ba_drain: all replayed, s_ir_done == s_ir_sent) and frees it all; counted as a fallback. Swept at every retire,
 *    present and ba_drain.
 *  - PS3_BA_IDX_REF=2 (verify): the op also carries a copy of the indices; the worker compares the referenced array with
 *    it before the draw (a mismatch = the array changed or was freed between queueing and replay; the draw then uses the
 *    copy) and retired arrays are filled with 0xFF before free(), so a too-early free shows up as a mismatch.
 *    "[ba idxref]" every 300 presents: draws by reference, bytes not copied, deferred list now/peak, retired, fallbacks,
 *    worker checks / mismatches (must stay 0).
 * Only for the async proxy: rsx_be_async_idxref_mode() is 0 for any other table, and the engine then calls draw_vbuf
 * exactly as before. */
#define IR_DEFER_N 4096u
#define IR_DEFER_BYTES (32u << 20)
static int s_ir;                                          /* PS3_BA_IDX_REF (read once, before the worker exists) */
static unsigned long long s_ir_sent;                      /* producer: blocks sent */
static unsigned long long s_ir_done;                      /* atomic: the number of the last block the worker replayed */
typedef struct { void* p; unsigned long long tk; u32 bytes; } ir_def;
static ir_def s_ir_def[IR_DEFER_N];                       /* producer: arrays waiting for the worker */
static u32 s_ir_n, s_ir_peak;
static unsigned long long s_ir_bytes;
static unsigned long long s_ir_draws, s_ir_saved, s_ir_retired, s_ir_fb, s_ir_big;   /* producer stats */
static unsigned s_ir_vchk, s_ir_vbad;                     /* worker stats (atomic) */
static void ba_drain(void);
static void ir_free(void* p, u32 bytes)
{
    if (s_ir == 2 && bytes) memset(p, 0xFF, bytes);   /* verify: a read after this is a mismatch, not old bytes */
    free(p);
}
static void ir_sweep(void)   /* producer: free what the worker is past */
{
    if (!s_ir_n) return;
    const unsigned long long done = __atomic_load_n(&s_ir_done, __ATOMIC_ACQUIRE);
    u32 k = 0;
    for (u32 i = 0; i < s_ir_n; i++) {
        if (s_ir_def[i].tk <= done) { ir_free(s_ir_def[i].p, s_ir_def[i].bytes); s_ir_bytes -= s_ir_def[i].bytes; }
        else s_ir_def[k++] = s_ir_def[i];
    }
    s_ir_n = k;
}
int rsx_be_async_idxref_mode(const rsx_draw_backend* be);
int rsx_be_async_idxref_busy(unsigned long long tk);
void rsx_be_async_idxref_retire(void* p, u32 bytes, unsigned long long tk);
void rsx_be_async_idxref_fallback(void);
void rsx_be_async_idxref_draw(rsx_topology t, u32 vbuf, u32 vc, u32 stride, const u32* idx, u32 ic, unsigned long long* tk);
int rsx_be_async_replayop_mode(const rsx_draw_backend* be);
/* ba replay op: 1, 2 = PS3_BA_REPLAY_OP's working mode when `be` is this proxy; 0 otherwise. */
int rsx_be_async_replayop_mode(const rsx_draw_backend* be) { return be && be == &s_proxy ? g_rsx_ba_ro.mode : 0; }
/* 1, 2 = PS3_BA_IDX_REF when `be` is this proxy; 0 otherwise. */
int rsx_be_async_idxref_mode(const rsx_draw_backend* be) { return be && be == &s_proxy ? s_ir : 0; }
/* 1 = a draw queued with ticket tk may not have been replayed yet (its array must not be written or freed). */
int rsx_be_async_idxref_busy(unsigned long long tk) { return tk > __atomic_load_n(&s_ir_done, __ATOMIC_ACQUIRE); }
/* The engine is done with p (`bytes` long), last referenced with ticket tk: freed now or once the worker is past tk. */
void rsx_be_async_idxref_retire(void* p, u32 bytes, unsigned long long tk)
{
    if (!p) return;
    PROD_LOCK();
    s_ir_retired++;
    ir_sweep();
    if (rsx_be_async_idxref_busy(tk) && (s_ir_n >= IR_DEFER_N || s_ir_bytes + bytes > IR_DEFER_BYTES)) {
        s_ir_fb++; ba_drain();   /* over the cap: everything replayed (ba_drain sweeps the list) */
    }
    if (!rsx_be_async_idxref_busy(tk)) ir_free(p, bytes);
    else {
        s_ir_def[s_ir_n].p = p; s_ir_def[s_ir_n].tk = tk; s_ir_def[s_ir_n].bytes = bytes;
        s_ir_n++; s_ir_bytes += bytes;
        if (s_ir_n > s_ir_peak) s_ir_peak = s_ir_n;
    }
    PROD_UNLOCK();
}
void rsx_be_async_idxref_fallback(void) { PROD_LOCK(); s_ir_fb++; PROD_UNLOCK(); }   /* engine: no fresh array (copied instead) */
/* draw_vbuf with the indices referenced, not copied (rsx_draw_engine.c: idx memo arrays only). */
void rsx_be_async_idxref_draw(rsx_topology t, u32 vbuf, u32 vc, u32 stride, const u32* idx, u32 ic, unsigned long long* tk)
{
    if (!idx || !ic) { s_proxy.draw_vbuf(s_proxy.user, t, vbuf, vc, stride, idx, ic); return; }   /* nothing to reference */
    PROD_LOCK();
    if (s_vbasync) { vb_note_draw(vbuf); if (s_vbasync == 2) vb_check_put(vbuf, (unsigned long long)vc * stride, 0u, 0u); }   /* ba vbuf async (as px_draw_vbuf) */
    const unsigned long long ib = (unsigned long long)ic * 4u;
    const int copy = s_ir == 2 && 8ull + 32ull + ib + 7ull <= BA_BLOCK;   /* verify: the indices go along when they fit (ba_put's need) */
    if (s_ir == 2 && !copy) s_ir_big++;
    u8* a = (u8*)ba_put(OP_DRAW_VBUF_REF, 32u + (copy ? (u32)ib : 0u));   /* 40 bytes always fit a block */
    u32* w = (u32*)a; w[0] = (u32)t; w[1] = vbuf; w[2] = vc; w[3] = stride; w[4] = ic; w[5] = (u32)copy;
    memcpy(a + 24, &idx, sizeof idx);
    if (copy) memcpy(a + 32, idx, (size_t)ib);
    *tk = s_ir_sent + 1u;   /* s_cur holds the op: ba_send_cur gives it the next number */
    s_ir_draws++; s_ir_saved += ib;
    PROD_UNLOCK();
}

/* ba vs delta (2026-11-11; PS3_BA_VS_DELTA, default 0 = off: OP_VS_RANGE with the whole range, as before).
 * See rsx_vs_delta.h for the stale-row map and its writers.
 *  =1: px_vs_range queues OP_VS_DELTA {first count tail_bytes total nruns nrows full=0 draw#, tail, runs}: only the
 *      rows of the range whose stale bit is set (their bits cleared). The worker patches s_vs_rows with the runs and
 *      calls bind_vs_constants_range(s_vs_rows, first, count, tail...) exactly as for OP_VS_RANGE: the rows it
 *      passes are the bytes today's full copy would have put there (s_vs_rows is identical to today's, all 512 rows,
 *      at every replayed op -- rsx_vs_delta.h).
 *  =2 (verify): the op also carries the full range (full=1, before the tail). The worker applies the runs to its own
 *      shadow (s_vsd_shadow), compares the shadow's range with the full range byte for byte (and all 512 rows with
 *      s_vs_rows every 256th draw), counts a mismatching draw (first 8 logged: draw number, first differing row),
 *      then does exactly what OP_VS_RANGE does with the full range: the picture is today's.
 * Not queued (ok == 0, or no room: never for <= 8 KB + tail): the synchronous call as today, no bit cleared; the
 * worker's s_vs_rows is untouched by that path in every mode, so the map stays right.
 * Threads: the map is read/cleared here in px_vs_range and set by rsx_dispatch.c's writers. Both run inside the FIFO
 * walk (cellGcm_rsx_process_fifo holds s_gcm_fifo_lock; the engine's draws, replays included, are made from the
 * dispatch sink callbacks of that walk) on the one producer thread (PS3_BA_NOLOCK note above): no lock, no atomics.
 * px_init / px_shutdown mark all rows (same thread, nothing in flight that reads the map). s_vs_rows and
 * s_vsd_shadow are touched by ba_replay only (the worker; the synchronous paths pass the engine's array, never
 * s_vs_rows); the op's bytes reach the worker through the s_mu hand-off of its block, in queue order, which is
 * the order the bits were cleared in. "[ba vsdelta]" every 300 presents. */
static int s_vsd;                                         /* PS3_BA_VS_DELTA (read once in wrap, before the worker exists) */
static const void* s_vsd_rows;                            /* producer: the array the map describes */
static unsigned long long s_vsd_draws, s_vsd_fbytes, s_vsd_dbytes, s_vsd_rsent, s_vsd_fsends, s_vsd_drawno;   /* producer */
static unsigned s_vsd_vbad, s_vsd_vlog;                   /* worker, verify (atomic) */
static u8 s_vsd_shadow[512 * 16];                         /* worker, verify: what =1 would have in s_vs_rows */
static void vsd_replay(void* u, const u8* a)
{
    const u32* w = (const u32*)a;   /* first count tail_bytes total nruns nrows full draw# */
    const u32 first = w[0], count = w[1], tb = w[2], total = w[3], nruns = w[4], full = w[6];
    const u8* p = a + 32;
    const u8* fr = full ? p : NULL; p += full ? ALIGN8(count * 16u) : 0u;
    const u8* tail = p; p += ALIGN8(tb);
    if (!full) vsd_apply(s_vs_rows, p, nruns);
    else {
        vsd_apply(s_vsd_shadow, p, nruns);
        int bad = memcmp(s_vsd_shadow + first * 16u, fr, count * 16u) != 0;
        memcpy(s_vs_rows + first * 16u, fr, count * 16u);   /* OP_VS_RANGE */
        u32 row = first, all = 0;
        if (bad) { while (row < first + count && !memcmp(s_vsd_shadow + row * 16u, fr + (row - first) * 16u, 16u)) row++; }
        else if ((w[7] & 255u) == 0u && memcmp(s_vsd_shadow, s_vs_rows, sizeof s_vs_rows)) {   /* every 256th: all rows */
            bad = 1; all = 1; row = 0;
            while (row < 512u && !memcmp(s_vsd_shadow + row * 16u, s_vs_rows + row * 16u, 16u)) row++;
        }
        if (bad) {
            __atomic_fetch_add(&s_vsd_vbad, 1u, __ATOMIC_RELAXED);
            if (__atomic_fetch_add(&s_vsd_vlog, 1u, __ATOMIC_RELAXED) < 8u)
                fprintf(stderr, "[ba vsdelta] verify: MISMATCH draw %u row %u (range %u+%u%s, %u runs %u rows sent)\n",
                        w[7], row, first, count, all ? ", found outside the range" : "", nruns, w[5]);
        }
    }
    s_real.bind_vs_constants_range(u, s_vs_rows, first, count, tb ? tail : NULL, tb, total);
}

/* ---- worker ---- */
static void ba_replay(ba_block* b)
{
    u8* p = b->data; u8* end = b->data + b->used;
    void* const u = s_real.user;
    while (p < end) {
        const u32 op = ((u32*)p)[0] & ~BA_OP_DD, len = ((u32*)p)[1];
        u8* a = p + 8;
        if (s_dd == 2) dd_verify(op, ((u32*)p)[0] & BA_OP_DD, a, len);   /* ba dedup verify */
        switch (op) {
        case OP_BIND_TARGETS: { const u32* w = (const u32*)a; s_real.bind_targets(u, w + 2, w[0], w[1]); } break;
        case OP_BIND_PIPELINE: s_real.bind_pipeline(u, *(u32*)a); break;
        case OP_BIND_VS: { const u32 n = *(u32*)a; s_real.bind_vs_constants(u, n ? a + 8 : NULL, n); } break;
        case OP_BIND_PS: { const u32 n = *(u32*)a; s_real.bind_ps_constants(u, n ? a + 8 : NULL, n); } break;
        case OP_BIND_TEX: case OP_BIND_VTEX: {
            const u32 mask = ((u32*)a)[0], n = ((u32*)a)[1];
            const u32* tex = (const u32*)(a + 8);
            const rsx_be_sampler_desc* smp = (const rsx_be_sampler_desc*)(a + 8 + ALIGN8(n * 4u));
            if (op == OP_BIND_TEX) s_real.bind_textures(u, tex, smp, mask);
            else s_real.bind_vertex_textures(u, tex, smp, mask);
        } break;
        case OP_VIEWPORT: { const float* f = (const float*)a; s_real.set_viewport(u, f[0], f[1], f[2], f[3]); } break;
        case OP_SCISSOR: { const u32* w = (const u32*)a; s_real.set_scissor(u, w[0], w[1], w[2], w[3]); } break;
        case OP_STENCIL_REF: s_real.set_stencil_ref(u, *(u32*)a); break;
        case OP_DRAW: {
            const u32* w = (const u32*)a;   /* topology, vcount, stride, icount, vbytes */
            const u8* v = a + 24; const u32* idx = (const u32*)(v + ALIGN8(w[4]));
            s_real.draw(u, (rsx_topology)w[0], w[4] ? v : NULL, w[1], w[2], w[3] ? idx : NULL, w[3]);
        } break;
        case OP_DRAW_VBUF: {
            const u32* w = (const u32*)a;   /* topology, vbuf, vcount, stride, icount */
            if (s_vbasync) { vb_draw_w((rsx_topology)w[0], w[1], w[2], w[3], w[4] ? (const u32*)(a + 24) : NULL, w[4]); break; }   /* ba vbuf async */
            s_real.draw_vbuf(u, (rsx_topology)w[0], w[1], w[2], w[3], w[4] ? (const u32*)(a + 24) : NULL, w[4]);
        } break;
        case OP_DRAW_VBUF_REF: {   /* ba idx ref: topology vbuf vcount stride icount verify, the indices' address (+ a copy) */
            const u32* w = (const u32*)a; const u32* idx; memcpy(&idx, a + 24, sizeof idx);
            if (w[5]) {   /* verify */
                const u32* c = (const u32*)(a + 32);
                __atomic_fetch_add(&s_ir_vchk, 1u, __ATOMIC_RELAXED);
                if (memcmp(idx, c, (size_t)w[4] * 4u)) {
                    const unsigned n = __atomic_fetch_add(&s_ir_vbad, 1u, __ATOMIC_RELAXED);
                    if (n < 8u) fprintf(stderr, "[ba idxref] verify: MISMATCH %p, %u indices (vbuf %u): the array changed before its draw was replayed\n", (const void*)idx, w[4], w[1]);
                    idx = c;   /* draw what was queued */
                }
            }
            if (s_vbasync) { vb_draw_w((rsx_topology)w[0], w[1], w[2], w[3], idx, w[4]); break; }   /* ba vbuf async */
            s_real.draw_vbuf(u, (rsx_topology)w[0], w[1], w[2], w[3], idx, w[4]);
        } break;
        case OP_DRAW_VBUF_IB: { const u32* w = (const u32*)a;
            if (s_vbasync) { vb_draw_ib_w((rsx_topology)w[0], w[1], w[2], w[3], w[4], w[5]); break; }   /* ba vbuf async */
            s_real.draw_vbuf_ib(u, (rsx_topology)w[0], w[1], w[2], w[3], w[4], w[5]); } break;
        case OP_CLEAR_COLOR: { const u32 s = *(u32*)a; s_real.clear_color(u, s, (const float*)(a + 8)); } break;
        case OP_CLEAR_DS: { const u32* w = (const u32*)a; float d; memcpy(&d, w + 2, 4);
            s_real.clear_depth_stencil(u, w[0], w[1], d, (u8)w[3]); } break;
        case OP_VS_RANGE: {
            const u32* w = (const u32*)a;   /* first, count, tail_bytes, total_bytes */
            const u8* rows = a + 16; const u8* tail = rows + ALIGN8(w[1] * 16u);
            if (w[0] + w[1] <= 512u) memcpy(s_vs_rows + w[0] * 16u, rows, w[1] * 16u);
            s_real.bind_vs_constants_range(u, s_vs_rows, w[0], w[1], w[2] ? tail : NULL, w[2], w[3]);
        } break;
        case OP_VS_DELTA: vsd_replay(u, a); break;   /* ba vs delta */
        case OP_SET_HUD: { const u32* w = (const u32*)a; s_real.set_hud(u, (int)w[0], w[1]); } break;
        case OP_DEPTH_BIAS: { const float* f = (const float*)a; s_real.set_depth_bias(u, f[0], f[1]); } break;
        case OP_DEPTH_CLAMP: s_real.set_depth_clamp(u, *(int*)a); break;
        case OP_TEX_RELEASE: s_real.texture_release(u, *(u32*)a); break;
        case OP_CT_RELEASE: s_real.color_target_release(u, *(u32*)a); break;
        case OP_DT_RELEASE: s_real.depth_target_release(u, *(u32*)a); break;
        case OP_PIPE_RELEASE: s_real.pipeline_release(u, *(u32*)a); break;
        case OP_VBUF_RELEASE: if (s_vbasync) vb_release_w(*(u32*)a); else s_real.vbuf_release(u, *(u32*)a); break;   /* ba vbuf async: an id */
        case OP_VBUF_CREATE: { const u32* w = (const u32*)a; vb_create_w(w[0], w[2], a + 16, w[1]); } break;   /* ba vbuf async: id bytes gen 0, data */
        case OP_VB_CHECK: vb_check_w((const u32*)a); break;   /* ba vbuf async, verify */
        case OP_PRESENT: s_real.present(u, *(u32*)a); break;   /* be present async */
        case OP_TEX_UPLOAD: { const u32* w = (const u32*)a;   /* be async upload: t face mip w h rb rows, pixels */
            s_real.texture_upload(u, w[0], w[1], w[2], w[3], w[4], a + 32, w[5], w[6]); } break;
        case OP_CSNAP: { const u32* w = (const u32*)a;
            if (s_real.color_snapshot(u, w[0]) != w[1]) __atomic_fetch_add(&s_csnap_bad, 1, __ATOMIC_RELAXED); } break;
        case OP_OCCQ_BEGIN: s_real.occq_begin(u, *(u32*)a); break;   /* occ query: in stream order with the draws */
        case OP_OCCQ_END: s_real.occq_end(u); break;
        case OP_DD_MARK: break;   /* ba dedup verify: only dd_verify reads it */
        default: fprintf(stderr, "[be async] unknown op %u\n", op); return;
        }
        p += 8 + len;
    }
}

static void* ba_worker(void* arg)
{
    (void)arg;
    { extern void ps3_host_thread_label(const char*) __attribute__((weak)); if (ps3_host_thread_label) ps3_host_thread_label("be async"); }   /* ps5 pin: label = pin class */
    fprintf(stderr, "[be async] worker tid %ld\n", BA_TID());
    pthread_mutex_lock(&s_mu);
    for (;;) {
        while (!s_head) {
            if (s_ws_spin_us > 0 && ps3_ws_spin_begin(&s_ws_worker)) {   /* wake storm: the next block is usually ~50 us away */
                ps3_ws_clock c; int hit = 0;
                pthread_mutex_unlock(&s_mu);
                ps3_ws_clock_start(&c, s_ws_spin_us);
                do { if (__atomic_load_n(&s_head, __ATOMIC_ACQUIRE)) { hit = 1; break; } } while (ps3_ws_turn(&c));
                ps3_ws_spin_end(&s_ws_worker, hit);                      /* slot back before the lock */
                pthread_mutex_lock(&s_mu);
                if (s_head) break;                                       /* decided under s_mu, like the sleep */
            }
            s_waiting = 1; pthread_cond_wait(&s_cv_work, &s_mu); s_waiting = 0;   /* ba handoff: flag for the wake count */
        }
        ba_block* b = s_head; s_head = b->next; if (!s_head) s_tail = NULL;
        s_busy = 1;
        pthread_mutex_unlock(&s_mu);
        ba_replay(b);
        __atomic_store_n(&s_ir_done, b->seq, __ATOMIC_RELEASE);   /* ba idx ref: every array this block named is read */
        pthread_mutex_lock(&s_mu);
        s_busy = 0;
        b->next = s_free; s_free = b;
        if (!s_ws_lazy || s_done_waiters) pthread_cond_broadcast(&s_cv_done);   /* wake storm: only for a sleeper */
    }
    return NULL;
}

/* ---- producer side (s_prod held) ---- */
static void ba_send_cur(void)
{
    if (!s_cur || !s_cur->used) return;
    ba_block* b = s_cur; s_cur = NULL; b->next = NULL;
    b->seq = ++s_ir_sent;   /* ba idx ref: block number (tickets) */
    pthread_mutex_lock(&s_mu);
    if (s_tail) s_tail->next = b; else s_head = b;
    s_tail = b;
    s_n_blocks_sent++;
    s_ho_blocks++; if (s_waiting) s_ho_wakes++;   /* ba handoff: stats */
    if (!s_ws_lazy || s_waiting) pthread_cond_signal(&s_cv_work);   /* wake storm: only for a sleeping worker */
    pthread_mutex_unlock(&s_mu);
}

static void ba_new_cur(void)
{
    pthread_mutex_lock(&s_mu);
    while (!s_free && s_nblocks >= BA_BLOCKS) { s_done_waiters++; pthread_cond_wait(&s_cv_done, &s_mu); s_done_waiters--; }   /* wake storm: counted */
    ba_block* b = s_free;
    if (b) s_free = b->next;
    pthread_mutex_unlock(&s_mu);
    if (!b) { b = (ba_block*)malloc(sizeof *b); s_nblocks++; }
    b->next = NULL; b->used = 0; b->ops = 0;
    s_cur = b;
}

/* be present async limit (2026-11-11): producer-only state of the queued present (PS3_BA_PRESENT_ASYNC=1); all 0 off. */
static unsigned long long s_pa_seq;                 /* block number the last queued present went in (s_ir_sent) */
static int s_pa_first;                              /* 1 = no ba_drain since that present was queued */
static unsigned s_pa_n, s_pa_wait_n, s_pa_fd_n, s_pa_fd_busy;   /* per 300 frames: queued, waited for the one before, first drains */
static unsigned long long s_pa_wait_ns, s_pa_fd_ns;
static unsigned long long ba_ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (unsigned long long)t.tv_sec * 1000000000ull + (unsigned long long)t.tv_nsec; }

/* ba view direct (2026-11-11; PS3_BA_VIEW_DIRECT, default 0 = off: every surface_view miss drains as before).
 * The ~6-7 surface_view "waits" a frame are not waits: the proxy's view cache (s_vc) misses only right after a
 * synchronous call returned that handle and vc_forget()ed it -- the GPU depth->RGBA8 copy (a COLOR target of the
 * backend's dz cache, rsx_draw_engine.c eng_zdepth_snapshot_rgba8[_sized] -> surface_view at once), the GPU-light
 * output, the first colour snapshot of a surface. Console logs: FoB surface_view 5.93 / depth_rgba8 5.93 a frame,
 * if2 6.81 / 5.83. Nothing is queued between the two calls, so the view's ba_drain finds s_cur empty and the worker
 * idle and returns without waiting; it is counted all the same.
 *  - s_vd_quiet (producer): 1 = no op put since the last ba_drain completed. ba_put clears it; ba_drain sets it at
 *    its end (s_cur sent and empty, worker idle, s_ir_done == s_ir_sent). While it is 1, a ba_drain would only redo
 *    dd_reset (s_dd_valid is still 0: a dd_check record is always followed by a ba_put) and ir_sweep (nothing can be
 *    deferred while the worker is idle: rsx_be_async_idxref_busy is 0, retire frees at once).
 *  - =1: a surface_view miss while s_vd_quiet calls the backend directly on this thread (the worker is idle; the
 *    same call at the same point of the stream as today), not counted as a wait ("direct").
 *  - =2 (verify): the miss drains as today; the proxy first predicts "this drain is a no-op" from s_vd_quiet and
 *    ba_drain reports whether it sent a block or found the worker busy. Predicted no-op but work found = mismatch
 *    (counted, first 8 logged with the inputs).
 *  - =1 and =2: per wait kind, drains that found work (a block to send / the worker busy) and the time in ba_drain
 *    (the real RSX-thread cost of each wait kind: settles which waits are worth removing), and the first drain after
 *    a queued present (PS3_BA_PRESENT_ASYNC=1: how long the RSX thread still waits for that present).
 * No handle is predicted or invented: the engine and texguard see exactly the numbers they see today.
 * t35 stack: the direct call runs the backend on the RSX thread only while the worker has had nothing since a
 * completed drain (that drain's s_mu hand-off orders the worker's last freed-handle records before this thread's),
 * so the tg rebase freed-handle record keeps one writer at a time; px_surface_view reads that record (px_bf_drain)
 * before its cache lookup and so before this branch too. A queued present (PS3_BA_PRESENT_ASYNC) goes through
 * ba_put, so it clears s_vd_quiet: the direct path never overlaps a present the worker is replaying. */
static int s_vd = -1;                     /* PS3_BA_VIEW_DIRECT (read at first use) */
static int ba_vd(void) { if (__builtin_expect(s_vd < 0, 0)) { const char* e = getenv("PS3_BA_VIEW_DIRECT"); s_vd = e && (*e == '1' || *e == '2') ? *e - '0' : 0; } return s_vd; }
static int s_vd_quiet;                    /* producer: nothing put since the last completed drain */
static int s_drain_kind = SY_N;           /* producer: the SYNC_AT kind of the next ba_drain (SY_N = untagged) */
static int s_vd_worked;                   /* producer: the last ba_drain sent a block or found the worker busy */
static int s_vd_after_pres;               /* producer: a present was queued since the last drain */
static unsigned s_vd_direct, s_vd_vchk, s_vd_vbad, s_vd_pres_n;
static unsigned s_vd_dn[SY_N + 1], s_vd_dwork[SY_N + 1];
static unsigned long long s_vd_dns[SY_N + 1], s_vd_pres_ns;
#define vd_now ba_ns                      /* t35 stack: one CLOCK_MONOTONIC helper (view-direct.patch had its own copy) */

/* Everything queued replayed and the worker idle: the caller may use the backend itself. */
static void ba_drain(void)
{
    const unsigned long long pa_t0 = __builtin_expect(s_pa_first, 0) ? ba_ns() : 0ull;   /* be present async: first drain after it */
    int pa_busy = 0;
    const int vd_kind = s_drain_kind; s_drain_kind = SY_N;   /* ba view direct */
    unsigned long long vd_t0 = 0;
    if (__builtin_expect(ba_vd() != 0, 0)) {   /* ba view direct: did this drain have anything to do? */
        vd_t0 = vd_now();
        s_vd_worked = (s_cur && s_cur->used) || __atomic_load_n(&s_head, __ATOMIC_ACQUIRE) || __atomic_load_n(&s_busy, __ATOMIC_ACQUIRE);
    }
    dd_reset();   /* ba dedup: the caller now runs the backend itself */
    ba_send_cur();
    /* wake storm: the worker is usually done within ~30 us; look for that before parking (hint only, see above) */
    if (s_ws_spin_us > 0 && (__atomic_load_n(&s_head, __ATOMIC_ACQUIRE) || __atomic_load_n(&s_busy, __ATOMIC_ACQUIRE)) &&
        ps3_ws_spin_begin(&s_ws_drain)) {
        ps3_ws_clock c; int hit = 0;
        ps3_ws_clock_start(&c, s_ws_spin_us);
        do {
            if (!__atomic_load_n(&s_head, __ATOMIC_ACQUIRE) && !__atomic_load_n(&s_busy, __ATOMIC_ACQUIRE)) { hit = 1; break; }
        } while (ps3_ws_turn(&c));
        ps3_ws_spin_end(&s_ws_drain, hit);
    }
    pthread_mutex_lock(&s_mu);
    if (pa_t0) pa_busy = s_head || s_busy;
    const int vd_busy = (s_head != NULL) | (s_busy != 0);   /* ba view direct: exact, under s_mu */
    while (s_head || s_busy) { s_done_waiters++; pthread_cond_wait(&s_cv_done, &s_mu); s_done_waiters--; }   /* wake storm: counted */
    pthread_mutex_unlock(&s_mu);
    if (pa_t0) { s_pa_first = 0; s_pa_fd_n++; s_pa_fd_busy += (unsigned)pa_busy; s_pa_fd_ns += ba_ns() - pa_t0; }
    s_n_sync++;
    if (s_ir_n) ir_sweep();   /* ba idx ref: the worker is past everything */
    if (__builtin_expect(vd_t0 != 0, 0)) {   /* ba view direct: stats */
        const unsigned long long dt = vd_now() - vd_t0;
        s_vd_worked |= vd_busy;
        s_vd_dn[vd_kind]++; s_vd_dns[vd_kind] += dt; if (s_vd_worked) s_vd_dwork[vd_kind]++;
        if (s_vd_after_pres) { s_vd_pres_n++; s_vd_pres_ns += dt; }
    }
    s_vd_after_pres = 0;
    s_vd_quiet = 1;   /* ba view direct: s_cur empty, worker idle */
}

/* Room for one op with `bytes` of arguments; NULL when it can never fit (the caller then runs it sync). */
static void* ba_put(u32 op, u32 bytes)
{
    const u32 need = 8u + ALIGN8(bytes);
    if (need > BA_BLOCK) return NULL;
    if (s_cur && (s_cur->used + need > BA_BLOCK || s_cur->ops >= s_kick)) ba_send_cur();   /* ba handoff: s_kick */
    if (!s_cur) ba_new_cur();
    u32* h = (u32*)(s_cur->data + s_cur->used);
    h[0] = op; h[1] = ALIGN8(bytes);
    if (s_dd == 2 && (bytes & 7u)) memset((u8*)(h + 2) + bytes, 0, ALIGN8(bytes) - bytes);   /* ba dedup verify */
    s_cur->used += need; s_cur->ops++;
    s_n_ops++; s_ho_ops++;
    s_vd_quiet = 0;   /* ba view direct */
    return h + 2;
}

#define SYNC_BEGIN PROD_LOCK(); ba_drain();   /* ba handoff: PROD_LOCK */
#define SYNC_AT(k) s_sync_by[k]++; s_drain_kind = (k);   /* ba view direct: kind for the drain stats */
#define SYNC_END   PROD_UNLOCK();

/* ---- proxies: queued ---- */
static void px_bind_targets(void* user, const u32* surfaces, u32 count, u32 depth)
{ (void)user; PROD_LOCK();
  u32 op = OP_BIND_TARGETS;
  if (s_dd) { const u32 hd[2] = { count, depth };   /* ba dedup */
              const dd_piece pc[2] = { { hd, 8u }, { surfaces, count * 4u } };
              op = dd_op(op, DD_TARGETS, pc, 2); }
  if (!op) { PROD_UNLOCK(); return; }
  u32* w = (u32*)ba_put(op, 8u + count * 4u);
  if (w) { w[0] = count; w[1] = depth; if (count) memcpy(w + 2, surfaces, count * 4u); }
  else { ba_drain(); s_real.bind_targets(s_real.user, surfaces, count, depth); }
  PROD_UNLOCK(); }
static void px_bind_pipeline(void* user, u32 p)
{ (void)user; PROD_LOCK();
  u32 op = OP_BIND_PIPELINE;
  if (s_dd) { const dd_piece pc[1] = { { &p, 4u } }; op = dd_op(op, DD_PIPE, pc, 1); }   /* ba dedup */
  if (op) *(u32*)ba_put(op, 4) = p;
  PROD_UNLOCK(); }
static void px_bind_consts(u32 op, const void* data, u32 bytes)
{ PROD_LOCK();
  if (s_dd && op == OP_BIND_PS) {   /* ba dedup: fragment constants only (vertex constants change every draw) */
      const u32 n = data ? bytes : 0u;
      const dd_piece pc[2] = { { &n, 4u }, { data, n } };
      op = dd_op(op, DD_PS, pc, 2);
      if (!op) { PROD_UNLOCK(); return; }
  }
  u8* a = (u8*)ba_put(op, 8u + (data ? bytes : 0u));
  if (a) { const u32 n = data ? bytes : 0u; memcpy(a, &n, 4); if (s_dd == 2) memset(a + 4, 0, 4); if (n) memcpy(a + 8, data, n); }
  else { ba_drain(); if ((op & ~BA_OP_DD) == OP_BIND_VS) s_real.bind_vs_constants(s_real.user, data, bytes); else s_real.bind_ps_constants(s_real.user, data, bytes); }
  PROD_UNLOCK(); }
static void px_bind_vs(void* user, const void* d, u32 n) { (void)user; px_bind_consts(OP_BIND_VS, d, n); }
static void px_bind_ps(void* user, const void* d, u32 n) { (void)user; px_bind_consts(OP_BIND_PS, d, n); }
static void px_bind_tex_common(u32 op, const u32* tex, const rsx_be_sampler_desc* smp, u32 mask, u32 n)
{ PROD_LOCK();
  if (s_dd) {   /* ba dedup: the bytes queued below (NULL arrays go as zeros) */
      const u32 hd[2] = { mask, n };
      const dd_piece pc[3] = { { hd, 8u }, { tex, n * 4u }, { smp, n * (u32)sizeof(rsx_be_sampler_desc) } };
      op = dd_op(op, op == OP_BIND_TEX ? DD_TEX : DD_VTEX, pc, 3);
      if (!op) { PROD_UNLOCK(); return; }
  }
  u8* a = (u8*)ba_put(op, 8u + ALIGN8(n * 4u) + n * (u32)sizeof(rsx_be_sampler_desc));
  ((u32*)a)[0] = mask; ((u32*)a)[1] = n;
  if (tex) memcpy(a + 8, tex, n * 4u); else memset(a + 8, 0, n * 4u);
  if (smp) memcpy(a + 8 + ALIGN8(n * 4u), smp, n * sizeof(rsx_be_sampler_desc));
  else memset(a + 8 + ALIGN8(n * 4u), 0, n * sizeof(rsx_be_sampler_desc));
  PROD_UNLOCK(); }
static void px_bind_textures(void* user, const u32* t, const rsx_be_sampler_desc* s, u32 m)
{ (void)user; px_bind_tex_common(OP_BIND_TEX, t, s, m, RSX_BE_MAX_TEXTURES); }
static void px_bind_vtextures(void* user, const u32* t, const rsx_be_sampler_desc* s, u32 m)
{ (void)user; px_bind_tex_common(OP_BIND_VTEX, t, s, m, RSX_BE_MAX_VERTEX_TEXTURES); }
static void px_set_viewport(void* user, float x, float y, float w, float h)
{ (void)user; PROD_LOCK();
  u32 op = OP_VIEWPORT;
  if (s_dd) { const float v[4] = { x, y, w, h }; const dd_piece pc[1] = { { v, 16u } }; op = dd_op(op, DD_VP, pc, 1); }   /* ba dedup */
  if (op) { float* f = (float*)ba_put(op, 16); f[0] = x; f[1] = y; f[2] = w; f[3] = h; }
  PROD_UNLOCK(); }
static void px_set_scissor(void* user, u32 x, u32 y, u32 w, u32 h)
{ (void)user; PROD_LOCK();
  u32 op = OP_SCISSOR;
  if (s_dd) { const u32 v[4] = { x, y, w, h }; const dd_piece pc[1] = { { v, 16u } }; op = dd_op(op, DD_SC, pc, 1); }   /* ba dedup */
  if (op) { u32* a = (u32*)ba_put(op, 16); a[0] = x; a[1] = y; a[2] = w; a[3] = h; }
  PROD_UNLOCK(); }
static void px_set_stencil_ref(void* user, u32 r)
{ (void)user; PROD_LOCK();
  u32 op = OP_STENCIL_REF;
  if (s_dd) { const dd_piece pc[1] = { { &r, 4u } }; op = dd_op(op, DD_SREF, pc, 1); }   /* ba dedup */
  if (op) *(u32*)ba_put(op, 4) = r;
  PROD_UNLOCK(); }
static void px_draw(void* user, rsx_topology t, const void* v, u32 vc, u32 stride, const u32* idx, u32 ic)
{ (void)user; PROD_LOCK();
  const u32 vb = v ? vc * stride : 0u, ib = idx ? ic * 4u : 0u;
  u8* a = (u8*)ba_put(OP_DRAW, 24u + ALIGN8(vb) + ib);
  if (a) { u32* w = (u32*)a; w[0] = (u32)t; w[1] = vc; w[2] = stride; w[3] = idx ? ic : 0u; w[4] = vb;
           if (vb) memcpy(a + 24, v, vb); if (ib) memcpy(a + 24 + ALIGN8(vb), idx, ib);
           if (!idx && ic) w[3] = 0; }
  else { ba_drain(); s_real.draw(s_real.user, t, v, vc, stride, idx, ic); }
  PROD_UNLOCK(); }
static void px_draw_vbuf(void* user, rsx_topology t, u32 vbuf, u32 vc, u32 stride, const u32* idx, u32 ic)
{ (void)user; PROD_LOCK();
  const u32 ib = idx ? ic * 4u : 0u;
  if (s_vbasync) { vb_note_draw(vbuf); if (s_vbasync == 2) vb_check_put(vbuf, (unsigned long long)vc * stride, 0u, 0u); }   /* ba vbuf async */
  u8* a = (u8*)ba_put(OP_DRAW_VBUF, 24u + ib);
  if (a) { u32* w = (u32*)a; w[0] = (u32)t; w[1] = vbuf; w[2] = vc; w[3] = stride; w[4] = idx ? ic : 0u;
           if (ib) memcpy(a + 24, idx, ib); }
  else if (s_vbasync) { ba_drain(); vb_draw_w(t, vbuf, vc, stride, idx, ic); }   /* ba vbuf async: worker idle, the map is ours */
  else { ba_drain(); s_real.draw_vbuf(s_real.user, t, vbuf, vc, stride, idx, ic); }
  PROD_UNLOCK(); }
static void px_draw_vbuf_ib(void* user, rsx_topology t, u32 vbuf, u32 vc, u32 stride, u32 ibuf, u32 ic)
{ (void)user; PROD_LOCK();
  if (s_vbasync) { vb_note_draw(vbuf); vb_note_draw(ibuf);   /* ba vbuf async */
                   if (s_vbasync == 2) vb_check_put(vbuf, (unsigned long long)vc * stride, ibuf, (unsigned long long)ic * 4u); }
  u32* w = (u32*)ba_put(OP_DRAW_VBUF_IB, 24); w[0] = (u32)t; w[1] = vbuf; w[2] = vc; w[3] = stride; w[4] = ibuf; w[5] = ic;
  PROD_UNLOCK(); }
static void px_clear_color(void* user, u32 s, const float rgba[4])
{ (void)user; PROD_LOCK(); dd_reset(); u8* a = (u8*)ba_put(OP_CLEAR_COLOR, 24); memcpy(a, &s, 4); memcpy(a + 8, rgba, 16); PROD_UNLOCK(); }
static void px_clear_ds(void* user, u32 d, u32 flags, float dv, u8 st)
{ (void)user; PROD_LOCK(); dd_reset(); u32* w = (u32*)ba_put(OP_CLEAR_DS, 16); w[0] = d; w[1] = flags; memcpy(w + 2, &dv, 4); w[3] = st; PROD_UNLOCK(); }
static void px_vs_range(void* user, const void* rows, u32 first, u32 count, const void* tail, u32 tail_bytes, u32 total)
{ (void)user; PROD_LOCK();
  const int ok = rows && first <= 512u && count <= 512u - first && (tail || !tail_bytes);
  if (__builtin_expect(s_vsd && !g_rsx_vsd_track, 0)) {   /* ba vs delta: writers not marking (never: same env) -> full range */
      static int said; if (!said) { said = 1; fprintf(stderr, "[ba vsdelta] WARNING: mode %d but rsx_dispatch does not mark rows: full ranges sent\n", s_vsd); } }
  else if (s_vsd && ok) {   /* ba vs delta */
      if (__builtin_expect(rows != s_vsd_rows, 0)) { s_vsd_rows = rows; vsd_mark_all(g_rsx_vsd_stale); }   /* another array */
      u32 nrows, nruns;
      vsd_measure(g_rsx_vsd_stale, first, count, &nrows, &nruns);
      const u32 full = s_vsd == 2 ? ALIGN8(count * 16u) : 0u, pk = nruns * 4u + nrows * 16u;
      u8* d = (u8*)ba_put(OP_VS_DELTA, 32u + full + ALIGN8(tail_bytes) + pk);
      if (d) {
          u32* w = (u32*)d; w[0] = first; w[1] = count; w[2] = tail_bytes; w[3] = total; w[4] = nruns; w[5] = nrows;
          w[6] = s_vsd == 2; w[7] = (u32)s_vsd_drawno++;
          u8* q = d + 32;
          if (full) { memcpy(q, (const u8*)rows + first * 16u, count * 16u); q += full; }
          if (tail_bytes) memcpy(q, tail, tail_bytes);
          q += ALIGN8(tail_bytes);
          vsd_pack(g_rsx_vsd_stale, (const unsigned char*)rows, first, count, q);   /* writes pk bytes, clears their bits */
          s_vsd_draws++; s_vsd_fbytes += count * 16u; s_vsd_dbytes += pk; s_vsd_rsent += nrows;
          if (count && nrows == count) s_vsd_fsends++;
          PROD_UNLOCK(); return;
      }
  }
  u8* a = ok ? (u8*)ba_put(OP_VS_RANGE, 16u + ALIGN8(count * 16u) + tail_bytes) : NULL;
  if (a) { u32* w = (u32*)a; w[0] = first; w[1] = count; w[2] = tail_bytes; w[3] = total;
           memcpy(a + 16, (const u8*)rows + first * 16u, count * 16u);
           if (tail_bytes) memcpy(a + 16 + ALIGN8(count * 16u), tail, tail_bytes); }
  else { ba_drain(); s_real.bind_vs_constants_range(s_real.user, rows, first, count, tail, tail_bytes, total); }
  PROD_UNLOCK(); }
static void px_set_hud(void* user, int hud, u32 tw)
{ (void)user; PROD_LOCK(); dd_reset(); u32* w = (u32*)ba_put(OP_SET_HUD, 8); w[0] = (u32)hud; w[1] = tw; PROD_UNLOCK(); }
static void px_depth_bias(void* user, float c, float s)
{ (void)user; PROD_LOCK();
  u32 op = OP_DEPTH_BIAS;
  if (s_dd) { const float v[2] = { c, s }; const dd_piece pc[1] = { { v, 8u } }; op = dd_op(op, DD_ZBIAS, pc, 1); }   /* ba dedup */
  if (op) { float* f = (float*)ba_put(op, 8); f[0] = c; f[1] = s; }
  PROD_UNLOCK(); }
static void px_depth_clamp(void* user, int cl)
{ (void)user; PROD_LOCK();
  /* vk depth clamp: called before every draw; a reset here would void the dedup (and the replay-op epoch) per draw */
  u32 op = OP_DEPTH_CLAMP;
  if (s_dd) { const dd_piece pc[1] = { { &cl, 4u } }; op = dd_op(op, DD_ZCLAMP, pc, 1); }   /* ba dedup */
  if (op) *(int*)ba_put(op, 4) = cl;
  PROD_UNLOCK(); }
/* occ query: the begin/end of a sample count travel with the draws they bracket; the answer comes back through
 * rsx_draw_engine_occq_result from whichever thread runs the backend. */
static void px_occq_begin(void* user, u32 id)
{ (void)user; PROD_LOCK(); dd_reset(); *(u32*)ba_put(OP_OCCQ_BEGIN, 4) = id; PROD_UNLOCK(); }
static void px_occq_end(void* user)
{ (void)user; PROD_LOCK(); dd_reset(); *(u32*)ba_put(OP_OCCQ_END, 4) = 0u; PROD_UNLOCK(); }
static void vc_forget(u32 h);
static void cs_forget(u32 h);
#define PX_RELEASE(name, OPC) static void px_##name(void* user, u32 h) \
{ (void)user; PROD_LOCK(); dd_reset(); \
  if (OPC == OP_TEX_RELEASE || OPC == OP_CT_RELEASE) { vc_forget(h); cs_forget(h); } \
  *(u32*)ba_put(OPC, 4) = h; PROD_UNLOCK(); }
PX_RELEASE(texture_release, OP_TEX_RELEASE)
PX_RELEASE(color_target_release, OP_CT_RELEASE)
PX_RELEASE(depth_target_release, OP_DT_RELEASE)
PX_RELEASE(pipeline_release, OP_PIPE_RELEASE)
static void px_vbuf_release(void* user, u32 h)
{ (void)user; PROD_LOCK(); dd_reset();   /* ba dedup (was in PX_RELEASE) */
  if (!s_vbasync) *(u32*)ba_put(OP_VBUF_RELEASE, 4) = h;
  else if (h && h <= VB_MAX && s_vb_live[h]) { *(u32*)ba_put(OP_VBUF_RELEASE, 4) = h; vb_unnumber(h); }   /* ba vbuf async */
  else if (h) s_vb_deadrel++;   /* an id not out: today the backend ignores a free number or frees its new owner */
  PROD_UNLOCK(); }

/* ---- proxies: synchronous ---- */
static void vc_forget(u32 h);
static int px_init(void* user, u32 w, u32 h) { (void)user; SYNC_BEGIN int r = s_real.init(s_real.user, w, h); if (s_vsd) vsd_mark_all(g_rsx_vsd_stale); SYNC_END return r; }   /* ba vs delta */
static void px_shutdown(void* user) { (void)user; SYNC_BEGIN s_real.shutdown(s_real.user); if (s_vsd) vsd_mark_all(g_rsx_vsd_stale); SYNC_END }
static void px_submit_and_wait(void* user, u32 reason) { (void)user; SYNC_BEGIN s_real.submit_and_wait(s_real.user, reason); SYNC_END }
static u32 px_texture_create(void* user, rsx_be_format f, u32 w, u32 h, u32 mips, u32 faces, u32 remap, u32 rf)
{ (void)user; SYNC_AT(SY_TEXC) SYNC_BEGIN u32 r = s_real.texture_create(s_real.user, f, w, h, mips, faces, remap, rf); if (r) vc_forget(r); SYNC_END return r; }
/* be async upload: the pixels go into the queue (up to a block's room), so an upload no longer drains the
 * worker; larger ones still run in order after a drain. PS3RECOMP_BE_ASYNC_UPLOAD=0 = always sync. */
static void px_texture_upload(void* user, u32 t, u32 face, u32 mip, u32 w, u32 h, const void* src, u32 rb, u32 rows)
{
    (void)user;
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3RECOMP_BE_ASYNC_UPLOAD"); on = !(e && *e == '0'); }
    const unsigned long long bytes = (unsigned long long)rb * rows;
    if (on && src && rb && rows && bytes + 32u + 8u <= BA_BLOCK) {
        PROD_LOCK();
        dd_reset();   /* ba dedup */
        u8* a = (u8*)ba_put(OP_TEX_UPLOAD, 32u + (u32)bytes);
        if (a) {
            u32* w32 = (u32*)a; w32[0] = t; w32[1] = face; w32[2] = mip; w32[3] = w; w32[4] = h; w32[5] = rb; w32[6] = rows;
            memcpy(a + 32, src, (size_t)bytes);
            PROD_UNLOCK();
            return;
        }
        PROD_UNLOCK();
    }
    SYNC_AT(SY_TEXU) SYNC_BEGIN s_real.texture_upload(s_real.user, t, face, mip, w, h, src, rb, rows); SYNC_END
}
static u32 px_color_target_create(void* user, rsx_be_format f, u32 w, u32 h, const void* seed, u32 sr)
{ (void)user; SYNC_BEGIN u32 r = s_real.color_target_create(s_real.user, f, w, h, seed, sr); if (r) vc_forget(r); SYNC_END return r; }
/* A view is created once per (surface, remap, format) and kept until its surface goes (vk_eng_surface_view
 * returns the existing one), so a repeat request needs no wait: the handle is remembered here and forgotten
 * when the surface or the view is released. */
#define VC_N 4096u
static struct { u32 surface, remap, fmt, view, valid; } s_vc[VC_N];
#define CS_N 256u
static struct { u32 surface, snap; } s_cs[CS_N];   /* (declared with s_vc: px_bf_drain clears both, tg rebase) */   /* view 0 = "no view" (a snapshot texture) */
static u32 vc_slot(u32 s, u32 remap, u32 fmt) { return ((s * 2654435761u) ^ (remap * 40503u) ^ (fmt * 97u)) & (VC_N - 1u); }
static void vc_forget(u32 h)
{ for (u32 i = 0; i < VC_N; i++) if (s_vc[i].valid && (s_vc[i].surface == h || (s_vc[i].view && s_vc[i].view == h))) s_vc[i].valid = 0; }
/* tg rebase: the backend also frees views and copies the engine never released (a depth->RGBA8 copy evicted, a light
 * output remade, the views of a target that went with it); their numbers come back for other objects, and a view
 * remembered here under such a number named a dead slot or someone else's view. The proxy reads the backend's
 * freed-handle record (rsx_be_freed_poll, its own cursor) before it answers from s_vc / s_cs, and forgets each freed
 * number as a surface, a view or a copy. Producer only (PROD_LOCK held). PS3RECOMP_ENG_FREED_NOTE=1 (t35b: default 0):
 * read; unset / 0: nothing is recorded (rsx_be_note_freed) and this returns at once. */
static u32 s_bf_cur; static int s_bf_on = -1;
static unsigned s_bf_forgot, s_bf_lost;
static void cs_forget(u32 h);
static int px_bf_on(void)
{
    if (__builtin_expect(s_bf_on < 0, 0)) {
        const char* e = getenv("PS3RECOMP_ENG_FREED_NOTE"); s_bf_on = e && *e == '1';   /* t35b: as eng_bf_on */
        s_bf_cur = rsx_be_freed_cursor();
    }
    return s_bf_on;
}
static void px_bf_drain(void)
{
    if (!px_bf_on() || s_bf_cur == rsx_be_freed_cursor()) return;
    for (;;) {
        u32 buf[64];
        const u32 n = rsx_be_freed_poll(&s_bf_cur, buf, 64u);
        if (!n) break;
        if (n == RSX_BE_FREED_LOST) { memset(s_vc, 0, sizeof s_vc); memset(s_cs, 0, sizeof s_cs); s_bf_lost++; continue; }
        for (u32 i = 0; i < n; i++) { vc_forget(buf[i]); cs_forget(buf[i]); s_bf_forgot++; }
    }
}
static u32 px_surface_view(void* user, u32 s, u32 remap, u32 rf)
{ (void)user;
  PROD_LOCK();
  px_bf_drain();   /* tg rebase (before the cache answers AND before the view-direct call below) */
  u32 k = vc_slot(s, remap, rf);
  if (s_vc[k].valid && s_vc[k].surface == s && s_vc[k].remap == remap && s_vc[k].fmt == rf) { const u32 v = s_vc[k].view; PROD_UNLOCK(); return v; }
  const int vd = ba_vd(), vd_pred = s_vd_quiet;   /* ba view direct */
  if (vd == 1 && vd_pred) {   /* nothing queued since the last drain: worker idle, the drain would do nothing */
      s_vd_direct++;
      const u32 r = s_real.surface_view(s_real.user, s, remap, rf);
      s_vc[k].surface = s; s_vc[k].remap = remap; s_vc[k].fmt = rf; s_vc[k].view = r; s_vc[k].valid = 1;
      PROD_UNLOCK(); return r; }
  PROD_UNLOCK();
  SYNC_AT(SY_VIEW) SYNC_BEGIN
  if (vd == 2 && vd_pred) {   /* ba view direct verify: the drain was predicted to be a no-op */
      s_vd_vchk++;
      if (s_vd_worked && s_vd_vbad++ < 8u)
          fprintf(stderr, "[be async] view direct verify: surface %u remap 0x%04X fmt 0x%02X: predicted an idle queue, the drain found work\n", s, remap, rf); }
  u32 r = s_real.surface_view(s_real.user, s, remap, rf);
  s_vc[k].surface = s; s_vc[k].remap = remap; s_vc[k].fmt = rf; s_vc[k].view = r; s_vc[k].valid = 1;
  SYNC_END return r; }
static u32 px_depth_target_create(void* user, u32 w, u32 h)
{ (void)user; SYNC_BEGIN u32 r = s_real.depth_target_create(s_real.user, w, h); if (r) vc_forget(r); SYNC_END return r; }
static u32 px_depth_snapshot(void* user, u32 d, u32 w, u32 h)
{ (void)user; SYNC_AT(SY_ZSNAP) SYNC_BEGIN u32 r = s_real.depth_snapshot(s_real.user, d, w, h); if (r) vc_forget(r); SYNC_END return r; }
/* A colour snapshot is the surface's one copy texture (vk_eng_snap2: kept per surface while its size stays,
 * which a surface's does), refilled on each request at that point of the command stream. After the first
 * request the handle is known, so a repeat only queues the refill: the decals' read-modify-write copies
 * (~200+ a heavy inFAMOUS 1 frame) no longer stop the queue. Forgotten when the surface goes. */
static void cs_forget(u32 h)
{ for (u32 i = 0; i < CS_N; i++) if (s_cs[i].snap && (s_cs[i].surface == h || s_cs[i].snap == h)) s_cs[i].snap = 0; }
static u32 px_color_snapshot(void* user, u32 s)
{ (void)user;
  PROD_LOCK();
  px_bf_drain();   /* tg rebase */
  const u32 k = (s * 2654435761u) & (CS_N - 1u);
  if (s_cs[k].snap && s_cs[k].surface == s) {
      dd_reset();   /* ba dedup */
      u32* w = (u32*)ba_put(OP_CSNAP, 8); w[0] = s; w[1] = s_cs[k].snap; s_csnap_q++;
      const u32 r = s_cs[k].snap; PROD_UNLOCK(); return r; }
  PROD_UNLOCK();
  SYNC_AT(SY_SNAP) SYNC_BEGIN u32 r = s_real.color_snapshot(s_real.user, s);
  if (r) { vc_forget(r); s_cs[k].surface = s; s_cs[k].snap = r; }
  SYNC_END return r; }
static u32 px_depth_snapshot_rgba8(void* user, u32 d, u32 w, u32 h)
{ (void)user; SYNC_AT(SY_ZRGBA) SYNC_BEGIN u32 r = s_real.depth_snapshot_rgba8(s_real.user, d, w, h); if (r) vc_forget(r); SYNC_END return r; }
static u32 px_pipeline_create(void* user, const char* vs, const char* ps, const rsx_be_render_state* rs,
                              const rsx_vertex_layout_plan* layout, u32 stride, rsx_be_format rt, u32 rtc)
{ (void)user; SYNC_AT(SY_PIPE) SYNC_BEGIN u32 r = s_real.pipeline_create(s_real.user, vs, ps, rs, layout, stride, rt, rtc); SYNC_END return r; }
void rsx_be_async_stats(void);
/* be present async (2026-11-10): PS3_BA_PRESENT_ASYNC=1 queues the present as a worker op instead of draining the
 * worker and presenting on the RSX thread (~1.7 ms/frame of the RSX thread in inFAMOUS 2), so the RSX thread goes on
 * with the next frame's FIFO. The worker runs ops in order, so recording after the present follows it as before.
 * be present async limit (2026-11-11): at most ONE present queued and not yet replayed. Before queuing present N the
 * RSX thread waits until the worker has replayed the block holding present N-1 (s_ir_done, published after each block;
 * the s_cv_done broadcast follows under s_mu, as ba_drain relies on). Without it nothing but the 48-block budget bounded
 * the run-ahead: the boot presents (main.cpp, every 1 ms pass before the first flip) and light frames with no
 * synchronous call queue presents faster than a FIFO swapchain shows them (30 real a second with frame generation),
 * i.e. up to ~48 frames of picture and input lag, while the guest's flips complete at queue time. Today's sync present
 * held the RSX thread in the acquire instead. In heavy frames a synchronous call has drained the worker long before. */
static int ba_present_async(void) { static int v = -1; if (v < 0) { const char* e = getenv("PS3_BA_PRESENT_ASYNC"); v = e && *e == '1'; } return v; }
static void px_present(void* user, u32 s)
{ (void)user;
  if (ba_present_async()) { PROD_LOCK();
      if (s_pa_seq && __atomic_load_n(&s_ir_done, __ATOMIC_ACQUIRE) < s_pa_seq) {   /* the previous present still queued */
          const unsigned long long t0 = ba_ns();
          pthread_mutex_lock(&s_mu);
          while (__atomic_load_n(&s_ir_done, __ATOMIC_ACQUIRE) < s_pa_seq) { s_done_waiters++; pthread_cond_wait(&s_cv_done, &s_mu); s_done_waiters--; }
          pthread_mutex_unlock(&s_mu);
          s_pa_wait_n++; s_pa_wait_ns += ba_ns() - t0;
      }
      dd_reset(); *(u32*)ba_put(OP_PRESENT, 4) = s; ba_send_cur();
      s_pa_seq = s_ir_sent; s_pa_first = 1; s_pa_n++;   /* the block just sent holds it, as its last op */
      s_vd_after_pres = 1;   /* ba view direct */
      PROD_UNLOCK(); }
  else { SYNC_AT(SY_PRESENT) SYNC_BEGIN s_real.present(s_real.user, s); SYNC_END }
  if (s_ho_stats) {   /* ba handoff: counter line */
      static unsigned hn; static unsigned long long o0, b0, w0;
      if (++hn % 600u == 0) {
          pthread_mutex_lock(&s_mu); const unsigned long long b = s_ho_blocks, w = s_ho_wakes; pthread_mutex_unlock(&s_mu);
          const unsigned long long o = s_ho_ops;
          fprintf(stderr, "[ba handoff] kick %u nolock %d: %llu ops, %llu blocks, %llu wakes per 600 frames (%.0f / %.1f / %.1f a frame), producer changes %u, lock back on %d (hand-over %s, %llu us)\n",
                  s_kick, s_nolock, o - o0, b - b0, w - w0, (double)(o - o0) / 600.0, (double)(b - b0) / 600.0, (double)(w - w0) / 600.0, s_owner_changes,
                  __atomic_load_n(&s_ba_lockreq, __ATOMIC_RELAXED), !__atomic_load_n(&s_ba_hodone, __ATOMIC_ACQUIRE) ? "-" : s_ba_ho_how == 1 ? "acknowledged" : "owner idle", s_ba_ho_us);
          o0 = o; b0 = b; w0 = w;
      } }
  static unsigned n; if (++n % 300u == 0) { fprintf(stderr, "[be async] rsx tid %ld: ", BA_TID()); rsx_be_async_stats();
      if (g_rsx_ba_ro.mode) {   /* ba replay op: per 300 presents (counted by the engine's replays) */
          rsx_ba_ro* const ro = &g_rsx_ba_ro;
          char rm[48]; rm[0] = 0;
          if (ro->mode == 2) snprintf(rm, sizeof rm, " not_dropped %llu", ro->miss);
          fprintf(stderr, "[ba replayop] mode %d: replays %llu skipped_sets %llu calls_saved %llu%s\n", ro->mode, ro->replays, ro->sets, ro->saved, rm);
          ro->replays = ro->sets = ro->saved = ro->miss = 0;
      }
      if (s_dd) {   /* ba dedup: per 300 presents */
          fprintf(stderr, "[ba dedup] mode %d: %llu of %llu state ops %s; worker verify %u checked, %u mismatched\n", s_dd,
                  s_dd_skip, s_dd_seen, s_dd == 1 ? "skipped" : "would be skipped",
                  __atomic_exchange_n(&s_dd_vchk, 0u, __ATOMIC_RELAXED), __atomic_exchange_n(&s_dd_vbad, 0u, __ATOMIC_RELAXED));
          s_dd_skip = s_dd_seen = 0;
      }
      if (s_vsd) {   /* ba vs delta: per 300 presents (bytes = row bytes: today's range copy vs runs + changed rows) */
          PROD_LOCK();
          char vm[64]; vm[0] = 0;
          if (s_vsd == 2) snprintf(vm, sizeof vm, " mismatches %u", __atomic_exchange_n(&s_vsd_vbad, 0u, __ATOMIC_RELAXED));
          fprintf(stderr, "[ba vsdelta] mode %d: draws %llu full_bytes %llu delta_bytes %llu rows_sent %llu full_sends %llu%s\n",
                  s_vsd, s_vsd_draws, s_vsd_fbytes, s_vsd_dbytes, s_vsd_rsent, s_vsd_fsends, vm);
          s_vsd_draws = s_vsd_fbytes = s_vsd_dbytes = s_vsd_rsent = s_vsd_fsends = 0;
          PROD_UNLOCK();
      }
      if (s_ir) {   /* ba idx ref: per 300 presents (the list and its peak: now / since the last line) */
          PROD_LOCK();
          fprintf(stderr, "[ba idxref] mode %d: %llu draws by reference, %.1f MB %s; deferred frees %u now (peak %u, %.2f MB), retired %llu, fallbacks %llu;"
                  " worker verify %u checked, %u mismatched%s\n", s_ir, s_ir_draws, s_ir_saved / 1e6, s_ir == 1 ? "not copied" : "would not be copied",
                  s_ir_n, s_ir_peak, s_ir_bytes / 1e6, s_ir_retired, s_ir_fb,
                  __atomic_exchange_n(&s_ir_vchk, 0u, __ATOMIC_RELAXED), __atomic_exchange_n(&s_ir_vbad, 0u, __ATOMIC_RELAXED),
                  s_ir_big ? " (some too big to check)" : "");
          s_ir_draws = s_ir_saved = s_ir_retired = s_ir_fb = s_ir_big = 0; s_ir_peak = s_ir_n;
          PROD_UNLOCK();
      } }
  if (s_ir_n) { PROD_LOCK(); ir_sweep(); PROD_UNLOCK(); }   /* ba idx ref: once a frame */
}
static void px_readback(void* user, u32 s, u32 x, u32 y, u32 w, u32 h, void* out, u32 op)
{ (void)user; SYNC_BEGIN s_real.readback(s_real.user, s, x, y, w, h, out, op); SYNC_END }
static u32 px_texture_create_3d(void* user, rsx_be_format f, u32 w, u32 h, u32 d, u32 mips, u32 remap, u32 rf)
{ (void)user; SYNC_AT(SY_TEXC) SYNC_BEGIN u32 r = s_real.texture_create_3d(s_real.user, f, w, h, d, mips, remap, rf); if (r) vc_forget(r); SYNC_END return r; }
static void px_texture_upload_3d(void* user, u32 t, u32 z, u32 mip, u32 w, u32 h, const void* src, u32 rb)
{ (void)user; SYNC_AT(SY_TEXU) SYNC_BEGIN s_real.texture_upload_3d(s_real.user, t, z, mip, w, h, src, rb); SYNC_END }
static u32 px_light_pass(void* user, u32 n, u32 d, u32 w, u32 h, const void* p, u32 pb, u32* spec)
{ (void)user; SYNC_BEGIN u32 r = s_real.light_pass(s_real.user, n, d, w, h, p, pb, spec); if (r) vc_forget(r);
  if (r && spec && *spec && px_bf_on()) vc_forget(*spec);   /* tg rebase: the specular target is handed back too (surface_view'd by the engine); t35b: with FREED_NOTE */
  SYNC_END return r; }
static u32 px_ssao_pass(void* user, u32 d, u32 n, const void* c, u32 cb, u32 fw, u32 fh, u32 hw, u32 hh)
{ (void)user; SYNC_BEGIN u32 r = s_real.ssao_pass(s_real.user, d, n, c, cb, fw, fh, hw, hh); if (r) vc_forget(r); SYNC_END return r; }
static u32 px_vbuf_create(void* user, const void* data, u32 bytes)
{ (void)user;
  if (s_vbasync) {   /* ba vbuf async */
      if (!data || !bytes) return 0;   /* what the backend answers */
      PROD_LOCK();
      const unsigned wf = __atomic_load_n(&s_vb_wfail, __ATOMIC_RELAXED);
      if (wf != s_vb_wfail_seen) { s_vb_wfail_seen = wf; s_vb_sync_left = 600u; }   /* the engine gets its 0s for a while */
      const int fits = bytes <= BA_BLOCK - 64u;   /* 8 + ALIGN8(16 + bytes) <= BA_BLOCK: ba_put can not refuse it */
      const u32 id = (!s_vb_sync_left && fits) ? vb_number() : 0u;
      if (id) {
          dd_reset();   /* perfstack: ba dedup forgets at a queued create (the worker's verify resets at it too) */
          u32* w = (u32*)ba_put(OP_VBUF_CREATE, 16u + bytes);
          w[0] = id; w[1] = bytes; w[2] = s_vb_pgen[id]; w[3] = 0u; memcpy(w + 4, data, bytes);
          s_vbq++; s_vb_qbytes += bytes; s_vb_qn++;
          const unsigned long long infl = s_vb_qn - __atomic_load_n(&s_vb_wdone, __ATOMIC_ACQUIRE);
          if (infl > s_vb_infl_max) s_vb_infl_max = (u32)infl;
          PROD_UNLOCK(); return id;
      }
      if (!s_vb_sync_left && fits) s_vbnoid++;
      PROD_UNLOCK();
      SYNC_AT(SY_VBUF) SYNC_BEGIN
      if (s_vb_sync_left) { s_vb_sync_left--; s_vbsync++; } else if (!fits) s_vbbig++;
      u32 h = vb_number();   /* worker drained: the id map is the producer's until the next hand-off (s_mu) */
      if (h) { const u32 r = s_real.vbuf_create(s_real.user, data, bytes);
               if (r) vb_set_w(h, s_vb_pgen[h], r, bytes); else { vb_unnumber(h); h = 0; } }
      s_vb_qn++; __atomic_fetch_add(&s_vb_wdone, 1ull, __ATOMIC_RELEASE);
      SYNC_END return h;
  }
  SYNC_AT(SY_VBUF) SYNC_BEGIN u32 r = s_real.vbuf_create(s_real.user, data, bytes); SYNC_END return r; }
static int px_image_load(void* user, const char* path, u8** rgba, u32* w, u32* h)
{ (void)user; SYNC_BEGIN int r = s_real.image_load(s_real.user, path, rgba, w, h); SYNC_END return r; }
static int px_image_save(void* user, const char* path, const u8* rgba, u32 w, u32 h, u32 rb)
{ (void)user; SYNC_BEGIN int r = s_real.image_save(s_real.user, path, rgba, w, h, rb); SYNC_END return r; }

const rsx_draw_backend* rsx_be_async_wrap(const rsx_draw_backend* real)
{
    if (!real) return real;
    const char* e = getenv("PS3RECOMP_BE_ASYNC");
    if (!(e && *e == '1')) return real;
    s_real = *real;
    {   /* ba handoff: switches (read once, before the worker exists) */
        const char* k = getenv("PS3_BA_KICK"); const char* nl = getenv("PS3_BA_NOLOCK");
        if (k && *k) { long v = strtol(k, NULL, 0); if (v < 1) v = 1; if (v > (1l << 20)) v = 1l << 20; s_kick = (u32)v; s_ho_stats = 1; }
        if (nl && *nl == '1') { s_nolock = 1; s_ho_stats = 1; }
        if (s_ho_stats) fprintf(stderr, "[ba handoff] kick %u ops a block, producer lock %s\n", s_kick, s_nolock ? "off (single producer)" : "on");
    }
    {   /* ba dedup: read once, before the worker exists (the worker reads s_dd too) */
        const char* d = getenv("PS3_BA_DEDUP");
        s_dd = d ? atoi(d) : 0;
        if (s_dd < 0 || s_dd > 2) s_dd = 0;
        if (s_dd) fprintf(stderr, "[ba dedup] mode %d: repeated state calls %s\n", s_dd, s_dd == 1 ? "not queued" : "queued and checked on the worker");
    }
    {   /* ba vbuf async (read once, before the worker exists) */
        const char* vb = getenv("PS3_BA_VBUF_ASYNC");
        if (vb && (*vb == '1' || *vb == '2') && s_real.vbuf_create && s_real.vbuf_release && s_real.draw_vbuf && s_real.draw) {
            s_vbw = (ba_vbw*)calloc(VB_MAX + 1u, sizeof *s_vbw);
            s_vb_ring = (u32*)calloc(VB_MAX, sizeof *s_vb_ring);
            s_vb_live = (u8*)calloc(VB_MAX + 1u, 1);
            s_vb_pgen = (u32*)calloc(VB_MAX + 1u, sizeof *s_vb_pgen);
            if (*vb == '2') s_vb_rev = (u32*)calloc(VB_MAX + 1u, sizeof *s_vb_rev);
            s_vbasync = (s_vbw && s_vb_ring && s_vb_live && s_vb_pgen && (*vb != '2' || s_vb_rev)) ? *vb - '0' : 0;
            fprintf(stderr, "[be async] vbuf async: %s (PS3_BA_VBUF_ASYNC=%c): vertex buffers numbered here, created in order on the worker\n",
                    s_vbasync == 2 ? "on, verify" : s_vbasync ? "on" : "no memory, off", *vb);
        }
    }
    {   /* ba replay op (read once here, the proxy's first use: getenv, not a knob -- the PS5 sets the env in main()) */
        const char* ro = getenv("PS3_BA_REPLAY_OP");
        int m = ro && (*ro == '1' || *ro == '2') && !ro[1] ? *ro - '0' : 0;
        if (m && !s_dd) m = 0;          /* nothing is dropped: nothing to skip */
        if (m == 1 && s_dd == 2) m = 2; /* dedup verify queues every call: skipping would change the worker's stream */
        u32 need = 0;
        if (s_real.bind_targets) need |= 1u << DD_TARGETS;   if (s_real.bind_pipeline) need |= 1u << DD_PIPE;
        if (s_real.bind_ps_constants) need |= 1u << DD_PS;   if (s_real.bind_textures) need |= 1u << DD_TEX;
        if (s_real.bind_vertex_textures) need |= 1u << DD_VTEX; if (s_real.set_viewport) need |= 1u << DD_VP;
        if (s_real.set_scissor) need |= 1u << DD_SC;         if (s_real.set_stencil_ref) need |= 1u << DD_SREF;
        if (s_real.set_depth_bias) need |= 1u << DD_ZBIAS;
        g_rsx_ba_ro.need = need; g_rsx_ba_ro.mode = m;
        if (ro && *ro && *ro != '0')
            fprintf(stderr, "[ba replayop] mode %d (PS3_BA_REPLAY_OP=%s, dedup %d): %s\n", m, ro, s_dd,
                    m == 1 ? "replays with an unchanged state epoch skip their state calls" : m == 2 ? "replays make every call; the ones the epoch would skip must be dropped" :
                    "off (needs PS3_BA_DEDUP=1/2)");
    }
    {   /* ba idx ref (read once, before the worker exists) */
        const char* ir = getenv("PS3_BA_IDX_REF");
        s_ir = ir ? atoi(ir) : 0;
        if (s_ir < 0 || s_ir > 2 || !s_real.draw_vbuf) s_ir = 0;
        if (s_ir) fprintf(stderr, "[ba idxref] mode %d: idx memo indices %s\n", s_ir, s_ir == 1 ? "queued by reference" : "queued by reference and as a copy, compared on the worker");
    }
    {   /* ba vs delta (read once, before the worker exists; getenv here, not a knob: the PS5 sets the env in main()) */
        const char* vd = getenv("PS3_BA_VS_DELTA");
        s_vsd = vd && (*vd == '1' || *vd == '2') && !vd[1] && s_real.bind_vs_constants_range ? *vd - '0' : 0;
        if (s_vsd) {
            vsd_mark_all(g_rsx_vsd_stale);   /* rsx_dispatch.c marks every changed row, in every mode */
            fprintf(stderr, "[ba vsdelta] mode %d: vertex constants %s\n", s_vsd,
                    s_vsd == 1 ? "queued as changed rows only" : "queued in full and as changed rows, rebuilt and compared on the worker");
        }
    }
    if (ps3_ws_on() > 0) {   /* wake storm: switches (read once, before the worker exists) */
        const char* sp = getenv("PS3_BA_SPIN_US");
        s_ws_lazy = ps3_ws_lazy();
        s_ws_spin_us = sp ? (int)ps3_ws_clamp_us(atoi(sp)) : 0;
        s_ho_stats = 1;
        fprintf(stderr, "[wake storm] be async: signals for nobody %s, spin before a sleep %d us\n",
                s_ws_lazy ? "skipped" : "kept", s_ws_spin_us);
    }
    rsx_draw_backend p;
    memset(&p, 0, sizeof p);
    p.user = &s_proxy;
#define PX(f, fn) if (s_real.f) p.f = fn
    PX(init, px_init); PX(shutdown, px_shutdown); PX(submit_and_wait, px_submit_and_wait);
    PX(texture_create, px_texture_create); PX(texture_upload, px_texture_upload); PX(texture_release, px_texture_release);
    PX(color_target_create, px_color_target_create); PX(color_target_release, px_color_target_release);
    PX(surface_view, px_surface_view); PX(depth_target_create, px_depth_target_create);
    PX(depth_target_release, px_depth_target_release); PX(depth_snapshot, px_depth_snapshot);
    PX(color_snapshot, px_color_snapshot); PX(depth_snapshot_rgba8, px_depth_snapshot_rgba8);
    PX(pipeline_create, px_pipeline_create); PX(pipeline_release, px_pipeline_release);
    PX(bind_targets, px_bind_targets); PX(bind_pipeline, px_bind_pipeline);
    PX(bind_vs_constants, px_bind_vs); PX(bind_ps_constants, px_bind_ps);
    PX(bind_textures, px_bind_textures); PX(bind_vertex_textures, px_bind_vtextures);
    PX(set_viewport, px_set_viewport); PX(set_scissor, px_set_scissor); PX(set_stencil_ref, px_set_stencil_ref);
    PX(draw, px_draw); PX(clear_color, px_clear_color); PX(clear_depth_stencil, px_clear_ds);
    PX(present, px_present); PX(readback, px_readback); PX(bind_vs_constants_range, px_vs_range);
    PX(texture_create_3d, px_texture_create_3d); PX(texture_upload_3d, px_texture_upload_3d);
    PX(light_pass, px_light_pass); PX(ssao_pass, px_ssao_pass);
    PX(vbuf_create, px_vbuf_create); PX(vbuf_release, px_vbuf_release);
    PX(draw_vbuf, px_draw_vbuf); PX(draw_vbuf_ib, px_draw_vbuf_ib);
    PX(image_load, px_image_load); PX(image_save, px_image_save);
    PX(set_hud, px_set_hud); PX(set_depth_bias, px_depth_bias); PX(set_depth_clamp, px_depth_clamp);
    PX(occq_begin, px_occq_begin); PX(occq_end, px_occq_end);   /* occ query */
#undef PX
    s_proxy = p;
    pthread_t t; pthread_attr_t a;
    pthread_attr_init(&a);
    pthread_attr_setstacksize(&a, 1u << 20);
    if (pthread_create(&t, &a, ba_worker, NULL) != 0) { pthread_attr_destroy(&a); fprintf(stderr, "[be async] no worker thread: off\n"); return real; }
    pthread_attr_destroy(&a);
    pthread_detach(t);
    fprintf(stderr, "[be async] backend calls recorded on a worker thread\n");
    return &s_proxy;
}

void rsx_be_async_stats(void)
{
    fprintf(stderr, "%llu ops in %llu blocks, %llu waits (", s_n_ops, s_n_blocks_sent, s_n_sync);
    for (int k = 0; k < SY_N; k++) if (s_sync_by[k]) fprintf(stderr, " %s %u", s_sync_name[k], s_sync_by[k]);
    char vb[640]; vb[0] = 0;
    if (s_vbasync) {   /* ba vbuf async: this period, then run totals from the worker */
        snprintf(vb, sizeof vb, "; vbuf async: queued %u (%.1f MB), waited %u (too big %u, after a worker failure %u), out of ids %u,"
                 " ids live %u max %u, creates in flight max %u, draws of a dead id %u, releases of a dead id %u;"
                 " run total: failed on the worker %u (draws from kept bytes %u, dropped %u)",
                 s_vbq, s_vb_qbytes / 1e6, s_vbbig + s_vbsync, s_vbbig, s_vbsync, s_vbnoid, s_vb_nlive, s_vb_nlive_max, s_vb_infl_max,
                 s_vb_deaddraw, s_vb_deadrel, __atomic_load_n(&s_vb_wfail, __ATOMIC_RELAXED),
                 __atomic_load_n(&s_vb_wcopy, __ATOMIC_RELAXED), __atomic_load_n(&s_vb_wdrop, __ATOMIC_RELAXED));
        if (s_vbasync == 2) { const size_t l = strlen(vb);
            snprintf(vb + l, sizeof vb - l, ", verify: bad %u, backend aliases %u",
                     __atomic_load_n(&s_vb_wbad, __ATOMIC_RELAXED), __atomic_load_n(&s_vb_walias, __ATOMIC_RELAXED)); }
        s_vbq = s_vbbig = s_vbsync = s_vbnoid = s_vb_deaddraw = s_vb_deadrel = 0; s_vb_qbytes = 0;
        s_vb_nlive_max = s_vb_nlive; s_vb_infl_max = 0;
    }
    char vdb[1024]; vdb[0] = 0;
    if (s_vd > 0) {   /* ba view direct: this period; per kind "drains / with work / ms in ba_drain" (t35 stack: own buffer, last on the line) */
        size_t l = 0;
        snprintf(vdb, sizeof vdb, "; view direct %d: direct %u, verify %u checked %u mismatched; drains (n/work/ms):",
                 s_vd, s_vd_direct, s_vd_vchk, s_vd_vbad);
        for (int k = 0; k <= SY_N; k++) {
            if (!s_vd_dn[k]) continue;
            l = strlen(vdb);
            snprintf(vdb + l, sizeof vdb - l, " %s %u/%u/%.2f", k < SY_N ? s_sync_name[k] : "untagged", s_vd_dn[k], s_vd_dwork[k], s_vd_dns[k] / 1e6);
        }
        l = strlen(vdb);
        snprintf(vdb + l, sizeof vdb - l, "; first drain after a queued present %u, %.2f ms", s_vd_pres_n, s_vd_pres_ns / 1e6);
        s_vd_direct = s_vd_vchk = s_vd_pres_n = 0; s_vd_pres_ns = 0;   /* s_vd_vbad: run total (the first 8 are logged) */
        memset(s_vd_dn, 0, sizeof s_vd_dn); memset(s_vd_dwork, 0, sizeof s_vd_dwork); memset(s_vd_dns, 0, sizeof s_vd_dns);
    }
    char pa[256]; pa[0] = 0;
    if (ba_present_async()) {   /* be present async limit: this period */
        snprintf(pa, sizeof pa, "; present async: %u queued, %u waited for the previous one (%.2f ms), first drain after it %u (%u found the worker busy, %.2f ms)",
                 s_pa_n, s_pa_wait_n, s_pa_wait_ns / 1e6, s_pa_fd_n, s_pa_fd_busy, s_pa_fd_ns / 1e6);
        s_pa_n = s_pa_wait_n = s_pa_fd_n = s_pa_fd_busy = 0; s_pa_wait_ns = s_pa_fd_ns = 0;
    }
    fprintf(stderr, " ) per 300 frames; colour snapshots queued %u, mismatched %u%s; backend frees forgotten by the view cache %u, record overflows %u%s%s\n",
            s_csnap_q, __atomic_load_n(&s_csnap_bad, __ATOMIC_RELAXED), vb, s_bf_forgot, s_bf_lost, pa, vdb);   /* tg rebase: the two counts; be present async limit: pa; ba view direct: vdb */
    s_csnap_q = 0; s_bf_forgot = s_bf_lost = 0;
    s_n_ops = s_n_blocks_sent = s_n_sync = 0; memset(s_sync_by, 0, sizeof s_sync_by);
}
