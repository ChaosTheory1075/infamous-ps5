/*
 * ps3_toggles -- performance and debug knobs that change while the game runs.
 *
 * PS3_TOGGLE_FILE=<path> names a small text file that the port re-reads while
 * it runs (ps3_toggles_poll(), libs/misc/ps3_toggles.c, called from a thread
 * that runs every frame; between changes it costs one stat() every 250 ms).
 * One `NAME=value` per line, `#` starts a comment, NAME is the knob's own
 * environment variable:
 *
 *     PS3RECOMP_ENG_VCACHE=0
 *     PS3RECOMP_ENG_SKIP_FP=5f740845528b0e62     # a list: the whole value
 *     PS3_SHARPEN=0.5
 *
 * A knob the file names overrides its environment value; a knob the file no
 * longer names goes back to it. In the file a 0/1 knob takes a number (so
 * PS3RECOMP_ENG_TEXHASH_FULL=0 is off there, while in the environment any
 * value turns it on, as before). Every change logs `[toggle] NAME old -> new`,
 * and while PS3_FTRACE records it leaves a PS3_FT_TOGGLE mark, so
 * tools/ftrace_report.py --phases can split ONE run's frames into A and B:
 * the same scene at the same moment instead of two runs that drift apart.
 *
 * Without PS3_TOGGLE_FILE nothing changes: each knob is read from its
 * environment variable once, with the parsing it always had, into the same
 * module-local int its hot path always read. ps3_toggle_watch() registers a
 * callback that rewrites that int when the file changes the knob; the hot
 * path itself never looks at this header's state and never parses anything.
 *
 * Header-only state (one weak object, as in ps3_ftrace.h): the files that read
 * these knobs are also compiled on their own by self-contained tests, and a
 * new link dependency would break each of them. Only the poll lives in a .c.
 *
 * Not live (read once, as before): PS3RECOMP_ENG_GPU_LIGHT / GPU_SSAO (they
 * swap SPU job code with spu_replace_function while SPUs may be inside it),
 * PS3_UPSCALE (it resizes the drawable on the main thread), the pacing and
 * window knobs.
 */
#ifndef PS3EMU_PS3_TOGGLES_H
#define PS3EMU_PS3_TOGGLES_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

/* The live knobs. ftrace_report.py has the same list (TOGGLE_NAMES): append
 * only, so old traces keep their meaning. */
enum ps3_toggle_id {
    PS3T_ENG_VCACHE = 0,     /* rsx_draw_engine.c: cross-frame vertex cache       */
    PS3T_ENG_TEXHASH_FULL,   /* rsx_draw_engine.c: full texture re-hash per frame */
    PS3T_ENG_SKIP_FP,        /* rsx_draw_engine.c: fragment programs to skip      */
    PS3T_SPU_FASTJOB,        /* spu_channels.c: job overlays on the fast dispatch */
    PS3T_SPU_STUB_MICRO,     /* spu_channels.c: WWS interrupt stub microstepper   */
    PS3T_SPU_STACK_HINT,     /* spu_channels.c: stack-reset hint table            */
    PS3T_SPU_DRAIN_INLINE,   /* spu_drain.c: the launch check inline in the drain */
    PS3T_DISPLAY_GAMMA,      /* cellAvconfExt.c: video-out gamma override         */
    PS3T_SHARPEN,            /* rsx_metal_backend.m: CAS sharpening               */
    PS3T_AA,                 /* rsx_metal_backend.m: FXAA                         */
    PS3T_ANISO,              /* rsx_metal_backend.m: anisotropic filtering        */
    PS3T_METAL_FPS,          /* rsx_metal_backend.m: window-title fps counter     */
    PS3T_VIBRANCE,           /* rsx_metal_backend.m: vibrance (-1..1)             */
    PS3T_CONTRAST,           /* rsx_metal_backend.m: contrast (0.5..1.5)          */
    PS3T_VIGNETTE,           /* rsx_metal_backend.m: vignette (0..1)              */
    PS3T_GRAIN,              /* rsx_metal_backend.m: film grain (0..1)            */
    PS3T_LUT_STRENGTH,       /* rsx_metal_backend.m: colour LUT mix (0..1)        */
    PS3T_BUTTON_ICONS,       /* rsx_button_icons.c: prompt glyph set (auto/...)   */
    PS3T_SPU_DIRECT,         /* spu_context.h: lifted direct branches tail-call   */
    PS3T_AUDIO_VOLUME,       /* cellAudio.c: host master volume (0..100)          */
    PS3T_SHADOWS,            /* rsx_metal_backend.m: curves, shadow lift (-1..1)  */
    PS3T_MIDTONES,           /* rsx_metal_backend.m: curves, midtone lift (-1..1) */
    PS3T_HIGHLIGHTS,         /* rsx_metal_backend.m: curves, highlight lift       */
    PS3T_CLARITY,            /* rsx_metal_backend.m: local contrast (-1..1)       */
    PS3T_LUT_PRESET,         /* rsx_metal_backend.m: built-in LUT (warm/cool/...) */
    PS3T_SPU_IBCACHE,        /* spu_channels.c: indirect-branch inline cache      */
    PS3T_SPU_DMA_LEAN,       /* spu_dma.h: no per-PUT poison scan, MFC slot hint  */
    PS3T_QUIT,               /* cellSysutil.c: 1 = quit the game (ps3_host_quit)  */
    PS3T_RES_SSAO_FULL,      /* rsx_metal_backend.m: SSAO upsample at RES_SCALE   */
    PS3T_ENG_FBFETCH,        /* rsx_draw_engine.c: own-target reads as fb fetch   */
    PS3T_ENG_DEPTH_BOUNDS,   /* rsx_draw_engine.c: the depth-bounds test          */
    PS3T_ENG_SHADOW_CMP,     /* rsx_draw_engine.c: RSX order of the depth compare */
    PS3T_ENG_ZTEX_CROP,      /* rsx_draw_engine.c: depth textures read their crop */
    PS3T_ENG_POLY_OFFSET,    /* rsx_draw_engine.c: polygon offset (depth bias)    */
    PS3T_ENG_DEPTH_CLAMP,    /* rsx_draw_engine.c: ZMIN_MAX_CONTROL depth clamp   */
    PS3T_ENG_CLAMP_CULL_FLIP,/* rsx_draw_engine.c: flip clamped draws (diagnostic)*/
    PS3T_ENG_SHADOW_D24,     /* rsx_draw_engine.c: shadow compare precision (diagnostic) */
    PS3T_ENG_CASTER_FAST,    /* rsx_draw_engine.c: shadow casters replayed from the previous one (eng caster fast) */
    PS3T_ENG_SHADOW_CULL_FAR, /* rsx_draw_engine.c: eng shadow cull far threshold, texels (A/B) */
    PS3T_ENG_TEXHASH_STABLE, /* rsx_draw_engine.c: slower full re-hash for settled textures */
    PS3T_GCM_LEGACY_LEAN,    /* cellGcmSys.c: only label methods into the unused legacy state machine */
    PS3T_ENG_MICRO,          /* rsx_draw_engine.c + rsx_vulkan_backend.c: small per-draw savings (A/B) */
    PS3T_ENG_CSNAP_REUSE,    /* rsx_draw_engine.c: one own-target copy per run of read-modify-write draws */
    PS3T_ENG_RMW_DIRECT,     /* engine + vk: read-modify-write draws sample their own target (1), in the open pass (2) */
    PS3T_GCM_FAST_WORDS,     /* cellGcmSys.c: plain NV4097 words straight to the draw engine */
    PS3T_ENG_DRAW_FAST,      /* rsx_draw_engine.c: any draw replayed from the previous one (eng draw fast) */
    PS3T_ENG_TEXHASH_ASYNC,  /* rsx_draw_engine.c: texture change hashes on a helper thread */
    PS3T_COUNT
};

/* How the environment variable was always read (the file always takes a
 * number, or the text for the string knobs). */
enum ps3_toggle_kind {
    PS3_TK_ATOI,   /* set ? atoi(value) : default          */
    PS3_TK_SET,    /* set (to anything) ? 1 : 0            */
    PS3_TK_NOT0,   /* starts with '0' ? 0 : 1              */
    PS3_TK_IS1,    /* exactly "1" ? 1 : 0                  */
    PS3_TK_STR     /* text, read by the site; value = atoi */
};

typedef struct { const char* name; int kind; int def; } ps3_toggle_def;

static inline const ps3_toggle_def* ps3_toggle_def_of(int id)
{
    static const ps3_toggle_def d[PS3T_COUNT] = {
        { "PS3RECOMP_ENG_VCACHE",       PS3_TK_ATOI, 1 },
        { "PS3RECOMP_ENG_TEXHASH_FULL", PS3_TK_SET,  0 },
        { "PS3RECOMP_ENG_SKIP_FP",      PS3_TK_STR,  0 },
        { "PS3_SPU_FASTJOB",            PS3_TK_NOT0, 1 },
        { "PS3_SPU_STUB_MICRO",         PS3_TK_NOT0, 1 },
        { "PS3_SPU_STACK_HINT",         PS3_TK_NOT0, 1 },
        { "PS3_SPU_DRAIN_INLINE",       PS3_TK_NOT0, 1 },
        { "PS3_DISPLAY_GAMMA",          PS3_TK_STR,  0 },
        { "PS3_SHARPEN",                PS3_TK_STR,  0 },
        { "PS3_AA",                     PS3_TK_STR,  0 },
        { "PS3_ANISO",                  PS3_TK_ATOI, 0 },
        { "PS3RECOMP_METAL_FPS",        PS3_TK_IS1,  0 },
        { "PS3_VIBRANCE",               PS3_TK_STR,  0 },
        { "PS3_CONTRAST",               PS3_TK_STR,  0 },
        { "PS3_VIGNETTE",               PS3_TK_STR,  0 },
        { "PS3_GRAIN",                  PS3_TK_STR,  0 },
        { "PS3_LUT_STRENGTH",           PS3_TK_STR,  0 },
        { "PS3_BUTTON_ICONS",           PS3_TK_STR,  0 },
        { "PS3_SPU_DIRECT",             PS3_TK_NOT0, 1 },
        { "PS3_AUDIO_VOLUME",           PS3_TK_STR,  0 },
        { "PS3_SHADOWS",                PS3_TK_STR,  0 },
        { "PS3_MIDTONES",               PS3_TK_STR,  0 },
        { "PS3_HIGHLIGHTS",             PS3_TK_STR,  0 },
        { "PS3_CLARITY",                PS3_TK_STR,  0 },
        { "PS3_LUT_PRESET",             PS3_TK_STR,  0 },
        { "PS3_SPU_IBCACHE",            PS3_TK_NOT0, 1 },
        { "PS3_SPU_DMA_LEAN",           PS3_TK_NOT0, 1 },
        { "PS3_QUIT",                   PS3_TK_ATOI, 0 },
        { "PS3_RES_SSAO_FULL",          PS3_TK_NOT0, 1 },
        { "PS3RECOMP_ENG_FBFETCH",      PS3_TK_ATOI, -1 },
        { "PS3RECOMP_ENG_DEPTH_BOUNDS", PS3_TK_NOT0, 1 },
        { "PS3RECOMP_ENG_SHADOW_CMP",   PS3_TK_NOT0, 1 },
        { "PS3RECOMP_ENG_ZTEX_CROP",    PS3_TK_NOT0, 1 },
        { "PS3RECOMP_ENG_POLY_OFFSET",  PS3_TK_ATOI, 1 },
        { "PS3RECOMP_ENG_DEPTH_CLAMP",  PS3_TK_NOT0, 1 },
        { "PS3RECOMP_ENG_CLAMP_CULL_FLIP", PS3_TK_ATOI, 0 },
        { "PS3RECOMP_ENG_SHADOW_D24",   PS3_TK_ATOI, 0 },
        { "PS3RECOMP_ENG_CASTER_FAST",  PS3_TK_ATOI, 0 },
        { "PS3RECOMP_ENG_SHADOW_CULL_FAR", PS3_TK_ATOI, -1 },
        { "PS3RECOMP_ENG_TEXHASH_STABLE", PS3_TK_IS1, 0 },
        { "PS3_GCM_LEGACY_LEAN",        PS3_TK_ATOI, 0 },
        { "PS3RECOMP_ENG_MICRO",        PS3_TK_IS1, 0 },
        { "PS3RECOMP_ENG_CSNAP_REUSE",  PS3_TK_ATOI, 0 },
        { "PS3RECOMP_ENG_RMW_DIRECT",   PS3_TK_ATOI, 0 },
        { "PS3_GCM_FAST_WORDS",         PS3_TK_ATOI, 0 },
        { "PS3RECOMP_ENG_DRAW_FAST",    PS3_TK_ATOI, 0 },
        { "PS3RECOMP_ENG_TEXHASH_ASYNC", PS3_TK_ATOI, 0 },
    };
    return &d[id];
}

#if defined(_MSC_VER)
#  define PS3_TOGGLE_SHARED __declspec(selectany)
#else
#  define PS3_TOGGLE_SHARED __attribute__((weak))
#endif

typedef void (*ps3_toggle_fn)(int id, int value);

enum { PS3_TOGGLE_STR = 160, PS3_TOGGLE_WATCHERS = 4, PS3_TOGGLE_EXTRA = 16 };

typedef struct {
    int seeded;                                   /* 0 no, 1 seeding, 2 done */
    char lock;                                    /* value/str/watchers/extra */
    int value[PS3T_COUNT];                        /* current */
    char str[PS3T_COUNT][PS3_TOGGLE_STR];
    int env_value[PS3T_COUNT];                    /* what the environment said */
    char env_str[PS3T_COUNT][PS3_TOGGLE_STR];
    ps3_toggle_fn watch[PS3T_COUNT][PS3_TOGGLE_WATCHERS];
    /* Names the file sets that are not built-in knobs: ps3_toggle_get() reads
     * them, for a quick experiment that has no knob of its own yet. */
    struct { char name[48]; int value, set; } extra[PS3_TOGGLE_EXTRA];
    int n_extra;
} ps3_toggle_state;

PS3_TOGGLE_SHARED ps3_toggle_state g_ps3_toggles = { 0 };

static inline void ps3_toggle_lock(void)
{
    while (__atomic_test_and_set(&g_ps3_toggles.lock, __ATOMIC_ACQUIRE)) { }
}
static inline void ps3_toggle_unlock(void)
{
    __atomic_clear(&g_ps3_toggles.lock, __ATOMIC_RELEASE);
}

static inline int ps3_toggle_env_parse(int id, const char* e)
{
    const ps3_toggle_def* d = ps3_toggle_def_of(id);
    switch (d->kind) {
    case PS3_TK_ATOI: return e ? atoi(e) : d->def;
    case PS3_TK_SET:  return e ? 1 : 0;
    case PS3_TK_NOT0: return (e && *e == '0') ? 0 : 1;
    case PS3_TK_IS1:  return (e && !strcmp(e, "1")) ? 1 : 0;
    default:          return e ? atoi(e) : d->def;
    }
}

/* Every knob from the environment, once. */
static inline void ps3_toggles_seed(void)
{
    ps3_toggle_state* s = &g_ps3_toggles;
    if (__builtin_expect(__atomic_load_n(&s->seeded, __ATOMIC_ACQUIRE) == 2, 1)) return;
    int expect = 0;
    if (!__atomic_compare_exchange_n(&s->seeded, &expect, 1, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        while (__atomic_load_n(&s->seeded, __ATOMIC_ACQUIRE) != 2) { }
        return;
    }
    int nondef = 0;
    for (int id = 0; id < PS3T_COUNT; id++) {
        const ps3_toggle_def* d = ps3_toggle_def_of(id);
        const char* e = getenv(d->name);
        s->env_value[id] = s->value[id] = ps3_toggle_env_parse(id, e);
        snprintf(s->env_str[id], PS3_TOGGLE_STR, "%s", e ? e : "");
        memcpy(s->str[id], s->env_str[id], PS3_TOGGLE_STR);
        nondef += d->kind == PS3_TK_STR ? (e && *e) : s->value[id] != ps3_toggle_env_parse(id, NULL);
    }
    __atomic_store_n(&s->seeded, 2, __ATOMIC_RELEASE);
    /* toggle reseed: when this ran shows in the log (on the PS5 a constructor -- libsre_spu_register_ctor ->
     * spu_register_stack_reset_entry -- seeds before ps5_app_setup has set the environment, and this line goes
     * to the stderr before the log's freopen; ps3_toggles_reseed_env() then logs its own summary). */
    fprintf(stderr, "[toggle] seeded: %d knobs from the environment (%d non-default)\n", (int)PS3T_COUNT, nondef);
}

/* Register fn for knob id and call it with the current value (under the lock,
 * so a change from the file cannot land between the two and be overwritten).
 * Returns that value. fn runs on the polling thread on every later change, so
 * it must be short: store an int, set a dirty flag. Registering the same fn
 * twice (two threads racing a site's first use) keeps one. */
static inline int ps3_toggle_watch(int id, ps3_toggle_fn fn)
{
    ps3_toggles_seed();
    ps3_toggle_lock();
    ps3_toggle_fn* w = g_ps3_toggles.watch[id];
    for (int i = 0; i < PS3_TOGGLE_WATCHERS; i++) {
        if (w[i] == fn) break;
        if (!w[i]) { w[i] = fn; break; }
    }
    const int v = g_ps3_toggles.value[id];
    fn(id, v);
    ps3_toggle_unlock();
    return v;
}

/* The current value (not for a hot path: use ps3_toggle_watch there). */
static inline int ps3_toggle_value(int id)
{
    ps3_toggles_seed();
    return __atomic_load_n(&g_ps3_toggles.value[id], __ATOMIC_RELAXED);
}

/* The current text of a knob ("" when neither the file nor the environment
 * sets it). */
static inline const char* ps3_toggle_str(int id, char* buf, size_t n)
{
    ps3_toggles_seed();
    ps3_toggle_lock();
    snprintf(buf, n, "%s", g_ps3_toggles.str[id]);
    ps3_toggle_unlock();
    return buf;
}

/* By name: a built-in knob's value, or a name the toggle file sets, else def.
 * A string compare per call: for an experiment's code path, not a hot one. */
static inline int ps3_toggle_get(const char* name, int def)
{
    ps3_toggles_seed();
    for (int id = 0; id < PS3T_COUNT; id++)
        if (!strcmp(ps3_toggle_def_of(id)->name, name)) return ps3_toggle_value(id);
    int v = def;
    ps3_toggle_lock();
    for (int i = 0; i < g_ps3_toggles.n_extra; i++)
        if (g_ps3_toggles.extra[i].set && !strcmp(g_ps3_toggles.extra[i].name, name)) {
            v = g_ps3_toggles.extra[i].value; break;
        }
    ps3_toggle_unlock();
    return v;
}

/* Re-read PS3_TOGGLE_FILE if it changed (at most every 250 ms) and apply it.
 * Call from ONE thread that runs every frame. Does nothing without the
 * variable. libs/misc/ps3_toggles.c. */
void ps3_toggles_poll(void);

/* toggle reseed: re-read every knob's environment variable; where it differs from what the first seed saw,
 * store it as the knob's environment value and (unless a toggle file already set the knob) as its current
 * value, calling the watchers as a toggle-file change does; one "[toggle]" line per changed knob plus a
 * summary line. For a host whose startup code sets the environment after the knobs were seeded (the PS5:
 * ps5_app_setup calls it after its last env_default). libs/misc/ps3_toggles.c. */
void ps3_toggles_reseed_env(void);

#ifdef __cplusplus
}
#endif

#endif
