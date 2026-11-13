# eng texhash async: the per-frame texture change hashes on a helper thread. Every texture the RSX thread
# uses is checked once a frame (sparse hash every frame, full every 8th or always when small) -- ~2.1 ms of
# the RSX thread a heavy inFAMOUS 1 frame (680 textures, 10 MB), ~8% of its drain (2026-11-06). Now the RSX
# thread queues each texture it checks; at the frame's end the list goes to a helper that hashes them while
# the next frame runs. A texture whose helper result (<= 2 frames old, same slot generation) says
# "unchanged" is not hashed by the RSX thread; any other result -- changed, missing, stale -- takes the old
# synchronous path, which confirms and re-uploads. A rewrite is therefore seen 1-2 frames later than before.
# Results are published per slot under a sequence counter. PS3RECOMP_ENG_TEXHASH_ASYNC=1 (live toggle).
import sys
C = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_draw_engine.c"
H = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/include/ps3emu/ps3_toggles.h"
c = open(C).read(); h = open(H).read()
if "eng texhash async" in c: print("already"); sys.exit(0)
def edit(s, old, new):
    if s.count(old) != 1: print("NOT FOUND/UNIQUE:", old[:80]); sys.exit(1)
    return s.replace(old, new)

h = edit(h, '''    PS3T_ENG_DRAW_FAST,      /* rsx_draw_engine.c: any draw replayed from the previous one (eng draw fast) */
    PS3T_COUNT''', '''    PS3T_ENG_DRAW_FAST,      /* rsx_draw_engine.c: any draw replayed from the previous one (eng draw fast) */
    PS3T_ENG_TEXHASH_ASYNC,  /* rsx_draw_engine.c: texture change hashes on a helper thread */
    PS3T_COUNT''')
h = edit(h, '''        { "PS3RECOMP_ENG_DRAW_FAST",    PS3_TK_ATOI, 0 },''', '''        { "PS3RECOMP_ENG_DRAW_FAST",    PS3_TK_ATOI, 0 },
        { "PS3RECOMP_ENG_TEXHASH_ASYNC", PS3_TK_ATOI, 0 },''')

c = edit(c, '''    u8 th_stable;               /* eng texhash stable: full hashes in a row that matched */''',
'''    u8 th_stable;               /* eng texhash stable: full hashes in a row that matched */
    u32 th_gen;                 /* eng texhash async: this slot's texture, for the helper's results */''')

# the helper, before the content-hash function's first caller
c = edit(c, '''static volatile int s_th_stable = 0;''', '''/* eng texhash async: jobs (RSX thread -> helper) and per-slot results (helper -> RSX thread) */
typedef struct { u32 slot, gen, location, offset, span, frame; u8 full; } eng_tha_job;
typedef struct { volatile u32 seq; u32 gen, frame; u64 sparse, full; u8 has_full, readable; } eng_tha_res;
static eng_tha_job s_tha_q[2][RSX_DRAW_ENGINE_TEXTURE_CACHE * 2u];
static u32 s_tha_n[2], s_tha_fill;                 /* list being filled by the RSX thread, its count */
static eng_tha_res s_tha_res[RSX_DRAW_ENGINE_TEXTURE_CACHE];
static pthread_mutex_t s_tha_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t s_tha_cv = PTHREAD_COND_INITIALIZER;
static int s_tha_ready, s_tha_busy, s_tha_started;   /* a list handed over / being hashed */
static volatile int s_tha_on = -1;
static unsigned s_tha_skipped, s_tha_sync;
static void eng_tha_set(int id, int v) { (void)id; __atomic_store_n(&s_tha_on, v > 0, __ATOMIC_RELAXED); }
static u64 eng_texture_content_hash(u32 location, u32 offset, u32 span, int* readable);
static u64 eng_texture_sparse_hash(u32 location, u32 offset, u32 span, int* readable);
static void* eng_tha_main(void* arg)
{
    (void)arg;
    for (;;) {
        pthread_mutex_lock(&s_tha_mu);
        while (!s_tha_ready) pthread_cond_wait(&s_tha_cv, &s_tha_mu);
        const u32 list = (u32)(s_tha_ready - 1); s_tha_ready = 0; s_tha_busy = 1;
        pthread_mutex_unlock(&s_tha_mu);
        for (u32 i = 0; i < s_tha_n[list]; i++) {
            const eng_tha_job* j = &s_tha_q[list][i];
            int rd = 0, rd2 = 1;
            const u64 sp = eng_texture_sparse_hash(j->location, j->offset, j->span, &rd);
            const u64 fu = j->full ? eng_texture_content_hash(j->location, j->offset, j->span, &rd2) : 0;
            eng_tha_res* r = &s_tha_res[j->slot];
            const u32 s = __atomic_load_n(&r->seq, __ATOMIC_RELAXED);
            __atomic_store_n(&r->seq, s + 1u, __ATOMIC_RELEASE);   /* odd: being written */
            __atomic_thread_fence(__ATOMIC_RELEASE);
            r->gen = j->gen; r->frame = j->frame; r->sparse = sp; r->full = fu;
            r->has_full = (u8)(j->full && rd2); r->readable = (u8)(rd != 0);
            __atomic_store_n(&r->seq, s + 2u, __ATOMIC_RELEASE);
        }
        pthread_mutex_lock(&s_tha_mu); s_tha_busy = 0; pthread_mutex_unlock(&s_tha_mu);
    }
    return NULL;
}
static int eng_tha_on(void)
{
    if (__builtin_expect(s_tha_on < 0, 0)) {
        const char* e = getenv("PS3RECOMP_ENG_TEXHASH_ASYNC"); const int v = e && *e == '1';
        __atomic_store_n(&s_tha_on, v, __ATOMIC_RELAXED);
        ps3_toggle_watch(PS3T_ENG_TEXHASH_ASYNC, eng_tha_set);
        if (v) __atomic_store_n(&s_tha_on, 1, __ATOMIC_RELAXED);
    }
    const int on = __atomic_load_n(&s_tha_on, __ATOMIC_RELAXED);
    if (on && !s_tha_started) {
        s_tha_started = 1;
        pthread_t t; pthread_attr_t a; pthread_attr_init(&a); pthread_attr_setstacksize(&a, 256u << 10);
        if (pthread_create(&t, &a, eng_tha_main, NULL) == 0) pthread_detach(t); else s_tha_started = -1;
        pthread_attr_destroy(&a);
    }
    return on && s_tha_started > 0;
}
/* Frame end: hand this frame's list to the helper unless it is still busy (then the list is dropped and
 * those textures simply take the synchronous path next frame). */
static void eng_tha_frame_end(void)
{
    if (s_tha_started <= 0) return;
    const u32 f = s_tha_fill;
    pthread_mutex_lock(&s_tha_mu);
    if (!s_tha_busy && !s_tha_ready) { s_tha_ready = (int)f + 1; s_tha_fill ^= 1u; pthread_cond_signal(&s_tha_cv); }
    pthread_mutex_unlock(&s_tha_mu);
    s_tha_n[s_tha_fill] = 0;
    { static u32 n; if (++n % 600u == 0) { fprintf(stderr, "[texhash async] last 600 frames: %u checks answered by the helper, %u synchronous\\n", s_tha_skipped, s_tha_sync); s_tha_skipped = s_tha_sync = 0; } }
}

static volatile int s_th_stable = 0;''')

# texture creation: a generation for the slot
c = edit(c, '''    e.last_use_serial = ++g.texture_use_serial;
    const uint64_t ft_u0 = PS3_FT_ON() ? ps3_ft_now() : 0;''', '''    e.last_use_serial = ++g.texture_use_serial;
    { static u32 gen; e.th_gen = ++gen; }   /* eng texhash async */
    const uint64_t ft_u0 = PS3_FT_ON() ? ps3_ft_now() : 0;''')

# the per-frame check: try the helper's result first, queue the next job
c = edit(c, '''        if (e->handle && e->last_hash_frame != g.frames) {
            /* Every cached texture used to be hashed in full every frame:''', '''        if (e->handle && e->last_hash_frame != g.frames && eng_tha_on()) {   /* eng texhash async */
            const u32 slot = (u32)(e - g.textures);
            const eng_tha_res* r = &s_tha_res[slot];
            const u32 s0 = __atomic_load_n(&r->seq, __ATOMIC_ACQUIRE);
            const u32 rg = r->gen, rf = r->frame; const u64 rs = r->sparse, rfu = r->full; const u8 rh = r->has_full, rr = r->readable;
            __atomic_thread_fence(__ATOMIC_ACQUIRE);
            const int clean = !(s0 & 1u) && __atomic_load_n(&r->seq, __ATOMIC_ACQUIRE) == s0 && s0;
            const int full_due = span <= 16384u || g.frames - e->last_full_frame >= 8u;
            if (clean && rg == e->th_gen && rr && g.frames - rf <= 2u && rs == e->sparse_hash &&
                (!rh || rfu == e->content_hash) && (rh || !full_due || g.frames - e->last_full_frame < 16u)) {
                e->last_hash_frame = g.frames;   /* the helper saw it unchanged */
                if (rh) e->last_full_frame = rf;
                s_tha_skipped++;
            } else s_tha_sync++;
            if (s_tha_n[s_tha_fill] < RSX_DRAW_ENGINE_TEXTURE_CACHE * 2u) {
                eng_tha_job* j = &s_tha_q[s_tha_fill][s_tha_n[s_tha_fill]++];
                j->slot = slot; j->gen = e->th_gen; j->location = location; j->offset = offset; j->span = span;
                j->frame = g.frames; j->full = (u8)full_due;
            }
        }
        if (e->handle && e->last_hash_frame != g.frames) {
            /* Every cached texture used to be hashed in full every frame:''')

c = edit(c, '''    g.frames++;
    s_icon_gen = rsx_button_icons_frame();''', '''    eng_tha_frame_end();   /* eng texhash async */
    g.frames++;
    s_icon_gen = rsx_button_icons_frame();''')
open(C, "w").write(c); open(H, "w").write(h); print("patched")
