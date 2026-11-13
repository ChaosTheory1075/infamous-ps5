#!/usr/bin/env python3
"""rsx doorbell: apply the edits to COPIES of main.cpp / cellGcmSys.c (never to the trees).

  apply_doorbell.py main <in main.cpp> <out main.cpp>
  apply_doorbell.py fork <in cellGcmSys.c> <out cellGcmSys.c>

Every edit is an exact-text replacement that must match exactly once, so a base that moved under it fails loudly
instead of landing somewhere else. make_patches.sh runs this on fresh copies and writes the .patch files.
"""
import sys


def sub(src, old, new, what):
    n = src.count(old)
    if n != 1:
        sys.exit("rsx doorbell: anchor '%s' matches %d times (want 1)" % (what, n))
    return src.replace(old, new)


# --------------------------------------------------------------------------------------------------------------
# cellGcmSys.c
# --------------------------------------------------------------------------------------------------------------
FORK_STATE = r'''
/* rsx doorbell: state the walker leaves for the RSX thread's idle wait (see "rsx doorbell" above
 * cellGcm_rsx_process_fifo). Written by the RSX thread only. */
static int      s_db_stop;        /* what the last pass stopped on: 0 caught-up/flip, 1 acquire, 2 park, 3 stalled */
static u32      s_db_sema_val;    /* the value that acquire waits for */
static int      s_db_stuck, s_db_burned;   /* the walker watchdogs' pass counters (stuck-get, circling) */
static unsigned s_db_progress;    /* passes that moved get */
/* A guest or SPU thread changed something the RSX thread may be sleeping through: 0 HLE flip/put, 1 SPU PUT into
 * the label window, 2 a guest read of the ref register. One load when PS3_RSX_DOORBELL is off. */
static void gcm_db_ring(int src);
'''

FORK_BLOCK = r'''/* ---------------------------------------------------------------------------
 * rsx doorbell
 *
 * The RSX thread (the runner's frame clock) sleeps PS3_FRAMECLOCK_US between two drain passes and nothing wakes
 * it: a put, a flip, the label an acquire is parked on all wait for the sleep to run out, while the guest sits on
 * the label / ref / get / flip the next pass would give it. Two things the runner can use instead of the bare
 * sleep (main.cpp, both off by default: PS3_RSX_SPIN_US, PS3_RSX_DOORBELL):
 *
 *   cellGcm_rsx_idle_state()     a lock-free look at "would a pass now make progress": what its bounded spin polls;
 *   cellGcm_rsx_doorbell_wait()  the same timed sleep, ended early by gcm_db_ring() from the threads that can
 *                                tell: an HLE flip or put, an SPU PUT into the label window (what a blocking
 *                                NV406E acquire waits for), a guest read of the ref register (a guest seen
 *                                waiting on the RSX: cellGcm_ref_on_poll).
 *
 * A put the title stores itself has no hook (an inline store in the lifted code), nor has a park it patches or a
 * label a PPU thread writes: the spin, the title's next ref read, or at worst the timed sleep -- today's latency
 * -- picks those up.
 *
 * "Progress" is exact, not "put != get": a pass parked on an acquire only moves when the label has the value, one
 * parked on a self-JUMP only when the word was patched, and a stalled walker (the stuck-get / circling watchdogs,
 * which count PASSES) is never hurried -- those keep riding on the timed passes, a full sleep apart, as before.
 *
 * No lost wake-up: the waiter stores s_db_waiting (seq_cst) and THEN looks for work, holding the mutex; a ringer
 * changes guest state, fences, THEN loads s_db_waiting, and signals under the same mutex. One of the two sees
 * the other. Every wait is timed as well, so anything without a hook costs what it costs today, never more.
 * -----------------------------------------------------------------------*/
static int gcm_db_pending(void)
{
    if (s_flip_pending) return 1;                                 /* a frame to present */
    if (!s_gcm_context_ea && !s_gcm_syscall_mode) return 0;
    if (s_db_stop == 3) return 0;                                 /* stalled: never hurried */
    const u32 get = s_fifo_getoff;
    if (vm_read32(GCM_CONTROL_GUEST_ADDR + 0) == get) return 0;   /* caught up */
    if (s_db_stop == 1) {                                         /* parked on an acquire: the label ends it */
        const u32 off = s_sema_offset & 0xFFFFu;
        if (off >= CELL_GCM_MAX_LABEL_COUNT * GCM_LABEL_STRIDE) return 0;   /* not a label: leave it to the timed passes */
        return vm_read32(GCM_LABEL_GUEST_BASE + off) == s_db_sema_val;
    }
    if (s_db_stop == 2) {                                         /* parked on a self-JUMP: the patch ends it */
        const u32 ea = gcm_io2ea(get);
        const u32 w = ea ? vm_read32(ea) : 0;
        return !ea || (w >> 29) != 1u || (w & 0x1FFFFFFCu) != get;
    }
    return 1;
}

/* RSX thread only. 1: a pass now makes progress. 0: nothing to do. -1: the walker is stalled short of put. */
int cellGcm_rsx_idle_state(void)
{
    if (gcm_db_pending()) return 1;
    return s_db_stop == 3 ? -1 : 0;
}

unsigned cellGcm_rsx_progress(void) { return s_db_progress; }

#if !defined(_WIN32)
static pthread_mutex_t s_db_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t  s_db_cv = PTHREAD_COND_INITIALIZER;
static int      s_db_armed;       /* cellGcm_rsx_doorbell_wait has been used: ringers look further */
static int      s_db_waiting;     /* the RSX thread is in (or entering) its wait */
static unsigned s_db_rings[3];    /* wake-ups by source */

static void gcm_db_ring(int src)
{
    if (!__atomic_load_n(&s_db_armed, __ATOMIC_RELAXED)) return;      /* PS3_RSX_DOORBELL off */
    __atomic_thread_fence(__ATOMIC_SEQ_CST);                          /* the caller's store, then this load */
    if (!__atomic_load_n(&s_db_waiting, __ATOMIC_SEQ_CST)) return;    /* awake: it looks again before it sleeps */
    if (!gcm_db_pending()) return;                                    /* nothing a pass could do with it yet */
    pthread_mutex_lock(&s_db_mu);
    pthread_cond_broadcast(&s_db_cv);
    pthread_mutex_unlock(&s_db_mu);
    __atomic_add_fetch(&s_db_rings[src], 1, __ATOMIC_RELAXED);
}

/* RSX thread only: sleep up to `us`, or until a ring. Returns 1 when it ended early (rung, or the work was
 * already there). The deadline is CLOCK_REALTIME, the condvar's default clock, as in ps3_memkick_wait. */
int cellGcm_rsx_doorbell_wait(unsigned us)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    const uint64_t ns = (uint64_t)ts.tv_nsec + (uint64_t)us * 1000ull;
    ts.tv_sec += (time_t)(ns / 1000000000ull);
    ts.tv_nsec = (long)(ns % 1000000000ull);
    int early = 1;
    pthread_mutex_lock(&s_db_mu);
    __atomic_store_n(&s_db_armed, 1, __ATOMIC_RELAXED);
    __atomic_store_n(&s_db_waiting, 1, __ATOMIC_SEQ_CST);
    if (!gcm_db_pending())
        early = pthread_cond_timedwait(&s_db_cv, &s_db_mu, &ts) == 0;
    __atomic_store_n(&s_db_waiting, 0, __ATOMIC_SEQ_CST);
    pthread_mutex_unlock(&s_db_mu);
    return early;
}

/* Wake-ups by source since the last call (0 HLE flip/put, 1 SPU label PUT, 2 guest ref read). */
void cellGcm_rsx_doorbell_counts(unsigned c[3])
{
    for (int i = 0; i < 3; i++) c[i] = __atomic_exchange_n(&s_db_rings[i], 0, __ATOMIC_RELAXED);
}
#else   /* the Windows runner keeps its Sleep */
static void gcm_db_ring(int src) { (void)src; }
int  cellGcm_rsx_doorbell_wait(unsigned us) { Sleep((us + 999) / 1000); return 0; }
void cellGcm_rsx_doorbell_counts(unsigned c[3]) { c[0] = c[1] = c[2] = 0; }
#endif

'''


def patch_fork(s):
    # 1. state + forward declaration, right after the flip-pending accessor
    a = ("int cellGcm_take_flip_pending(void)\n{\n    int v = s_flip_pending;\n    s_flip_pending = 0;\n"
         "    return v;\n}\n")
    s = sub(s, a, a + FORK_STATE, "take_flip_pending")

    # 2. SPU PUT into the label window
    a = "void gcm_note_spu_put(u32 ea, u32 size)\n{\n"
    s = sub(s, a, a +
            "    /* rsx doorbell: an SPU PUT that touches the label window is what a blocking acquire waits for. */\n"
            "    if (ea - GCM_LABEL_GUEST_BASE < CELL_GCM_MAX_LABEL_COUNT * GCM_LABEL_STRIDE ||\n"
            "        GCM_LABEL_GUEST_BASE - ea < size) gcm_db_ring(1);\n", "gcm_note_spu_put")

    # 3. a guest read of the ref register
    a = "void cellGcm_ref_on_poll(void)\n{\n"
    s = sub(s, a, a +
            "    gcm_db_ring(2);   /* rsx doorbell: a guest is reading ref, i.e. waiting on the RSX -- wake it if it has work */\n",
            "cellGcm_ref_on_poll")

    # 4. the block itself, ahead of the drain entry point
    a = "void cellGcm_rsx_process_fifo(void)\n{\n"
    s = sub(s, a, FORK_BLOCK + a, "cellGcm_rsx_process_fifo")

    # 5. the value a blocking acquire waits for
    a = ("                    if (PS3_FT_ON() && !s_ft_sema_t0) s_ft_sema_t0 = ps3_ft_now();\n"
         "                    sem_blocked = 1; break;\n")
    s = sub(s, a,
            "                    if (PS3_FT_ON() && !s_ft_sema_t0) s_ft_sema_t0 = ps3_ft_now();\n"
            "                    s_db_sema_val = v;   /* rsx doorbell */\n"
            "                    sem_blocked = 1; break;\n", "sem_blocked")

    # 6. circling watchdog counter
    a = "      } else burned = 0; }\n"
    s = sub(s, a, "      } else burned = 0;\n      s_db_burned = burned; }   /* rsx doorbell */\n", "burned")

    # 7. what the pass stopped on (before the stuck-get block clears the two flags), and its counter
    a = "    { static u32 last = 0xFFFFFFFFu; static int stuck = 0;\n"
    s = sub(s, a, "    s_db_stop = s_sema_blocked_pass ? 1 : s_park_pass ? 2 : 0;   /* rsx doorbell */\n" + a, "stuck head")
    a = "      } else { stuck = 0; last = s_fifo_getoff; } }\n"
    s = sub(s, a,
            "      } else { stuck = 0; last = s_fifo_getoff; }\n"
            "      s_db_stuck = stuck; }\n"
            "    /* rsx doorbell: a walker those two watchdogs are counting on is not to be hurried */\n"
            "    if (!s_db_stop && (s_db_stuck || s_db_burned)) s_db_stop = 3;\n", "stuck tail")

    # 8. progress counter
    a = "    g_gcm_fifo_drained_ea = gcm_io2ea(s_fifo_getoff);\n"
    s = sub(s, a, "    if (s_fifo_getoff != start_off) s_db_progress++;   /* rsx doorbell */\n" + a, "drained_ea")

    # 9. HLE flip that is not queued in the FIFO
    a = ("        s_flip_pending = 1;   /* ticker: present BEFORE the next drain */\n"
         "        s_flip_request_count++;\n")
    s = sub(s, a, a + "        gcm_db_ring(0);       /* rsx doorbell */\n", "gcm_flip_request")

    # 10. HLE put: the buffer-full callback
    a = "        vm_write32(GCM_CONTROL_GUEST_ADDR + 0, io_begin);        /* put = begin */\n    }\n"
    s = sub(s, a, a + "    gcm_db_ring(0);   /* rsx doorbell */\n", "fifo_recycle")

    # 11. HLE put: the lv1 driver's FIFO reset
    a = "    s_fifo_getoff  = get;\n    s_fifo_calloff = 0;\n}\n"
    s = sub(s, a, "    s_fifo_getoff  = get;\n    s_fifo_calloff = 0;\n    gcm_db_ring(0);   /* rsx doorbell */\n}\n",
            "syscall_set_fifo")
    return s


# --------------------------------------------------------------------------------------------------------------
# main.cpp
# --------------------------------------------------------------------------------------------------------------
MAIN_HELPERS = r'''
#if !defined(_WIN32)
/* rsx doorbell: the wait between two passes of the frame clock, when PS3_RSX_SPIN_US / PS3_RSX_DOORBELL ask for
 * more than the bare sleep (cellGcmSys.c "rsx doorbell" has the mechanism and the no-lost-wake-up argument).
 *
 *   1. Work already there (the last pass stopped at a flip with commands behind it, the guest was quick): no wait.
 *   2. PS3_RSX_SPIN_US, only after a pass that found work: poll for the guest's answer -- the next put, the label
 *      an acquire is parked on -- instead of sleeping through it. The guest that just got its label / ref / flip
 *      usually answers within microseconds, and usleep cannot return in under ~100 us on the PS5. The spin ends
 *      on this thread's own clock (every PS5 thread is FIFO: a spinner has to stop itself), at the next vblank
 *      deadline, and on a stalled walker; an idle RSX thread never spins.
 *   3. PS3_RSX_DOORBELL: the timed sleep, woken by the threads that can tell there is work. Else the bare sleep.
 *
 * Returns 1 when it came back early for work. The caller holds it to that: an early pass that finds none is
 * followed by one bare sleep, so nothing here can turn the loop into a busy one. */
static struct { unsigned at_once, spins, spin_hits, bells, bell_early, wasted; } g_fc_db;

static inline void fc_relax(void)
{
#if defined(__x86_64__) || defined(__i386__)
    __builtin_ia32_pause();
#elif defined(__aarch64__)
    __asm__ __volatile__("yield");
#endif
}

static int fc_idle_wait(int us, int spin_us, int bell, int productive, uint64_t vbl_next)
{
    int st = cellGcm_rsx_idle_state();
    if (st > 0) { g_fc_db.at_once++; return 1; }
    if (st == 0 && spin_us > 0 && productive) {
        if (spin_us > 2000) spin_us = 2000;
        g_fc_db.spins++;
        const uint64_t t0 = fc_now_ns(), lim = (uint64_t)spin_us * 1000ull;
        for (unsigned k = 1;; k++) {
            for (int i = 0; i < 8; i++) fc_relax();
            st = cellGcm_rsx_idle_state();
            if (st > 0) { g_fc_db.spin_hits++; return 1; }
            if (st < 0) break;
            if (!(k & 7u)) {
                const uint64_t t = fc_now_ns();
                if ((int64_t)(t - vbl_next) >= 0) return 0;   /* a vblank tick is due: no sleep on top of it */
                if (t - t0 >= lim) break;
            }
        }
    }
    /* A stalled walker (st < 0) gets the bare sleep: its watchdogs count passes, a full sleep apart. */
    if (bell && st == 0) {
        g_fc_db.bells++;
        const int early = cellGcm_rsx_doorbell_wait((unsigned)us);
        g_fc_db.bell_early += (unsigned)early;
        return early;
    }
    usleep((useconds_t)us);
    return 0;
}
#endif
'''

MAIN_ENV = r'''    /* rsx doorbell: PS3_RSX_SPIN_US=<us> (default 0 = off, capped at 2000) -- after a pass that found work, poll
     * that long for the guest's next put / label before sleeping. PS3_RSX_DOORBELL=1 (default 0) -- the sleep is
     * woken by an HLE flip or put, an SPU write of the label an acquire is parked on, a guest reading the ref
     * register. With both 0 the wait below is the usleep it always was. Read live (PS3_TOGGLE_FILE). Off until
     * the title's first flip: before it every pass presents, and boot should not change. */
    int spin_us_env = 0, bell_env = 0;
    { const char* e = getenv("PS3_RSX_SPIN_US");  if (e && atoi(e) > 0) spin_us_env = atoi(e); }
    { const char* e = getenv("PS3_RSX_DOORBELL"); if (e && atoi(e) > 0) bell_env = 1; }
    if (spin_us_env || bell_env)
        fprintf(stderr, "[rsx] doorbell: spin %d us, doorbell %d\n", spin_us_env, bell_env);
'''

MAIN_LOOP_VARS = r'''#if !defined(_WIN32)
    /* rsx doorbell: what the pass before this wait did, and whether that wait came back early */
    int db_early = 0, db_live = 0;
    unsigned db_prog = 0;
    LONG db_pres = 0;
    ULONGLONG db_log = 0;
#endif
'''

MAIN_WAIT_OLD = r'''#ifdef _WIN32
            Sleep((DWORD)((us + 999) / 1000));
#else
            usleep((useconds_t)us);
#endif
        }
        ULONGLONG now = GetTickCount64();
'''

MAIN_WAIT_NEW = r'''#ifdef _WIN32
            Sleep((DWORD)((us + 999) / 1000));
#else
            /* rsx doorbell */
            const int spin_us = ps3_toggle_get("PS3_RSX_SPIN_US", spin_us_env);
            const int bell    = ps3_toggle_get("PS3_RSX_DOORBELL", bell_env) > 0;
            db_live = (spin_us > 0 || bell) && rsx_ok && cellGcm_flip_request_count() != 0;
            if (db_live) {
                const int productive = cellGcm_rsx_progress() != db_prog || g_frames_presented != db_pres;
                if (db_early && !productive) {       /* came back early and found nothing: one bare sleep */
                    g_fc_db.wasted++;
                    usleep((useconds_t)us);
                    db_early = 0;
                } else
                    db_early = fc_idle_wait(us, spin_us, bell, productive, vbl_next);
                db_prog = cellGcm_rsx_progress();
                db_pres = g_frames_presented;
            } else {
                usleep((useconds_t)us);
                db_early = 0;
            }
#endif
        }
        ULONGLONG now = GetTickCount64();
#if !defined(_WIN32)
        if (db_live && now - db_log >= 10000) {      /* rsx doorbell: what the waits did, per 10 s */
            unsigned c[3];
            cellGcm_rsx_doorbell_counts(c);
            if (db_log)
                fprintf(stderr, "[rsx doorbell] 10 s: %u waits skipped (work already there), %u spins (%u hit), "
                        "%u doorbell waits (%u ended early; rings: hle %u, spu label %u, ref read %u), "
                        "%u early passes found nothing\n",
                        g_fc_db.at_once, g_fc_db.spins, g_fc_db.spin_hits, g_fc_db.bells, g_fc_db.bell_early,
                        c[0], c[1], c[2], g_fc_db.wasted);
            memset(&g_fc_db, 0, sizeof g_fc_db);
            db_log = now;
        }
#endif
'''


def patch_main(s):
    # 1. what cellGcmSys.c gives the frame clock
    a = "int      cellGcm_drain_sema_blocked(void);\n"
    s = sub(s, a, a +
            "/* rsx doorbell (cellGcmSys.c) */\n"
            "int      cellGcm_rsx_idle_state(void);            /* 1 a pass now makes progress, 0 nothing to do, -1 stalled */\n"
            "int      cellGcm_rsx_doorbell_wait(unsigned us);  /* the timed sleep, ended early by a ring: 1 = early */\n"
            "unsigned cellGcm_rsx_progress(void);              /* passes that moved get */\n"
            "void     cellGcm_rsx_doorbell_counts(unsigned c[3]);\n", "extern block")

    # 2. the wait helper, ahead of frame_clock
    a = "static DWORD WINAPI frame_clock(LPVOID)\n{\n"
    s = sub(s, a, MAIN_HELPERS.lstrip("\n") + "\n" + a, "frame_clock")

    # 3. the two switches, after PS3_FRAMECLOCK_US
    a = ("    { const char* e = getenv(\"PS3_FRAMECLOCK_US\"); if (e && atoi(e) > 0) clock_us_env = atoi(e); }\n")
    s = sub(s, a, a + MAIN_ENV, "PS3_FRAMECLOCK_US")

    # 4. loop state
    a = "    uint64_t vbl_next = fc_now_ns();\n\n    for (;;) {\n"
    s = sub(s, a, "    uint64_t vbl_next = fc_now_ns();\n" + MAIN_LOOP_VARS + "\n    for (;;) {\n", "loop head")

    # 5. the wait
    s = sub(s, MAIN_WAIT_OLD, MAIN_WAIT_NEW, "wait")
    return s


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ("main", "fork"):
        sys.exit(__doc__)
    with open(sys.argv[2], encoding="latin-1", newline="") as f:
        s = f.read()
    if "rsx doorbell" in s:
        sys.exit("rsx doorbell: %s already carries the edit" % sys.argv[2])
    s = patch_main(s) if sys.argv[1] == "main" else patch_fork(s)
    with open(sys.argv[3], "w", encoding="latin-1", newline="") as f:
        f.write(s)


if __name__ == "__main__":
    main()
