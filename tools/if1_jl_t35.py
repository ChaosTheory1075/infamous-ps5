#!/usr/bin/env python3
"""if1_jl_t35.py [IF1_LLE_DIR] -- inFAMOUS 1 job-list wait, t35 form: profile, lane spin, ready 6, jl stat, and the
SPURS max-contention workload-mask stand-down. Anchor-based (no lifted game code is carried here): it finds functions
by their guest address and our own earlier inserted lines, and inserts our code. Apply AFTER tools/if1_jl_wait.py and
tools/if1_spurs_prio8.py, BEFORE rewrite_vshuf.py. Needs the t35 toolkit (ps3_memkick_wait_pred, g_mkp_stat,
spu_sample_all, cellGcm_flip_request_count). Idempotent. Default dir: ${IF1_LLE_DIR:-~/if1/infamous2-lle}.
Equivalent to the t35 build's game patch (t35c_07g); switches: PS3_IF1_JLPROF, PS3_IF1_JL_SPIN_US, PS3_IF1_JL_READY,
PS3_IF1_JL_STAT, SPURS_MAXCONT_WKL (all default off)."""
import os, re, sys, pathlib

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("IF1_LLE_DIR", __import__("os").path.expanduser("~") + "/if1/infamous2-lle"))
f7 = root / "recompiled" / "ppu_recomp_007.cpp"
f15 = root / "recompiled" / "ppu_recomp_015.cpp"
fsre = root / "lle" / "libsre" / "libsre_recomp_000.cpp"

def rd(p):
    with open(p, newline="") as f:
        return f.read()
def wr(p, s):
    with open(p, "w", newline="") as f:
        f.write(s)

s7, s15, ssre = rd(f7), rd(f15), rd(fsre)
if "if1j_enter" in s7:
    print("if1 jl t35: already applied"); sys.exit(0)
assert "if1_jl_backoff" in s7, "apply tools/if1_jl_wait.py first"
assert "if1_prio8_to = 0;" in ssre, "apply tools/if1_spurs_prio8.py first"

HELPER = r'''
/* ==== if1 jl prof / lane spin / ready 6 (if1jobs notes, 2026-11-11) ==== */
#include <time.h>
extern "C" int ps3_memkick_wait_pred(uint64_t us, uint64_t spin_us, int (*done)(void*), void* arg);
extern "C" unsigned long g_mkp_stat[8];
extern "C" unsigned cellGcm_flip_request_count(void);
extern "C" int spu_sample_all(uint32_t* out, int max);
static inline uint64_t if1j_now(void)
{ struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec; }
static int if1j_env(const char* n, int lo, int hi)
{ const char* e = getenv(n); const int v = e && *e ? atoi(e) : 0; return v < lo ? 0 : v > hi ? hi : v; }
static int if1j_prof(void)
{ static int v = -1; if (v < 0) { v = if1j_env("PS3_IF1_JLPROF", 1, 1); if (v) fprintf(stderr, "[if1 jl] profile on\n"); } return v; }
static int if1j_spin(void)
{ static int v = -1; if (v < 0) { v = if1j_env("PS3_IF1_JL_SPIN_US", 1, 200); if (v) fprintf(stderr, "[if1 jl] lane spin %d us\n", v); } return v; }
static int if1j_ready(void)
{ static int v = -1; if (v < 0) { v = if1j_env("PS3_IF1_JL_READY", 6, 6); if (v) fprintf(stderr, "[if1 jl] ready count 5 -> %d where max contention allows\n", v); } return v; }

/* if1 jl stat (if1spu, if1stack notes): one "[if1 jl stat]" line per 300 presents while PS3_IF1_JL_STAT=1,
 * PS3_IF1_JL_SPIN_US or PS3_IF1_JL_READY is set: lists waited for, guest polls per list, wait calls ("spin returns")
 * per frame and how the lane-spin waits ended, kicks raised to 6, and per SPU lane 0..5 the number of distinct job
 * indices main saw in that lane while it polled (a lower bound of the jobs each SPU number ran for the waited
 * lists; lane 5 > 0 = the sixth SPU takes job-list work). Main-thread only code; reads only. */
static int if1j_stat(void)
{ static int v = -1; if (v < 0) { v = if1j_env("PS3_IF1_JL_STAT", 1, 1) || if1j_spin() || if1j_ready();
                                  if (v) fprintf(stderr, "[if1 jl stat] on\n"); } return v; }
static unsigned long s_if1s_lists, s_if1s_polls, s_if1s_waits, s_if1s_lane[6], s_if1s_raised, s_if1s_mkp0[8];
static unsigned s_if1s_f0; static int s_if1s_busy;
struct if1j_pred { uint32_t rec, tgt; int obs; uint16_t last[6]; };
static inline void if1j_observe(if1j_pred* p)   /* if1 jl stat: a new job index in a lane = one more job seen there */
{
    for (int i = 0; i < 6; i++) {
        const uint16_t v = (uint16_t)vm_read16(p->rec + 4u + 2u * (uint32_t)i);
        if (v != p->last[i]) { p->last[i] = v; if (v != 0xFFFFu) __atomic_add_fetch(&s_if1s_lane[i], 1ul, __ATOMIC_RELAXED); }
    }
}
/* = func_0041D028(jl, 3, tgt): min of the u16 at rec+2..rec+0xE >= tgt, unsigned, as the guest compares */
static int if1j_done(void* a)
{
    if1j_pred* p = (if1j_pred*)a;
    if (p->obs) if1j_observe(p);
    uint32_t m = vm_read16(p->rec + 2);
    for (uint32_t o = 4; o <= 0xE; o += 2) { const uint32_t v = vm_read16(p->rec + o); if (v < m) m = v; }
    return m >= p->tgt;
}
static void if1j_stat_report(void)
{
    const unsigned f = cellGcm_flip_request_count();
    if (!s_if1s_f0) { s_if1s_f0 = f ? f : 1u; return; }
    const unsigned nf = f - s_if1s_f0;
    if (nf < 300u || __atomic_exchange_n(&s_if1s_busy, 1, __ATOMIC_ACQUIRE)) return;
    s_if1s_f0 = f;
    unsigned long d[8]; for (int k = 0; k < 8; k++) { const unsigned long v = __atomic_load_n(&g_mkp_stat[k], __ATOMIC_RELAXED); d[k] = v - s_if1s_mkp0[k]; s_if1s_mkp0[k] = v; }
    unsigned long ln[6]; for (int i = 0; i < 6; i++) ln[i] = __atomic_exchange_n(&s_if1s_lane[i], 0ul, __ATOMIC_RELAXED);
    const unsigned long L = __atomic_exchange_n(&s_if1s_lists, 0ul, __ATOMIC_RELAXED), P = __atomic_exchange_n(&s_if1s_polls, 0ul, __ATOMIC_RELAXED),
                        W = __atomic_exchange_n(&s_if1s_waits, 0ul, __ATOMIC_RELAXED), R = __atomic_exchange_n(&s_if1s_raised, 0ul, __ATOMIC_RELAXED);
    const double fr = nf;
    fprintf(stderr, "[if1 jl stat] last %u presents: lists %.1f/frame, polls/list %.1f, wait returns %.0f/frame | lane spin (%d us): "
                    "%.0f/frame ended by completion in spin %.0f, after sleep: re-check %.0f woken %.0f timeout %.0f, spin %.2f ms/frame sleep %.2f ms/frame "
                    "| kicks raised to 6 %.1f/frame | jobs seen per lane 0-5: %lu %lu %lu %lu %lu %lu (lane 5 %.1f%%)\n",
            nf, L / fr, L ? (double)P / L : 0.0, W / fr, if1j_spin(), d[0] / fr, d[1] / fr, d[3] / fr, d[4] / fr, d[5] / fr,
            d[6] / 1e6 / fr, d[7] / 1e6 / fr, R / fr, ln[0], ln[1], ln[2], ln[3], ln[4], ln[5],
            100.0 * ln[5] / (double)((ln[0] + ln[1] + ln[2] + ln[3] + ln[4] + ln[5]) ? (ln[0] + ln[1] + ln[2] + ln[3] + ln[4] + ln[5]) : 1));
    __atomic_store_n(&s_if1s_busy, 0, __ATOMIC_RELEASE);
}
struct if1j_call { uint64_t t0, t_lanes, t_samp, t_ff, tk; uint32_t jl, inst, wid, lr, f0, fk; if1j_pred p; int on; };
struct if1j_site { uint32_t lr, inst, wid; unsigned long calls, waited, wait_ns, join_ns, max_ns, out_sum, age_n, age_ns, ff_n, ff_ns; };
struct if1j_kick { uint32_t jl, f; uint64_t t; };
#define IF1J_SITES 12
static if1j_site s_if1j_site[IF1J_SITES];
static if1j_kick s_if1j_kicks[64];
static unsigned long s_if1j_kc[4];                 /* kicks, value 5, raised, not raised (max contention < 6) */
static unsigned long s_if1j_ns, s_if1j_busy[9], s_if1j_onw[9], s_if1j_img_on[512], s_if1j_img_other[512];
static uint64_t s_if1j_t_rep; static unsigned s_if1j_f_rep; static int s_if1j_rep_busy;
static unsigned long s_if1j_mkp0[8];

static void if1j_report(uint64_t t)
{
    const double sec = (double)(t - s_if1j_t_rep) / 1e9;
    const unsigned fr = cellGcm_flip_request_count(), nf = fr - s_if1j_f_rep;
    s_if1j_t_rep = t; s_if1j_f_rep = fr;
    const double fps = nf / sec;
    unsigned long calls = 0, waited = 0, wns = 0, jns = 0, mx = 0;
    for (int i = 0; i < IF1J_SITES; i++) { const if1j_site* s = &s_if1j_site[i]; calls += s->calls; waited += s->waited; wns += s->wait_ns; jns += s->join_ns; if (s->max_ns > mx) mx = s->max_ns; }
    fprintf(stderr, "[if1 jl] %.1f s, %.1f fps: %.0f calls/s (%.1f/frame, %.0f/s had to wait), lane wait %.1f ms/s = %.2f ms/frame, join %.2f ms/s, longest %.2f ms\n",
            sec, fps, calls / sec, calls / (nf ? nf : 1.0), waited / sec, wns / sec / 1e6, wns / 1e6 / (nf ? nf : 1), jns / sec / 1e6, mx / 1e6);
    for (int i = 0; i < IF1J_SITES; i++) {
        if1j_site* s = &s_if1j_site[i];
        if (!s->calls) continue;
        fprintf(stderr, "[if1 jl] site lr %08X spurs %08X wid %u: %.0f/s %.2f/frame, %.1f ms/s avg %.0f us max %.0f us, join %.1f ms/s, not taken at entry %.1f jobs, kick->entry %.0f us (%lu), kick->first job %.0f us (%lu)\n",
                s->lr, s->inst, s->wid, s->calls / sec, s->calls / (nf ? nf : 1.0), s->wait_ns / sec / 1e6, s->wait_ns / 1e3 / s->calls, s->max_ns / 1e3,
                s->join_ns / sec / 1e6, (double)s->out_sum / s->calls, s->age_n ? s->age_ns / 1e3 / s->age_n : 0.0, s->age_n,
                s->ff_n ? s->ff_ns / 1e3 / s->ff_n : 0.0, s->ff_n);
        s->calls = s->waited = s->wait_ns = s->join_ns = s->max_ns = s->out_sum = s->age_n = s->age_ns = s->ff_n = s->ff_ns = 0;
    }
    if (s_if1j_ns) {
        char a[160], b[160]; int pa = 0, pb = 0;
        for (int k = 0; k <= 8; k++) { pa += snprintf(a + pa, sizeof a - pa, " %d:%.0f%%", k, 100.0 * s_if1j_busy[k] / s_if1j_ns);
                                       pb += snprintf(b + pb, sizeof b - pb, " %d:%.0f%%", k, 100.0 * s_if1j_onw[k] / s_if1j_ns); }
        fprintf(stderr, "[if1 jl] spus while main waits (%lu snapshots): busy in the waited instance%s | on the waited list%s\n", s_if1j_ns, a, b);
        for (int pass = 0; pass < 2; pass++) {
            unsigned long* h = pass ? s_if1j_img_other : s_if1j_img_on, tot = 0;
            for (int k = 0; k < 512; k++) tot += h[k];
            char l[400]; int pl = 0; l[0] = 0;
            for (int r = 0; r < 10 && tot; r++) {
                int best = -1; for (int k = 0; k < 512; k++) if (h[k] && (best < 0 || h[k] > h[best])) best = k;
                if (best < 0) break;
                pl += snprintf(l + pl, sizeof l - pl, " img%d %.1f%%", best, 100.0 * h[best] / tot);
                h[best] = 0;
            }
            fprintf(stderr, "[if1 jl] images %s (SPU-snapshots %lu):%s\n", pass ? "running OTHER workloads" : "running the waited list", tot, l);
            memset(h, 0, 512 * sizeof *h);
        }
        s_if1j_ns = 0; memset(s_if1j_busy, 0, sizeof s_if1j_busy); memset(s_if1j_onw, 0, sizeof s_if1j_onw);
    }
    fprintf(stderr, "[if1 jl] kicks %.0f/s: value 5 %.0f/s, raised to 6 %.0f/s, left (max contention < 6) %.0f/s\n",
            s_if1j_kc[0] / sec, s_if1j_kc[1] / sec, s_if1j_kc[2] / sec, s_if1j_kc[3] / sec);
    memset(s_if1j_kc, 0, sizeof s_if1j_kc);
    unsigned long d[8]; for (int k = 0; k < 8; k++) { d[k] = g_mkp_stat[k] - s_if1j_mkp0[k]; s_if1j_mkp0[k] = g_mkp_stat[k]; }
    if (d[0])
        fprintf(stderr, "[if1 jl] lane spin: %.0f waits/s = spin-hit %.0f/s, spin-miss %.0f/s (spin %.1f ms/s) -> re-check hit %.0f/s, woken %.0f/s, timed out %.0f/s (sleep %.1f ms/s)\n",
                d[0] / sec, d[1] / sec, d[2] / sec, d[6] / sec / 1e6, d[3] / sec, d[4] / sec, d[5] / sec, d[7] / sec / 1e6);
}
static if1j_site* if1j_site_of(uint32_t lr)
{
    for (int i = 0; i < IF1J_SITES; i++) {
        uint32_t cur = __atomic_load_n(&s_if1j_site[i].lr, __ATOMIC_RELAXED);
        if (cur == lr) return &s_if1j_site[i];
        if (!cur && __atomic_compare_exchange_n(&s_if1j_site[i].lr, &cur, lr, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED)) return &s_if1j_site[i];
        if (cur == lr) return &s_if1j_site[i];
    }
    return &s_if1j_site[IF1J_SITES - 1];   /* overflow: lumped into the last row */
}
static inline void if1j_enter(ppu_context* ctx, if1j_call* c)
{
    c->on = if1j_prof() | (if1j_spin() ? 2 : 0) | (if1j_stat() ? 4 : 0);
    if (!c->on) return;
    const uint32_t jl = (uint32_t)ctx->gpr[3];
    c->jl = jl;
    c->p.rec = vm_read32(jl) + 0x70u;             /* the guest's own reads (func_0041D028) */
    c->p.tgt = vm_read16(jl + 0x2A);
    c->p.obs = (c->on & 4) != 0;                  /* if1 jl stat */
    for (int i = 0; i < 6; i++) c->p.last[i] = (uint16_t)vm_read16(c->p.rec + 4u + 2u * (uint32_t)i);
    if (!(c->on & 1)) return;
    c->t0 = c->t_samp = if1j_now(); c->t_ff = 0; c->t_lanes = 0;
    c->lr = (uint32_t)ctx->lr; c->inst = vm_read32(jl + 4); c->wid = vm_read32(jl + 8);
    c->f0 = vm_read16(c->p.rec + 2);
    const if1j_kick* k = &s_if1j_kicks[(jl >> 4) & 63];
    c->tk = 0;
    if (__atomic_load_n(&k->jl, __ATOMIC_RELAXED) == jl) { c->tk = k->t; c->fk = k->f; }
}
static void if1j_sample(if1j_call* c, unsigned n)
{
    const uint64_t t = if1j_now();
    if ((n & 15u) || t - c->t_samp < 20000ull) return;
    c->t_samp = t;
    uint32_t s[6 * 24];
    const int k = spu_sample_all(s, 24);
    int busy = 0, onw = 0;
    for (int i = 0; i < k; i++) {
        const uint32_t* o = s + 6 * i;
        if (o[1] == 8u || o[3] != c->inst || o[5] >= 0x20u) continue;   /* parked, another instance, or no workload */
        busy++;
        if (o[5] == c->wid) { onw++; s_if1j_img_on[o[2] & 511u]++; } else s_if1j_img_other[o[2] & 511u]++;
    }
    s_if1j_ns++; s_if1j_busy[busy > 8 ? 8 : busy]++; s_if1j_onw[onw > 8 ? 8 : onw]++;
}
static inline void if1j_backoff(unsigned* n, if1j_call* c)
{
    if ((c->on & 1) && !c->t_ff && vm_read16(c->p.rec + 2) != c->f0) c->t_ff = if1j_now();   /* first job taken after entry */
    if (c->on & 4) if1j_observe(&c->p);            /* if1 jl stat */
    if (++*n < 64u) return;
    if (c->on & 1) if1j_sample(c, *n);
    const int us = if1_jl_wait_us();
    if (us <= 0) return;                            /* PS3_IF1_JL_WAIT_US=0: the plain spin of before */
    if (c->on & 4) __atomic_add_fetch(&s_if1s_waits, 1ul, __ATOMIC_RELAXED);
    if (c->on & 2) ps3_memkick_wait_pred((uint64_t)us, (uint64_t)if1j_spin(), if1j_done, &c->p);
    else ps3_memkick_wait((uint64_t)us);
}
static inline void if1j_lanes_done(if1j_call* c) { if (c->on & 1) c->t_lanes = if1j_now(); }
static void if1j_exit(if1j_call* c, unsigned n)
{
    if (c->on & 4) {                                /* if1 jl stat */
        if1j_observe(&c->p);
        __atomic_add_fetch(&s_if1s_lists, 1ul, __ATOMIC_RELAXED);
        __atomic_add_fetch(&s_if1s_polls, (unsigned long)n + 1ul, __ATOMIC_RELAXED);
        if1j_stat_report();
    }
    if (!(c->on & 1)) return;
    const uint64_t t = if1j_now();
    if1j_site* s = if1j_site_of(c->lr);
    s->inst = c->inst; s->wid = c->wid;
    const uint64_t w = c->t_lanes - c->t0;
    s->calls++; if (n) s->waited++;
    s->wait_ns += w; s->join_ns += t - c->t_lanes; if (w > s->max_ns) s->max_ns = w;
    const int out = (int16_t)(uint16_t)(c->p.tgt - c->f0);
    s->out_sum += out > 0 ? (unsigned long)out : 0ul;
    if (c->tk && c->tk <= c->t0) {
        s->age_n++; s->age_ns += c->t0 - c->tk;
        if (c->t_ff && c->f0 == c->fk) { s->ff_n++; s->ff_ns += c->t_ff - c->tk; }
    }
    if (!s_if1j_t_rep) { s_if1j_t_rep = t; s_if1j_f_rep = cellGcm_flip_request_count(); return; }
    if (t - s_if1j_t_rep >= 10000000000ull && !__atomic_exchange_n(&s_if1j_rep_busy, 1, __ATOMIC_ACQUIRE)) {
        if1j_report(t);
        __atomic_store_n(&s_if1j_rep_busy, 0, __ATOMIC_RELEASE);
    }
}
/* the kick: func_0041D50C / func_0041D510 (jl, value) -> cellSpursReadyCountStore(*(jl+4), *(jl+8), value) */
extern "C" void if1_jl_kick_hook(ppu_context* ctx)
{
    const int pr = if1j_prof(), rd = if1j_ready();
    if (!pr && !rd) return;
    const uint32_t jl = (uint32_t)ctx->gpr[3], v = (uint32_t)ctx->gpr[5];
    if (pr) { __atomic_add_fetch(&s_if1j_kc[0], 1, __ATOMIC_RELAXED); if (v == 5u) __atomic_add_fetch(&s_if1j_kc[1], 1, __ATOMIC_RELAXED); }
    if (rd && v == 5u) {
        const uint32_t sp = vm_read32(jl + 4), wid = vm_read32(jl + 8);
        if (sp && wid < 16u && (uint32_t)(vm_read8(sp + 0x50u + wid) & 15u) >= (uint32_t)rd) {
            ctx->gpr[5] = (uint64_t)rd;
            __atomic_add_fetch(&s_if1s_raised, 1ul, __ATOMIC_RELAXED);   /* if1 jl stat */
            if (pr) __atomic_add_fetch(&s_if1j_kc[2], 1, __ATOMIC_RELAXED);
        } else if (pr) __atomic_add_fetch(&s_if1j_kc[3], 1, __ATOMIC_RELAXED);
    }
    if (pr && v) {
        const uint32_t b = vm_read32(jl);
        if (b >= 0x10000u && b < 0xE0000000u) {
            if1j_kick* k = &s_if1j_kicks[(jl >> 4) & 63];
            k->f = vm_read16(b + 0x72u); k->t = if1j_now();
            __atomic_store_n(&k->jl, jl, __ATOMIC_RELEASE);
        }
    }
}
'''
SRE = r'''    /* spurs maxcont wkl mask (spu6 notes): the workload id is not known yet at attribute init, so with
     * SPURS_MAXCONT_WKL set this hook stands down and the runtime's fixup thread (lv2_register.c) widens only the
     * masked workloads (within 50 ms of their creation). */
    { const char* m = getenv("SPURS_MAXCONT_WKL"); if (m && *m) if1_prio8_to = 0; }
'''

def func_span(s, name):
    h = "void %s(ppu_context* ctx) {\n" % name
    assert s.count(h) == 1, name + " not found once"
    i = s.index(h)
    return i, s.index("\n}\n", i), h

# 1. func_0041FC38 (the wait): helper before it, four of our lines inside it
i, e, h = func_span(s7, "func_0041FC38")
body = s7[i:e]
old_n = "        unsigned _jl_n = 0;   /* if1 jl wait */\n"
old_b = re.compile(r"^(        if \(.*\)\) )\{ if1_jl_backoff\(&_jl_n\); (goto loc_[0-9A-F]+;) \}\n", re.M)
call = re.compile(r"^        ctx->lr = 0x[0-9A-F]+; func_0041DC00\(ctx\); DRAIN_TRAMPOLINE\(ctx\);\n", re.M)
assert body.count(old_n) == 1, "func_0041FC38: if1 jl wait counter not found once"
assert len(old_b.findall(body)) == 1, "func_0041FC38: if1 jl wait backoff not found once"
assert len(call.findall(body)) == 1, "func_0041FC38: the func_0041DC00 call not found once"
body = body.replace(old_n, old_n + "        if1j_call _jc; if1j_enter(ctx, &_jc);   /* if1 jl prof */\n")
body = old_b.sub(lambda m: m.group(1) + "{ if1j_backoff(&_jl_n, &_jc); " + m.group(2) + " }   /* if1 jl prof */\n", body)
body = call.sub(lambda m: "        if1j_lanes_done(&_jc);   /* if1 jl prof */\n" + m.group(0) + "        if1j_exit(&_jc, _jl_n);   /* if1 jl prof */\n", body)
s7 = s7[:i] + HELPER + body + s7[e:]

# 2. the two kick functions: declaration before, hook after the r5 = r4 copy (the "value" argument)
DECL = 'extern "C" void if1_jl_kick_hook(ppu_context* ctx);   /* if1 jl prof (defined in ppu_recomp_007.cpp) */\n'
KICK = re.compile(r"^        ctx->gpr\[5\] = ctx->gpr\[4\] \| ctx->gpr\[4\];\n", re.M)
def hook(s, name):
    i, e, h = func_span(s, name)
    body = s[i:e]
    assert len(KICK.findall(body)) == 1, name + ": r5 copy not found once"
    body = KICK.sub(lambda m: m.group(0) + "        if1_jl_kick_hook(ctx);   /* if1 jl prof / ready 6 */\n", body)
    return s[:i] + DECL + body + s[e:]
s7 = hook(s7, "func_0041D50C")
s15 = hook(s15, "func_0041D510")

# 3. libsre: SPURS_MAXCONT_WKL stands the prio8 hook down (after our own tools/if1_spurs_prio8.py line)
A = "    else if1_prio8_to = 0;\n"
assert ssre.count(A) == 1, "libsre: if1_spurs_prio8 anchor not found once"
ssre = ssre.replace(A, A + SRE)

wr(f7, s7); wr(f15, s15); wr(fsre, ssre)
print("if1 jl t35: applied to", f7, f15, fsre)
