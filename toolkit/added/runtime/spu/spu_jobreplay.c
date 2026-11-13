#define _GNU_SOURCE 1
/* SPU job replay harness (tools: work/jr_*): step A -- which indirect calls of the WWS policy module
 * enter jobs, with what target, and how long each call runs. PS3_SPU_JR=1 turns the counting on;
 * a table is printed every 10 s ("[jr] ..."). */
#include "spu_context.h"
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
static int jr_on(void) { static int v = -1; if (v < 0) { const char* e = getenv("PS3_SPU_JR"); v = e && e[0] == '1'; } return v; }
static uint64_t jr_ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (uint64_t)t.tv_sec * 1000000000ull + t.tv_nsec; }
#define JR_N 64
static struct { uint32_t site, tgt, img; unsigned long n; uint64_t ns; } s_jr[JR_N];
static __thread uint64_t t_jr_t0[4]; static __thread uint32_t t_jr_tgt[4]; static __thread int t_jr_d;
static uint64_t s_jr_last;
void jr_print(void);
void spu_jr_note(spu_context* ctx, uint32_t site, uint32_t tgt, int end)
{
    if (!jr_on()) return;
    if (!end) {
        if (t_jr_d < 4) { t_jr_t0[t_jr_d] = jr_ns(); t_jr_tgt[t_jr_d] = tgt & SPU_LS_MASK; }
        t_jr_d++;
        jr_print();
        return;
    }
    if (--t_jr_d < 0) { t_jr_d = 0; return; }
    if (t_jr_d >= 4) return;
    const uint64_t dt = jr_ns() - t_jr_t0[t_jr_d];
    const uint32_t tg = t_jr_tgt[t_jr_d], img = (uint32_t)ctx->resident_ovl;
    for (int i = 0; i < JR_N; i++) {
        if (s_jr[i].n && (s_jr[i].site != site || s_jr[i].tgt != tg || s_jr[i].img != img)) continue;
        s_jr[i].site = site; s_jr[i].tgt = tg; s_jr[i].img = img;
        __atomic_add_fetch(&s_jr[i].n, 1, __ATOMIC_RELAXED); __atomic_add_fetch(&s_jr[i].ns, dt, __ATOMIC_RELAXED);
        break;
    }
    jr_print();
}
static void jr_print_(void);
void jr_print(void) { jr_print_(); }
static void jr_print_(void)
{
    const uint64_t now = jr_ns();
    if (now - s_jr_last > 10000000000ull) {
        s_jr_last = now;
        for (int i = 0; i < JR_N; i++) if (s_jr[i].n)
            fprintf(stderr, "[jr] site 0x%X target 0x%05X ovl %u: %lu calls, %.1f us each, %.0f ms total\n",
                    s_jr[i].site, s_jr[i].tgt, s_jr[i].img, s_jr[i].n, s_jr[i].ns / 1e3 / s_jr[i].n, s_jr[i].ns / 1e6);
    }
}

/* step A2: job time by dispatch region. A dispatch to LS 0x4000..0x13FFF while a job overlay
 * (resident_ovl >= 200) is resident = inside a job; anything else = the kernel. Time from entering the
 * job region to leaving it is charged to that overlay. */
int g_spu_jr_on = -1;
/* PS3_SPU_JR=1: every resolver miss (a pc with no lifted function -> the interpreter), counted per
 * (resident overlay, image, pc) over the whole run; "[jr-nofn]" table every 30 s, biggest first. */
#define JR_NF 512
static struct { uint32_t key, pc; int ovl, img, slot; unsigned long n; } s_nf[JR_NF];
static uint64_t s_nf_last;
void spu_jr_nofn(const spu_context* ctx, uint32_t pc)
{
    int slot_img = 0;   /* the resident code slot covering pc, if any (the plugin image on the audio SPUs) */
    for (unsigned k = 0; k < SPU_RESIDENT_CODE_SLOTS; k++)
        if (ctx->resident_code[k].image_id && pc - ctx->resident_code[k].lsa < ctx->resident_code[k].size) { slot_img = ctx->resident_code[k].image_id; break; }
    const uint32_t key = (pc & SPU_LS_MASK) | ((uint32_t)ctx->resident_ovl << 18) | ((uint32_t)(slot_img & 0xFF) << 23) | 0x80000000u;
    uint32_t h = (key * 2654435761u) >> 23;
    for (int k = 0; k < JR_NF; k++, h = (h + 1) & (JR_NF - 1)) {
        if (s_nf[h].key == key) { __atomic_add_fetch(&s_nf[h].n, 1, __ATOMIC_RELAXED); break; }
        if (!s_nf[h].key) { s_nf[h].key = key; s_nf[h].pc = pc & SPU_LS_MASK; s_nf[h].ovl = ctx->resident_ovl; s_nf[h].img = ctx->image_id; s_nf[h].slot = slot_img; s_nf[h].n = 1; break; }
    }
    const uint64_t now = jr_ns();
    if (now - s_nf_last < 30000000000ull) return;
    s_nf_last = now;
    int idx[JR_NF], m = 0;
    for (int i = 0; i < JR_NF; i++) if (s_nf[i].key) idx[m++] = i;
    for (int i = 0; i < m; i++) for (int j = i + 1; j < m; j++) if (s_nf[idx[j]].n > s_nf[idx[i]].n) { int t = idx[i]; idx[i] = idx[j]; idx[j] = t; }
    for (int i = 0; i < m && i < 40; i++)
        fprintf(stderr, "[jr-nofn] ovl %d img %d slot image %d pc 0x%05X: %lu\n", s_nf[idx[i]].ovl, s_nf[idx[i]].img, s_nf[idx[i]].slot, s_nf[idx[i]].pc, s_nf[idx[i]].n);
}
__attribute__((constructor)) static void jr_init(void) { g_spu_jr_on = jr_on() ? 1 : 0; }
static __thread int t_in, t_ovl, t_ent; static __thread uint64_t t_t0;
static struct { int ovl; uint32_t ent; unsigned long n; uint64_t ns; } s_jd[128];
static uint64_t s_jd_last;

#ifndef __PROSPERO__   /* capture/replay */
/* ===========================================================================
 * Step B/C: capture and replay of whole job runs.
 *
 * Capture (PS3_SPU_JR_CAP=<dir>:<ovl>:<count>[:<skip seconds>]): the first <count> runs of job overlay
 * <ovl> after <skip> seconds are written to <dir>/jr_<ovl>_<k>.bin: the whole spu_context at the moment
 * the dispatcher enters the job (pc in the job region), then every event of the run in order: each DMA
 * element (GET: the source bytes; PUT: the bytes written), each atomic line op, each channel read and
 * count (the value it returned), each channel write. The run ends when execution leaves the job region
 * (a dispatch outside it, or an event with ctx->pc outside it).
 *
 * Replay (PS3_SPU_JR_REPLAY=<dir>[:<repeats>]): at the first SPU dispatch, every capture in <dir> is run
 * on a private context: GETs and channel reads are served from the log, PUTs / channel writes / atomics
 * only go into a digest, nothing touches the game. Each run ends where the capture ended. Printed per
 * file: event digest, final-state digest (LS + registers + pc), events consumed, time per run. Two
 * builds replaying the same captures must print the same digests; the times compare the code. Then exit.
 * ===========================================================================*/
#include <string.h>
#include <setjmp.h>
#include <dirent.h>
#include <unistd.h>
#include <sys/syscall.h>
#include <sys/ioctl.h>
#include <linux/perf_event.h>
extern uint8_t* vm_base;
/* this thread's user-mode cycles / instructions: not moved by clock speed or the game's other threads */
static int jr_pc_open(unsigned long cfg)
{
    struct perf_event_attr a; memset(&a, 0, sizeof a);
    a.type = PERF_TYPE_HARDWARE; a.size = sizeof a; a.config = cfg; a.exclude_kernel = 1; a.exclude_hv = 1;
    return (int)syscall(SYS_perf_event_open, &a, 0, -1, -1, 0);
}
static uint64_t jr_pc_read(int fd) { uint64_t v = 0; if (fd >= 0 && read(fd, &v, 8) != 8) v = 0; return v; }
enum { JR_GET = 1, JR_PUT = 2, JR_RDCH = 3, JR_RCHCNT = 4, JR_WRCH = 5, JR_ATOM = 6 };
typedef struct { uint8_t type; uint32_t a, b, c, len; uint64_t off; } jr_ev;   /* off: into the data blob */
typedef struct {
    int active; uint32_t ovl, entry; uint64_t dig;
    jr_ev* ev; size_t nev, cap; uint8_t* data; size_t ndata, dcap;
    size_t cur;      /* replay cursor */
    int mismatch; char why[160];
} jr_run;
static __thread jr_run* t_cap; static __thread jr_run* t_rep;
static int s_cap_ovl = -1, s_cap_left; static double s_cap_skip; static char s_cap_dir[256];
static int s_cap_busy; static int s_cap_k;
static int s_rep_mode = -1; static char s_rep_dir[256]; static int s_rep_reps = 20;
static uint64_t s_t_start;

static inline uint64_t jr_fnv(uint64_t h, const void* p, size_t n)
{ const uint8_t* b = (const uint8_t*)p; for (size_t i = 0; i < n; i++) { h ^= b[i]; h *= 1099511628211ull; } return h; }
/* PS3_SPU_JR_SPU=<hex spu ids, comma>: on those SPUs (the audio SPURS: 2005,2006) any pc >= 0x4000 is the
 * job region (the DSP plugin images live there, not as job overlays); elsewhere: a job overlay resident */
static uint32_t s_jr_spu[8]; static int s_jr_nspu = -1;
static inline int jr_in_region(const spu_context* ctx, uint32_t pc)
{
    pc &= SPU_LS_MASK;
    if (__builtin_expect(s_jr_nspu < 0, 0)) {
        s_jr_nspu = 0; const char* e = getenv("PS3_SPU_JR_SPU");
        while (e && *e && s_jr_nspu < 8) { s_jr_spu[s_jr_nspu++] = (uint32_t)strtoul(e, (char**)&e, 16); if (*e == ',') e++; else break; }
    }
    for (int i = 0; i < s_jr_nspu; i++) if (ctx->spu_id == s_jr_spu[i]) return 1;   /* window = wake .. next event wait */
    return pc >= 0x4000 && pc < 0x14000 && ctx->resident_ovl >= 200;
}
static inline int jr_spu_listed(const spu_context* ctx)
{ (void)jr_in_region(ctx, 0); for (int i = 0; i < s_jr_nspu; i++) if (ctx->spu_id == s_jr_spu[i]) return 1; return 0; }

static void jr_add(jr_run* r, uint8_t type, uint32_t a, uint32_t b, uint32_t c, const void* data, uint32_t len)
{
    if (r->nev == r->cap) { r->cap = r->cap ? r->cap * 2 : 4096; r->ev = (jr_ev*)realloc(r->ev, r->cap * sizeof(jr_ev)); }
    if (r->ndata + len > r->dcap) { while (r->ndata + len > r->dcap) r->dcap = r->dcap ? r->dcap * 2 : (1u << 20); r->data = (uint8_t*)realloc(r->data, r->dcap); }
    jr_ev* e = &r->ev[r->nev++]; e->type = type; e->a = a; e->b = b; e->c = c; e->len = len; e->off = r->ndata;
    if (len) { memcpy(r->data + r->ndata, data, len); r->ndata += len; }
}
static void jr_cfg(void)
{
    static int done; if (done) return; done = 1;
    s_t_start = jr_ns();
    const char* c = getenv("PS3_SPU_JR_CAP");
    if (c) { char d[256]; int ovl = -1, n = 0; double sk = 60;
             if (sscanf(c, "%255[^:]:%d:%d:%lf", d, &ovl, &n, &sk) >= 3) { strcpy(s_cap_dir, d); s_cap_ovl = ovl; s_cap_left = n; s_cap_skip = sk; } }
    const char* r = getenv("PS3_SPU_JR_REPLAY");
    s_rep_mode = 0;
    if (r) { char d[256]; int k = 20; if (sscanf(r, "%255[^:]:%d", d, &k) >= 1) { strcpy(s_rep_dir, d); s_rep_reps = k; s_rep_mode = 1; } }
}

/* the whole context, with ls pointed back at its own store */
static void jr_cap_begin(spu_context* ctx, uint32_t pc)
{
    jr_run* r = (jr_run*)calloc(1, sizeof *r);
    r->active = 1; r->ovl = (uint32_t)ctx->resident_ovl; r->entry = pc; r->dig = 1469598103934665603ull;
    const int own = ctx->ls == ctx->ls_store;
    jr_add(r, 0, (uint32_t)sizeof(spu_context), (uint32_t)own, pc, ctx, (uint32_t)sizeof(spu_context));
    if (!own) jr_add(r, 0, SPU_LS_SIZE, 0, 0, ctx->ls, SPU_LS_SIZE);   /* ls elsewhere: its bytes too */
    t_cap = r;
}
static void jr_write(jr_run* r, const spu_context* ctx)
{
    char p[400]; snprintf(p, sizeof p, "%s/jr_%u_%d.bin", s_cap_dir, r->ovl, s_cap_k++);
    FILE* f = fopen(p, "wb");
    if (f) {
        const uint64_t fin = jr_fnv(jr_fnv(1469598103934665603ull, ctx->ls, SPU_LS_SIZE), ctx->gpr, sizeof ctx->gpr);
        fwrite("JRC1", 1, 4, f); fwrite(&r->ovl, 4, 1, f); fwrite(&r->entry, 4, 1, f);
        fwrite(&r->dig, 8, 1, f); fwrite(&fin, 8, 1, f);
        fwrite(&r->nev, sizeof r->nev, 1, f); fwrite(r->ev, sizeof(jr_ev), r->nev, f);
        fwrite(&r->ndata, sizeof r->ndata, 1, f); fwrite(r->data, 1, r->ndata, f);
        fclose(f);
        fprintf(stderr, "[jr-cap] %s: ovl %u entry 0x%05X, %zu events, %zu data bytes, event digest %016llX\n",
                p, r->ovl, r->entry, r->nev, r->ndata, (unsigned long long)r->dig);
    }
    free(r->ev); free(r->data); free(r);
}
static void jr_cap_end(spu_context* ctx)
{
    jr_run* r = t_cap; t_cap = 0;
    jr_write(r, ctx);
    __atomic_store_n(&s_cap_busy, 0, __ATOMIC_RELEASE);
}

/* ---- replay ---- */
static __thread jmp_buf t_rep_env;
static __thread uint32_t s_jr_last_steps;
static void jr_rep_stop(spu_context* ctx) { (void)ctx; longjmp(t_rep_env, 1); }
static const jr_ev* jr_rep_next(spu_context* ctx, uint8_t type, uint32_t a, uint32_t b, uint32_t c)
{
    jr_run* r = t_rep;
    if (r->cur >= r->nev) { snprintf(r->why, sizeof r->why, "ran past the log (type %u a=0x%X)", type, a); r->mismatch = 1; jr_rep_stop(ctx); }
    const jr_ev* e = &r->ev[r->cur++];
    if (r->cur == r->nev) s_jr_last_steps = ctx->steps;   /* jr interp: the job's last logged event */
    if (e->type != type || e->a != a || (type != JR_RDCH && type != JR_RCHCNT && (e->b != b || e->c != c))) {
        snprintf(r->why, sizeof r->why, "event %zu: log type %u a=0x%X b=0x%X c=0x%X, replay type %u a=0x%X b=0x%X c=0x%X",
                 r->cur - 1, e->type, e->a, e->b, e->c, type, a, b, c);
        r->mismatch = 1; jr_rep_stop(ctx);
    }
    return e;
}

/* event hooks (called only when g_spu_jr_on > 0); return 1 = replay handled it, skip the real op */
static inline int jr_window_check(spu_context* ctx)
{
    if (t_rep && !jr_in_region(ctx, ctx->pc)) jr_rep_stop(ctx);
    if (t_cap && !jr_in_region(ctx, ctx->pc)) { jr_cap_end(ctx); return 0; }
    return t_cap || t_rep;
}
int spu_jr_dma(spu_context* ctx, uint32_t lsa, uint64_t ea, uint32_t size, uint32_t cmd)
{
    if (!jr_window_check(ctx)) return 0;
    const int get = (cmd & 0x40) != 0, put = !get && (cmd & 0x20);
    lsa &= SPU_LS_MASK;
    if (lsa + size > SPU_LS_SIZE) return 0;
    if (t_cap) {
        if (get) jr_add(t_cap, JR_GET, (uint32_t)ea, lsa, size, vm_base + (uint32_t)ea, size);
        else if (put) { jr_add(t_cap, JR_PUT, (uint32_t)ea, lsa, size, NULL, 0);
                        t_cap->dig = jr_fnv(jr_fnv(t_cap->dig, &ea, 4), ctx->ls + lsa, size); }
        return 0;
    }
    const jr_ev* e = jr_rep_next(ctx, get ? JR_GET : JR_PUT, (uint32_t)ea, lsa, size);
    if (get) memcpy(ctx->ls + lsa, t_rep->data + e->off, size);
    else t_rep->dig = jr_fnv(jr_fnv(t_rep->dig, &ea, 4), ctx->ls + lsa, size);
    return 1;
}
/* atomics: before the real op (cmd = the MFC_Cmd value); returns 1 when replay served it */
int spu_jr_atomic_pre(spu_context* ctx, uint32_t cmd)
{
    if (!jr_window_check(ctx)) return 0;
    if (cmd != MFC_GETLLAR_CMD && cmd != MFC_PUTLLC_CMD && cmd != MFC_PUTLLUC_CMD && cmd != MFC_PUTQLLUC_CMD) return 0;
    const uint32_t lsa = ctx->mfc_lsa & SPU_LS_MASK & ~127u, ea = ctx->mfc_eal & ~127u;
    if (t_cap) {
        if (cmd != MFC_GETLLAR_CMD) t_cap->dig = jr_fnv(jr_fnv(t_cap->dig, &cmd, 4), ctx->ls + lsa, 128);
        return 0;
    }
    const jr_ev* e = jr_rep_next(ctx, JR_ATOM, cmd, ea, lsa);
    if (cmd == MFC_GETLLAR_CMD) memcpy(ctx->ls + lsa, t_rep->data + e->off, 128);
    else t_rep->dig = jr_fnv(jr_fnv(t_rep->dig, &cmd, 4), ctx->ls + lsa, 128);
    return 1;
}
void spu_jr_atomic_post(spu_context* ctx, uint32_t cmd)
{
    if (!t_cap) return;
    if (cmd != MFC_GETLLAR_CMD && cmd != MFC_PUTLLC_CMD && cmd != MFC_PUTLLUC_CMD && cmd != MFC_PUTQLLUC_CMD) return;
    const uint32_t lsa = ctx->mfc_lsa & SPU_LS_MASK & ~127u, ea = ctx->mfc_eal & ~127u;
    jr_add(t_cap, JR_ATOM, cmd, ea, lsa, cmd == MFC_GETLLAR_CMD ? ctx->ls + lsa : NULL, cmd == MFC_GETLLAR_CMD ? 128 : 0);
}
/* channel read / count: replay returns the logged value; capture logs it */
int spu_jr_rdch_pre(spu_context* ctx, uint32_t ch, u128* out)
{
    if (ch == SPU_RdEventStat && jr_spu_listed(ctx)) {   /* listed SPUs: an event wait ends the window */
        if (t_rep) jr_rep_stop(ctx);
        if (t_cap) jr_cap_end(ctx);
        t_in = 0;
        return 0;
    }
    if (!jr_window_check(ctx) || !t_rep) return 0;
    const jr_ev* e = jr_rep_next(ctx, JR_RDCH, ch, 0, 0);
    memcpy(out, t_rep->data + e->off, 16);
    return 1;
}
void spu_jr_rdch_post(spu_context* ctx, uint32_t ch, u128 v) { (void)ctx; if (t_cap) jr_add(t_cap, JR_RDCH, ch, 0, 0, &v, 16); }
int spu_jr_rchcnt_pre(spu_context* ctx, uint32_t ch, uint32_t* out)
{
    if (!jr_window_check(ctx) || !t_rep) return 0;
    const jr_ev* e = jr_rep_next(ctx, JR_RCHCNT, ch, 0, 0);
    *out = e->b;
    return 1;
}
void spu_jr_rchcnt_post(spu_context* ctx, uint32_t ch, uint32_t v) { (void)ctx; if (t_cap) jr_add(t_cap, JR_RCHCNT, ch, v, 0, NULL, 0); }
/* channel write: MFC parameter writes go through (they only set up the next command); the rest is
 * logged (capture) or digested and dropped (replay) -- a replay must not signal the PPU */
int spu_jr_wrch_pre(spu_context* ctx, uint32_t ch, u128 v)
{
    if (!jr_window_check(ctx)) return 0;
    const int mfc_param = ch == MFC_LSA || ch == MFC_EAH || ch == MFC_EAL || ch == MFC_Size || ch == MFC_TagID ||
                          ch == MFC_Cmd || ch == MFC_WrTagMask || ch == MFC_WrTagUpdate || ch == SPU_WrDec ||
                          ch == SPU_WrEventMask || ch == SPU_WrEventAck;
    if (mfc_param) return 0;
    if (t_cap) { jr_add(t_cap, JR_WRCH, ch, v._u32[0], 0, NULL, 0); t_cap->dig = jr_fnv(jr_fnv(t_cap->dig, &ch, 4), &v, 16); return 0; }
    jr_rep_next(ctx, JR_WRCH, ch, v._u32[0], 0);
    t_rep->dig = jr_fnv(jr_fnv(t_rep->dig, &ch, 4), &v, 16);
    return 1;
}

extern int spu_run_with_halt(void (*entry)(spu_context*), spu_context* ctx);
static jr_run* jr_load(const char* p, uint64_t* cap_dig, uint64_t* cap_fin)
{
    FILE* f = fopen(p, "rb"); if (!f) return 0;
    char m[4]; jr_run* r = (jr_run*)calloc(1, sizeof *r);
    int ok = fread(m, 1, 4, f) == 4 && !memcmp(m, "JRC1", 4) && fread(&r->ovl, 4, 1, f) == 1 && fread(&r->entry, 4, 1, f) == 1 &&
             fread(cap_dig, 8, 1, f) == 1 && fread(cap_fin, 8, 1, f) == 1 && fread(&r->nev, sizeof r->nev, 1, f) == 1;
    if (ok) { r->ev = (jr_ev*)malloc(r->nev * sizeof(jr_ev)); ok = fread(r->ev, sizeof(jr_ev), r->nev, f) == r->nev && fread(&r->ndata, sizeof r->ndata, 1, f) == 1; }
    if (ok) { r->data = (uint8_t*)malloc(r->ndata ? r->ndata : 1); ok = fread(r->data, 1, r->ndata, f) == r->ndata; }
    fclose(f);
    if (!ok || r->nev < 1 || r->ev[0].a != sizeof(spu_context)) { fprintf(stderr, "[jr-replay] %s: bad file (or another build's context size)\n", p); return 0; }
    return r;
}
#include <signal.h>
#include <sched.h>
#include <sys/wait.h>
static void jr_replay_all_(void);
/* Measure in isolation: a forked child (it has only this thread) freezes the game process (SIGSTOP), pins
 * itself to one CPU and replays; nothing else runs meanwhile. PS3_SPU_JR_NOFORK=1 = in place, as before. */
static void jr_replay_all(void)
{
    if (getenv("PS3_SPU_JR_NOFORK")) { jr_replay_all_(); return; }
    fflush(stderr);
    const pid_t parent = getpid();
    const pid_t c = fork();
    if (c == 0) {
        kill(parent, SIGSTOP);
        fprintf(stderr, "[jr-replay] isolated: child %d, game process %d stopped, pinned to cpu 2\n", (int)getpid(), (int)parent);
        cpu_set_t cs; CPU_ZERO(&cs); CPU_SET(2, &cs); sched_setaffinity(0, sizeof cs, &cs);
        jr_replay_all_();   /* ends with _exit */
    }
    if (c > 0) { int st; waitpid(c, &st, 0); kill(parent, SIGCONT); }
    _exit(0);
}
static void jr_replay_all_(void)
{
    DIR* d = opendir(s_rep_dir); if (!d) { fprintf(stderr, "[jr-replay] no dir %s\n", s_rep_dir); exit(2); }
    struct dirent* de; char names[512][300]; int n = 0;
    while ((de = readdir(d)) && n < 512) if (!strncmp(de->d_name, "jr_", 3)) snprintf(names[n++], 300, "%s/%s", s_rep_dir, de->d_name);
    closedir(d);
    for (int i = 0; i < n; i++) for (int j = i + 1; j < n; j++) if (strcmp(names[i], names[j]) > 0) { char t[300]; strcpy(t, names[i]); strcpy(names[i], names[j]); strcpy(names[j], t); }
    spu_context* ctx = (spu_context*)aligned_alloc(64, (sizeof(spu_context) + 63) & ~(size_t)63);
    spu_context* fresh = (spu_context*)aligned_alloc(64, (sizeof(spu_context) + 63) & ~(size_t)63);
    memset(fresh, 0, sizeof *fresh); spu_context_init(fresh, 0x7F);
    double tot_us = 0, tot_mc = 0, tot_mi = 0, tot_steps = 0;
    /* jr interp: PS3_SPU_JR_INTERP=1 runs each job on the pure interpreter (image -1): ctx->steps then counts
     * every SPU instruction executed -- with a lifted run's host instruction count, the expansion factor. In a
     * lifted run the same delta counts the dispatch steps (trampolines). */
    const char* ie = getenv("PS3_SPU_JR_INTERP"); const int interp = ie && *ie == '1';
    extern uint32_t spu_interp_run(spu_context* ctx, uint32_t start_lsa);
    const int fd_c = jr_pc_open(PERF_COUNT_HW_CPU_CYCLES), fd_i = jr_pc_open(PERF_COUNT_HW_INSTRUCTIONS);
    for (int i = 0; i < n; i++) {
        uint64_t cdig, cfin; jr_run* r = jr_load(names[i], &cdig, &cfin); if (!r) continue;
        uint64_t best = ~0ull, bestc = ~0ull, besti = ~0ull, dig = 0, fin = 0, steps = 0; uint32_t endpc = 0; size_t used = 0; int bad = 0; char why[160] = "";
        for (int k = 0; k < s_rep_reps; k++) {
            memcpy(ctx, r->data + r->ev[0].off, sizeof(spu_context));
            /* host pointers of the capture process mean nothing here: this process's wait objects,
             * no cached dispatch targets, no pending trampoline, no kernel instance */
            ctx->ch_wait_cv = fresh->ch_wait_cv; ctx->ch_wait_lock = fresh->ch_wait_lock;
            ctx->spurs_vspu = 0; ctx->irq_frame = 0; ctx->tramp_fn = 0; ctx->mfc_hint = 0;
            memset(ctx->ib_cache, 0, sizeof ctx->ib_cache);
            ctx->ls = ctx->ls_store;
            size_t first = 1;
            if (!r->ev[0].b) { ctx->ls = ctx->ls_store; memcpy(ctx->ls_store, r->data + r->ev[1].off, SPU_LS_SIZE); first = 2; }
            ctx->pc = r->entry; ctx->stop_request = 0;
            r->cur = first; r->dig = 1469598103934665603ull; r->mismatch = 0; r->why[0] = 0;
            t_rep = r; t_in = 1;
            if (interp) ctx->image_id = -1;
            const uint64_t s0 = ctx->steps;
            const uint64_t c0 = jr_pc_read(fd_c), i0 = jr_pc_read(fd_i), t0 = jr_ns();
            if (!setjmp(t_rep_env)) { if (interp) spu_interp_run(ctx, ctx->pc); else spu_run_with_halt(spu_indirect_branch, ctx); }
            steps = (uint32_t)((r->cur >= r->nev ? s_jr_last_steps : ctx->steps) - (uint32_t)s0);
            const uint64_t dt = jr_ns() - t0, dc = jr_pc_read(fd_c) - c0, di = jr_pc_read(fd_i) - i0;
            if (dc < bestc) bestc = dc;
            if (di < besti) besti = di;
            t_rep = 0; t_in = 0;
            if (dt < best) best = dt;
            dig = r->dig; endpc = ctx->pc & SPU_LS_MASK; used = r->cur;
            if (k == 0) fin = jr_fnv(jr_fnv(1469598103934665603ull, ctx->ls, SPU_LS_SIZE), ctx->gpr, sizeof ctx->gpr);
            if (r->mismatch) { bad = 1; strcpy(why, r->why); break; }
        }
        tot_us += best / 1e3; tot_mc += bestc / 1e6; tot_mi += besti / 1e6; tot_steps += (double)steps;
        fprintf(stderr, "[jr-replay] %s: img %d ovl %u entry 0x%05X: events %zu/%zu, event digest %016llX (capture %016llX%s), "
                "final %016llX, end pc 0x%05X, %.1f us, %llu instr, %llu steps%s%s\n", names[i], ((const spu_context*)(r->data + r->ev[0].off))->image_id, r->ovl, r->entry, used, r->nev,
                (unsigned long long)dig, (unsigned long long)cdig, dig == cdig ? " same" : " DIFFERENT",
                (unsigned long long)fin, endpc, best / 1e3, (unsigned long long)besti, (unsigned long long)steps, bad ? " MISMATCH: " : "", why);
        free(r->ev); free(r->data); free(r);
    }
    fprintf(stderr, "[jr-replay] %d files, total %.1f us, %.3f Mcycles, %.3f Minstructions (best of %d each), %.3f M %s steps\n", n, tot_us, tot_mc, tot_mi, s_rep_reps,
            tot_steps / 1e6, interp ? "SPU instruction" : "dispatch");
    fflush(stderr);
    _exit(0);
}
#else   /* PS5: capture/replay are BC-250 tools (directory listing etc. would add imports) */
int spu_jr_dma(spu_context* c, uint32_t l, uint64_t e, uint32_t s, uint32_t m) { (void)c; (void)l; (void)e; (void)s; (void)m; return 0; }
int spu_jr_atomic_pre(spu_context* c, uint32_t m) { (void)c; (void)m; return 0; }
void spu_jr_atomic_post(spu_context* c, uint32_t m) { (void)c; (void)m; }
int spu_jr_rdch_pre(spu_context* c, uint32_t ch, u128* o) { (void)c; (void)ch; (void)o; return 0; }
void spu_jr_rdch_post(spu_context* c, uint32_t ch, u128 v) { (void)c; (void)ch; (void)v; }
int spu_jr_rchcnt_pre(spu_context* c, uint32_t ch, uint32_t* o) { (void)c; (void)ch; (void)o; return 0; }
void spu_jr_rchcnt_post(spu_context* c, uint32_t ch, uint32_t v) { (void)c; (void)ch; (void)v; }
int spu_jr_wrch_pre(spu_context* c, uint32_t ch, u128 v) { (void)c; (void)ch; (void)v; return 0; }
static void jr_cfg(void) {}
static void jr_cap_begin(spu_context* c, uint32_t pc) { (void)c; (void)pc; }
static void jr_cap_end(spu_context* c) { (void)c; }
static void jr_rep_stop(spu_context* c) { (void)c; }
static void jr_replay_all(void) {}
static inline int jr_in_region(const spu_context* ctx, uint32_t pc) { pc &= SPU_LS_MASK; return pc >= 0x4000 && pc < 0x14000 && ctx->resident_ovl >= 200; }
static inline int jr_spu_listed(const spu_context* ctx) { (void)ctx; return 0; }
static int s_cap_left, s_cap_ovl, s_rep_mode; static double s_cap_skip; static int s_cap_busy; static uint64_t s_t_start;
static __thread void* t_cap; static __thread void* t_rep;
#endif

void spu_jr_dispatch(spu_context* ctx, uint32_t pc)
{
    jr_cfg();
    if (s_rep_mode == 1 && !t_rep) { s_rep_mode = 2; jr_replay_all(); }
    const int in = jr_in_region(ctx, pc);
    if (t_rep && !in) jr_rep_stop(ctx);
    if (in == t_in) return;
    const uint64_t now = jr_ns();
    if (in) {
        t_in = 1; t_ovl = ctx->resident_ovl; t_ent = pc; t_t0 = now;
        if (s_cap_left > 0 && (s_cap_ovl < 0 ? jr_spu_listed(ctx) : ctx->resident_ovl == s_cap_ovl) && !t_cap && (now - s_t_start) / 1e9 > s_cap_skip) {
            int z = 0;
            if (__atomic_compare_exchange_n(&s_cap_busy, &z, 1, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)) {
                if (s_cap_left-- > 0) jr_cap_begin(ctx, pc); else __atomic_store_n(&s_cap_busy, 0, __ATOMIC_RELEASE);
            }
        }
        return;
    }
    t_in = 0;
    if (t_cap) jr_cap_end(ctx);
    for (int i = 0; i < 128; i++) {
        if (s_jd[i].n && (s_jd[i].ovl != t_ovl || s_jd[i].ent != (uint32_t)t_ent)) continue;
        s_jd[i].ovl = t_ovl; s_jd[i].ent = t_ent;
        __atomic_add_fetch(&s_jd[i].n, 1, __ATOMIC_RELAXED); __atomic_add_fetch(&s_jd[i].ns, now - t_t0, __ATOMIC_RELAXED);
        break;
    }
    if (now - s_jd_last > 10000000000ull) {
        s_jd_last = now;
        for (int i = 0; i < 128; i++) if (s_jd[i].n && s_jd[i].ns > 20000000ull)
            fprintf(stderr, "[jr] job ovl %d entry 0x%05X: %lu runs, %.1f us each, %.0f ms total\n",
                    s_jd[i].ovl, s_jd[i].ent, s_jd[i].n, s_jd[i].ns / 1e3 / s_jd[i].n, s_jd[i].ns / 1e6);
    }
}

#ifndef __PROSPERO__
/* PGO collection (BC-250 only): an instrumented build (-fprofile-generate) writes its profile at a normal
 * exit, but the run scripts end the game with SIGKILL. PS3_PGO_DUMP_S=<n>: write it every n seconds.
 * Weak: in a normal build the profile runtime is absent and this does nothing. */
#include <pthread.h>
extern int __llvm_profile_write_file(void) __attribute__((weak));
static void* jr_pgo_thread(void* a)
{
    const unsigned n = (unsigned)(uintptr_t)a;
    for (;;) { sleep(n); __llvm_profile_write_file(); }
    return 0;
}
__attribute__((constructor)) static void jr_pgo_init(void)
{
    const char* e = getenv("PS3_PGO_DUMP_S");
    if (!e || !__llvm_profile_write_file) return;
    pthread_t t; pthread_create(&t, 0, jr_pgo_thread, (void*)(uintptr_t)(atoi(e) > 0 ? atoi(e) : 20));
    pthread_detach(t);
    fprintf(stderr, "[pgo] profile written every %d s\n", atoi(e) > 0 ? atoi(e) : 20);
}
#endif
