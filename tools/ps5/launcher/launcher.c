/* inFamous: ReCharged (PS5) - the launcher: eboot.bin of the one app (PPSA95463) that holds all three
 * games, laid out as the other recomps' menus (Saints Row: ReInstated's). Shows the chosen game's art
 * and music; L1/R1 change the page (HOME, CONTENT, SETTINGS, CREDITS), Circle goes back to HOME; on
 * HOME up/down choose, Cross plays: the game's own program (/app0/if1.bin, if2.bin, fob.bin) is
 * started in this one's place (sceSystemServiceLoadExec), and it reads the settings this saves in
 * /app0/launcher.ini (ps5_app.c, apply_launcher_settings).
 *
 * Drawn on the CPU into a 1920x1080 picture, copied to a Vulkan image and scaled onto the TV through
 * RADV's PS5 display surface (the games' Vulkan backend's way of opening it). Art, music and fonts
 * are files in /app0/launcher/ (made by make_assets.py into Extras/app-assets/launcher). Log:
 * /app0/logs/launcher.log. */
#include <math.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>

#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_PNG
#define STBI_ONLY_JPEG
#define STBI_NO_STDIO_NOT_USED
#include "stb_image.h"
#define STB_TRUETYPE_IMPLEMENTATION
#include "stb_truetype.h"
#define DR_MP3_IMPLEMENTATION
#include "dr_mp3.h"

/* The INSTALL button: the player's ISO / PKG / folder dumps -> <app>/<game>/game (installer.c). */
#include "installer.c"

/* dr_mp3's wide-character file opening (unused here) calls wcsrtombs, which the games never import:
 * defined here, failing, so the launcher asks the console for nothing a game has not already used
 * (a missing import stops an app from starting at all). */
__attribute__((visibility("hidden")))
size_t wcsrtombs(char* restrict dst, const wchar_t** restrict src, size_t len, mbstate_t* restrict ps)
{
    (void)dst; (void)src; (void)len; (void)ps;
    return (size_t)-1;
}

#ifndef APP
#define APP "/app0"
#endif
#define W 1920
#define H 1080

/* ---- system ---- */
int sceUserServiceInitialize(void* params);
int sceUserServiceGetInitialUser(int32_t* user_id);
int scePadInit(void);
int scePadOpen(int32_t user_id, int32_t type, int32_t index, const void* param);
int scePadGetHandle(int32_t user_id, int32_t type, int32_t index);
int scePadReadState(int32_t handle, void* data);
int sceSystemServiceLoadExec(const char* path, char* const argv[]);
int sceSystemServiceHideSplashScreen(void);
int32_t sceAudioOutInit(void);
int32_t sceAudioOutOpen(int32_t user_id, int32_t type, int32_t index, uint32_t len, uint32_t freq, uint32_t param);
int32_t sceAudioOutOutput(int32_t handle, const void* ptr);
int32_t sceAudioOutClose(int32_t handle);
extern VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vk_icdGetInstanceProcAddr(VkInstance, const char*) __attribute__((weak));

static FILE* s_log;
static void logf_(const char* fmt, ...)
{
    if (!s_log) return;
    va_list ap; va_start(ap, fmt); vfprintf(s_log, fmt, ap); va_end(ap);
    fflush(s_log);
}

static double now_s(void)
{
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

/* ---- the games ---- */
enum { NGAMES = 3 };
static const char* const kName[NGAMES] = { "inFAMOUS", "inFAMOUS 2", "inFAMOUS: FESTIVAL OF BLOOD" };
static const char* const kDir[NGAMES] = { "if1", "if2", "fob" };
static const char* const kBlurbPt[NGAMES] = {
    "Empire City. Um entregador de bicicleta, um pacote e uma explosão que muda tudo.",
    "New Marais. Cole leva seus poderes para o sul para enfrentar a Besta.",
    "Noite da Fogueira em New Marais. Uma noite para desfazer a mordida de uma vampira.",
};
static const char* const kBlurb[NGAMES] = {
    "Empire City. A bike messenger, a package, and a blast that changes everything.",
    "New Marais. Cole takes his powers south to face the Beast.",
    "Pyre Night in New Marais. One night to undo a vampire's bite.",
};

/* ---- settings: each game's own (/app0/launcher_<g>.ini), and /app0/launcher.ini, the chosen game's,
 * which the games read when they start (ps5_app.c, apply_launcher_settings) ---- */
/* Every language an inFAMOUS game ships (inFAMOUS 2's text archives have the most); the runtime (ppu_fs_lang.h) maps the
 * code to the game's files, and a game without that language plays in English. Each name in its own language. */
static const char* const kLangCode[] = { "en", "fr", "es", "de", "it", "nl", "pt", "ru", "pl",
                                         "en-gb", "es-419", "pt-pt", "ja", "ko", "zh-t", "tr" };
static const char* const kLangName[] = { "ENGLISH", "FRANÇAIS", "ESPAÑOL", "DEUTSCH", "ITALIANO", "NEDERLANDS",
                                         "PORTUGUÊS (BRASIL)", "РУССКИЙ", "POLSKI", "ENGLISH (UK)", "ESPAÑOL (LATINOAMÉRICA)",
                                         "PORTUGUÊS (PORTUGAL)", "日本語", "한국어", "中文 (繁體)", "TÜRKÇE" };
static const char* const kLangNamePt[] = { "ENGLISH", "FRANÇAIS", "ESPAÑOL", "DEUTSCH", "ITALIANO", "NEDERLANDS",
                                           "PORTUGUÊS (BRASIL)", "РУССКИЙ", "POLSKI", "ENGLISH (UK)", "ESPAÑOL (LATINOAMÉRICA)",
                                           "PORTUGUÊS (PORTUGAL)", "日本語", "한국어", "中文 (繁體)", "TÜRKÇE" };
enum { NLANG = 16, LANG_AUTO = -1, LANG_PT = 6 };
typedef struct { int skip_intro, skip_movies, lang, gpu_effects, diagnostics, fps_counter, framegen, no_fsr, look, no_aa, no_aniso, no_ds, no_dlc, sharp, aniso_dn, smaa, ver; } gset_t;   /* ver: the file's settings_version (SETTINGS_VERSION since the release defaults; 0 = an older launcher's) */   /* smaa: with no_aa 0, SMAA instead of FXAA (ini anti_aliasing = 0 off / 1 FXAA / 2 SMAA) */   /* sharp: 0 high / 1 medium / 2 low (FSR RCAS 0 / 0.5 / 1.0 stops); aniso_dn: steps below 16x (0 16x, 1 8x, 2 4x, 3 2x) */   /* no_dlc: DLC costumes off (if2/fob) */   /* no_ds: DualSense extras off (set by the in-game quick menu) */   /* look: 0 original, 1 remaster, 2 comic (ini look) */   /* no_fsr: 1 = bilinear (ini upscaler = 0) */   /* fps_counter: 0 off, 1 simple, 2 detailed */   /* lang: LANG_AUTO or kLangCode's */
/* The recommended settings (SQUARE on SETTINGS) and a fresh install's, for all three; the language AUTO,
 * the PS5's own. Release defaults (2026-11-11): skip_intro 0, skip_movies 0 (every movie plays),
 * diagnostics 0, fps_counter 0 (were 1, 1, 1, 1 while testing). A saved launcher_<game>.ini / launcher.ini
 * still wins (settings_load). ps5_app.c apply_launcher_settings has the same defaults: keep them in step. */
#define RELEASE_DEFAULTS { 0, 0, LANG_AUTO, 1, 0, 0, 1, .smaa = 1 }   /* skip_intro, skip_movies, lang, gpu_effects, diagnostics, fps_counter, framegen; smaa; the rest 0. 2026-11-12: FRAME GENERATION on + ANTI-ALIASING SMAA = the owner's console settings, declared the release defaults (the launcher writes launcher.ini at every game start, so the games' own no-file defaults in ps5_app.c, fg 0 / aa 1, are not reached from the launcher) */
static const gset_t kRecommended[NGAMES] = { RELEASE_DEFAULTS, RELEASE_DEFAULTS, RELEASE_DEFAULTS };
/* A file an older launcher wrote (no settings_version line) has its test-time DIAGNOSTICS = 1 by default: put to 0 once
 * (logged), as the release defaults; every other choice in it is kept. */
enum { SETTINGS_VERSION = 2 };
static gset_t G[NGAMES] = { RELEASE_DEFAULTS, RELEASE_DEFAULTS, RELEASE_DEFAULTS };
static struct { int game, music, fx; } S = { 1, 70, 1 };   /* fx: MENU EFFECTS (launcher.ini menu_effects, 1 on by default) */

/* LANGUAGE > AUTO: the PS5's own language (kLangCode's), English for one the list hasn't. Asked once. */
int sceSystemServiceParamGetInt(int param_id, int* value);
static int system_lang(void)
{
    static int lang = -2;
    if (lang == -2) {
        int v = 1;
        if (sceSystemServiceParamGetInt(1 /* SCE_SYSTEM_SERVICE_PARAM_ID_LANG */, &v) != 0) v = 1;
        /* SCE_SYSTEM_LANG: 0 ja 1 en-US 2 fr 3 es 4 de 5 it 6 nl 7 pt-PT 8 ru 9 ko 10 zh-T 11 zh-S 16 pl 17 pt-BR 18 en-GB 19 tr
         * 20 es-419 22 fr-CA */
        lang = v == 0 ? 12 : v == 2 || v == 22 ? 1 : v == 3 ? 2 : v == 4 ? 3 : v == 5 ? 4 : v == 6 ? 5 : v == 7 ? 11
             : v == 8 ? 7 : v == 9 ? 13 : v == 10 || v == 11 ? 14 : v == 16 ? 8 : v == 17 ? LANG_PT : v == 18 ? 9 : v == 19 ? 15
             : v == 20 ? 10 : 0;
        logf_("the PS5's language: %d (%s)\n", v, kLangCode[lang]);
    }
    return lang;
}
static int lang_of(const gset_t* g) { return g->lang == LANG_AUTO ? system_lang() : g->lang; }

/* The launcher's own text in English or Brazilian Portuguese (the shown game's LANGUAGE, PORTUGUESE),
 * T("English", "Português") side by side, as the other recomps' menus. */
static int s_pt;
static int s_ml;   /* the menu's language: kLangCode index (the chosen game's LANGUAGE, AUTO = the PS5's) */
#include "launcher_text.inc"
/* The menu text in s_ml: en / en-gb the English, pt the call's Portuguese, the rest from kMenuTr (English if missing).
 * A small cache by the English literal's address keeps the lookups out of the frame. */
static const char* T(const char* en, const char* pt)
{
    if (s_ml == 0 || s_ml == 9) return en;
    if (s_ml == 6) return pt;
    enum { TRC = 512 };
    static struct { const char* en; int ml; const char* out; } c[TRC];
    unsigned k = (unsigned)((uintptr_t)en >> 3) * 2654435761u;
    for (int i = 0; i < 8; i++) {
        unsigned j = (k + (unsigned)i) % TRC;
        if (c[j].en == en && c[j].ml == s_ml) return c[j].out;
        if (!c[j].en) {
            const char* out = en;
            for (unsigned n = 0; n < sizeof kMenuTr / sizeof kMenuTr[0]; n++)
                if (!strcmp(kMenuTr[n].en, en)) { if (kMenuTr[n].t[s_ml]) out = kMenuTr[n].t[s_ml]; break; }
            c[j].en = en; c[j].ml = s_ml; c[j].out = out;
            return out;
        }
    }
    for (unsigned n = 0; n < sizeof kMenuTr / sizeof kMenuTr[0]; n++)
        if (!strcmp(kMenuTr[n].en, en)) return kMenuTr[n].t[s_ml] ? kMenuTr[n].t[s_ml] : en;
    return en;
}

/* The installer's own text (installer.c, here or in the payload's status.txt: always English, built at run time) in s_ml:
 * the whole text from kMenuTr, or else the kMenuTr entry whose only conversions are %s that matches it, each %s part
 * translated the same way (a file name stays as it is) and put into that entry's translation in order. pt has its own
 * column in these entries (T() has the call's). A few recent results cached by their text (not T()'s by address: these
 * are buffers whose text changes). */
static int ti_match(const char* t, const char* s, const char** a, int* al, int k)
{
    for (; *t; t++, s++) {
        if (t[0] == '%' && t[1] == 's') {
            if (k >= 4) return -1;
            for (const char* e = s;; e++) {   /* (shortest first: the names come before ": ") */
                a[k] = s; al[k] = (int)(e - s);
                const int r = ti_match(t + 2, e, a, al, k + 1);
                if (r >= 0) return r;
                if (!*e) return -1;
            }
        }
        if (*t != *s) return -1;
    }
    return *s ? -1 : k;
}
static void ti_tr(const char* s, char* out, size_t n, int depth)
{
    snprintf(out, n, "%s", s);
    if (s_ml == 0 || s_ml == 9 || !*s) return;
    const unsigned N = sizeof kMenuTr / sizeof kMenuTr[0];
    for (unsigned i = 0; i < N; i++)
        if (kMenuTr[i].t[s_ml] && !strcmp(kMenuTr[i].en, s)) { snprintf(out, n, "%s", kMenuTr[i].t[s_ml]); return; }
    if (depth > 3) return;
    for (unsigned i = 0; i < N; i++) {
        const char* en = kMenuTr[i].en; const char* tr = kMenuTr[i].t[s_ml];
        if (!tr || !strstr(en, "%s")) continue;
        int only_s = 1;
        for (const char* p = strchr(en, '%'); p; p = strchr(p + 2, '%')) if (p[1] != 's') { only_s = 0; break; }
        const char* a[4]; int al[4];
        const int na = only_s ? ti_match(en, s, a, al, 0) : -1;
        if (na < 0) continue;
        size_t k = 0; int j = 0;
        for (const char* p = tr; *p && k + 1 < n; p++) {
            if (p[0] == '%' && p[1] == 's' && j < na) {
                char arg[256], sub[384];
                snprintf(arg, sizeof arg, "%.*s", al[j], a[j]); j++;
                ti_tr(arg, sub, sizeof sub, depth + 1);
                const int w = snprintf(out + k, n - k, "%s", sub);
                k = w < 0 ? k : k + (size_t)w < n ? k + (size_t)w : n - 1;
                p++; continue;
            }
            out[k++] = *p;
        }
        out[k] = 0;
        return;
    }
}
static const char* TI(const char* s)
{
    static struct { int ml; char in[320]; char out[640]; } c[16];
    static int next;
    for (int i = 0; i < 16; i++) if (c[i].ml == s_ml + 1 && !strcmp(c[i].in, s)) return c[i].out;
    const int i = next; next = (next + 1) % 16;
    c[i].ml = s_ml + 1; snprintf(c[i].in, sizeof c[i].in, "%s", s);
    ti_tr(c[i].in, c[i].out, sizeof c[i].out, 0);
    return c[i].out;
}

/* One file's lines into a game's settings (and the menu's, from launcher.ini); 0: no file. */
static int settings_read(const char* path, gset_t* g, int menu)
{
    FILE* f = fopen(path, "r");
    if (!f) return 0;
    char line[256];
    while (fgets(line, sizeof line, f)) {
        char key[64], sv[32]; int v;
        if (sscanf(line, " language = %31s", sv) == 1) {
            if (!strcmp(sv, "auto")) g->lang = LANG_AUTO;
            for (int i = 0; i < NLANG; i++) if (!strcmp(sv, kLangCode[i])) g->lang = i;
            continue;
        }
        if (sscanf(line, " %63[a-z_] = %d", key, &v) != 2) continue;
        if (!strcmp(key, "skip_intro")) g->skip_intro = !!v;
        else if (!strcmp(key, "skip_movies")) g->skip_movies = !!v;
        else if (!strcmp(key, "gpu_effects")) g->gpu_effects = !!v;
        else if (!strcmp(key, "diagnostics")) g->diagnostics = !!v;
        else if (!strcmp(key, "fps_counter")) g->fps_counter = v < 0 ? 0 : v > 2 ? 2 : v;
        else if (!strcmp(key, "frame_generation")) g->framegen = !!v;
        else if (!strcmp(key, "upscaler")) g->no_fsr = !v;
        else if (!strcmp(key, "look")) g->look = v < 0 ? 0 : v > 11 ? 11 : v;
        else if (!strcmp(key, "anti_aliasing")) { g->no_aa = !v; g->smaa = v == 2; }
        else if (!strcmp(key, "aniso")) { g->no_aniso = !v; g->aniso_dn = v >= 16 || v == 1 ? 0 : v >= 8 ? 1 : v >= 4 ? 2 : v >= 2 ? 3 : 0; }
        else if (!strcmp(key, "sharpness")) g->sharp = v < 0 ? 0 : v > 2 ? 2 : v;
        else if (!strcmp(key, "dualsense")) g->no_ds = !v;
        else if (!strcmp(key, "dlc")) g->no_dlc = !v;
        else if (!strcmp(key, "settings_version")) g->ver = v;
        else if (menu && !strcmp(key, "game") && v >= 0 && v < NGAMES) S.game = v;
        else if (menu && !strcmp(key, "menu_music")) S.music = v < 0 ? 0 : v > 100 ? 100 : v;
        else if (menu && !strcmp(key, "menu_effects")) S.fx = !!v;
    }
    fclose(f);
    return 1;
}

static void settings_load(void)
{
    gset_t last = G[0];
    const int have = settings_read(APP "/launcher.ini", &last, 1);
    for (int i = 0; i < NGAMES; i++) {
        char p[96];
        snprintf(p, sizeof p, APP "/launcher_%s.ini", kDir[i]);
        G[i] = kRecommended[i];
        /* (none yet: the shared launcher.ini of before, for every game) */
        if (!settings_read(p, &G[i], 0) && have) G[i] = last;
        if (G[i].ver < SETTINGS_VERSION && G[i].diagnostics) { G[i].diagnostics = 0; logf_("%s: diagnostics off (settings of an older launcher)\n", kDir[i]); }
    }
}

static void settings_write(const char* path, const gset_t* g, int menu)
{
    FILE* f = fopen(path, "w");
    if (!f) { logf_("cannot write %s\n", path); return; }
    if (menu) fprintf(f, "game = %d\n", S.game);
    /* (a game's own file keeps AUTO; launcher.ini, which the game reads, the language it is) */
    fprintf(f, "skip_intro = %d\nskip_movies = %d\nlanguage = %s\ngpu_effects = %d\ndiagnostics = %d\nfps_counter = %d\nframe_generation = %d\nupscaler = %d\nlook = %d\nanti_aliasing = %d\naniso = %d\nsharpness = %d\ndualsense = %d\ndlc = %d\n",
            g->skip_intro, g->skip_movies, !menu && g->lang == LANG_AUTO ? "auto" : kLangCode[lang_of(g)],
            g->gpu_effects, g->diagnostics, g->fps_counter, g->framegen, !g->no_fsr, g->look, g->no_aa ? 0 : g->smaa ? 2 : 1, g->no_aniso ? 0 : 16 >> g->aniso_dn, g->sharp, !g->no_ds, !g->no_dlc);
    if (menu) fprintf(f, "menu_music = %d\nmenu_effects = %d\n", S.music, S.fx);
    fprintf(f, "settings_version = %d\n", SETTINGS_VERSION);
    fclose(f);
}

static void settings_save(void)
{
    for (int i = 0; i < NGAMES; i++) {
        char p[96];
        snprintf(p, sizeof p, APP "/launcher_%s.ini", kDir[i]);
        settings_write(p, &G[i], 0);
    }
    settings_write(APP "/launcher.ini", &G[S.game], 1);
}

/* ---- pictures ---- */
typedef struct { int w, h; uint32_t* px; } img_t;   /* B8G8R8A8 (0xAARRGGBB as a uint32) */
static uint32_t* s_fb;                               /* the 1920x1080 frame */
static int s_cx0, s_cy0, s_cx1 = W, s_cy1 = H;       /* the clip rectangle (credits, settings' list) */
static void clip(int x0, int y0, int x1, int y1)
{
    s_cx0 = x0 < 0 ? 0 : x0; s_cy0 = y0 < 0 ? 0 : y0; s_cx1 = x1 > W ? W : x1; s_cy1 = y1 > H ? H : y1;
}
static void unclip(void) { s_cx0 = 0; s_cy0 = 0; s_cx1 = W; s_cy1 = H; }

static int file_exists(const char* p) { struct stat st; return stat(p, &st) == 0; }

/* Load, then scale to w x h: cover (fill, crop the rest) or contain (fit, transparent around). */
static img_t img_load(const char* path, int w, int h, int cover)
{
    img_t out = { w, h, calloc((size_t)w * h, 4) };
    int sw, sh, n;
    uint8_t* src = stbi_load(path, &sw, &sh, &n, 4);
    if (!src) { logf_("image %s: %s\n", path, stbi_failure_reason()); return out; }
    const float sx = (float)w / sw, sy = (float)h / sh;
    const float s = cover ? (sx > sy ? sx : sy) : (sx < sy ? sx : sy);
    const float ox = (w - sw * s) * 0.5f, oy = (h - sh * s) * 0.5f;
    /* (shrinking: each output pixel averages the source pixels under it, not just the nearest 4) */
    const int taps = s < 1.0f ? (int)ceilf(1.0f / s) : 1;
    for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++) {
            float c[4] = { 0, 0, 0, 0 }, wsum = 0;
            for (int ty = 0; ty < taps; ty++)
                for (int tx = 0; tx < taps; tx++) {
                    const float fx = (x + (tx + 0.5f) / taps - ox) / s - 0.5f, fy = (y + (ty + 0.5f) / taps - oy) / s - 0.5f;
                    if (fx < -0.5f || fy < -0.5f || fx > sw - 0.5f || fy > sh - 0.5f) continue;
                    int x0 = (int)floorf(fx), y0 = (int)floorf(fy);
                    const float ax = fx - x0, ay = fy - y0;
                    for (int k = 0; k < 4; k++) {
                        const int xx = x0 + (k & 1), yy = y0 + (k >> 1);
                        const int cx = xx < 0 ? 0 : xx >= sw ? sw - 1 : xx, cy = yy < 0 ? 0 : yy >= sh ? sh - 1 : yy;
                        const float wgt = ((k & 1) ? ax : 1 - ax) * ((k >> 1) ? ay : 1 - ay);
                        const uint8_t* p = src + ((size_t)cy * sw + cx) * 4;
                        /* (premultiplied: no dark fringe where a cut-out's edge meets transparent pixels) */
                        const float pa = p[3] / 255.0f;
                        c[0] += p[0] * pa * wgt; c[1] += p[1] * pa * wgt; c[2] += p[2] * pa * wgt; c[3] += p[3] * wgt;
                    }
                    wsum += 1.0f;
                }
            if (wsum == 0) continue;
            const float a = c[3] / wsum, un = a > 0.5f ? 255.0f / a : 0.0f;
            const uint32_t r = (uint32_t)fminf(255, c[0] / wsum * un), g = (uint32_t)fminf(255, c[1] / wsum * un),
                           b = (uint32_t)fminf(255, c[2] / wsum * un);
            out.px[(size_t)y * w + x] = ((uint32_t)(a + 0.5f) << 24) | (r << 16) | (g << 8) | b;
        }
    stbi_image_free(src);
    return out;
}

/* An image h pixels tall, as wide as its shape makes it. */
static img_t img_load_h(const char* path, int h)
{
    int sw = 1, sh = 1, n;
    if (!stbi_info(path, &sw, &sh, &n)) { logf_("image %s: %s\n", path, stbi_failure_reason()); sw = sh = 1; }
    return img_load(path, (int)lroundf((float)sw * h / sh), h, 0);
}

static inline void blend_px(uint32_t* d, uint32_t s, int a /* 0..255 */)
{
    if (a <= 0) return;
    if (a >= 255) { *d = s | 0xFF000000u; return; }
    const uint32_t D = *d;
    uint32_t r = (((s >> 16) & 255) * a + ((D >> 16) & 255) * (255 - a)) / 255;
    uint32_t g = (((s >> 8) & 255) * a + ((D >> 8) & 255) * (255 - a)) / 255;
    uint32_t b = ((s & 255) * a + (D & 255) * (255 - a)) / 255;
    *d = 0xFF000000u | (r << 16) | (g << 8) | b;
}

/* Draw an image at x,y with opacity 0..255 (its own alpha too). */
static void img_draw(const img_t* im, int x, int y, int opacity)
{
    for (int j = 0; j < im->h; j++) {
        const int yy = y + j;
        if (yy < s_cy0 || yy >= s_cy1) continue;
        for (int i = 0; i < im->w; i++) {
            const int xx = x + i;
            if (xx < s_cx0 || xx >= s_cx1) continue;
            const uint32_t s = im->px[(size_t)j * im->w + i];
            blend_px(&s_fb[(size_t)yy * W + xx], s, (int)((s >> 24) * opacity / 255));
        }
    }
}

static void rect(int x, int y, int w, int h, uint32_t rgb, int a)
{
    const int x0 = x < s_cx0 ? s_cx0 : x, x1 = x + w > s_cx1 ? s_cx1 : x + w;
    for (int j = y < s_cy0 ? s_cy0 : y; j < y + h && j < s_cy1; j++)
        for (int i = x0; i < x1; i++) blend_px(&s_fb[(size_t)j * W + i], rgb, a);
}

/* A black rectangle whose opacity runs between its corners (top-left, top-right, bottom-right,
 * bottom-left), as ImGui's AddRectFilledMultiColor: the shades. */
static void shade(int x0, int y0, int x1, int y1, int a_tl, int a_tr, int a_br, int a_bl)
{
    if (x1 <= x0 || y1 <= y0) return;
    for (int j = y0 < s_cy0 ? s_cy0 : y0; j < y1 && j < s_cy1; j++) {
        const float v = (j - y0 + 0.5f) / (y1 - y0);
        const float l = a_tl + (a_bl - a_tl) * v, r = a_tr + (a_br - a_tr) * v;
        for (int i = x0 < s_cx0 ? s_cx0 : x0; i < x1 && i < s_cx1; i++) {
            const float h = (i - x0 + 0.5f) / (x1 - x0);
            blend_px(&s_fb[(size_t)j * W + i], 0x000000, (int)(l + (r - l) * h));
        }
    }
}

/* A rounded rectangle, filled (thick 0) or its outline thick pixels wide, edges smoothed. */
static void rrect(float x0, float y0, float x1, float y1, float r, float thick, uint32_t rgb, int a)
{
    const float cx = (x0 + x1) * 0.5f, cy = (y0 + y1) * 0.5f, hx = (x1 - x0) * 0.5f - r, hy = (y1 - y0) * 0.5f - r;
    for (int j = (int)floorf(y0) - 1; j <= (int)ceilf(y1); j++) {
        if (j < s_cy0 || j >= s_cy1) continue;
        for (int i = (int)floorf(x0) - 1; i <= (int)ceilf(x1); i++) {
            if (i < s_cx0 || i >= s_cx1) continue;
            const float qx = fabsf(i + 0.5f - cx) - hx, qy = fabsf(j + 0.5f - cy) - hy;
            const float ox = qx > 0 ? qx : 0, oy = qy > 0 ? qy : 0;
            float d = sqrtf(ox * ox + oy * oy) + (qx > qy ? (qx < 0 ? qx : 0) : (qy < 0 ? qy : 0)) - r;
            if (thick > 0) d = fabsf(d + thick * 0.5f) - thick * 0.5f;
            const float cov = 0.5f - d;
            if (cov <= 0) continue;
            blend_px(&s_fb[(size_t)j * W + i], rgb, (int)(a * (cov > 1 ? 1 : cov)));
        }
    }
}

/* ---- text ---- */
typedef struct { stbtt_fontinfo info; uint8_t* data; int ok; float ascent; } font_t;
static font_t F_title, F_item, F_body;
static font_t F_fb, F_cjk;   /* glyph fallbacks: DejaVu Sans (Latin Extended, Cyrillic, Greek), Noto Sans CJK (ja/ko/zh) */

static void font_load(font_t* f, const char* path)
{
    FILE* fp = fopen(path, "rb");
    if (!fp) { logf_("font %s missing\n", path); return; }
    fseek(fp, 0, SEEK_END); long n = ftell(fp); fseek(fp, 0, SEEK_SET);
    f->data = malloc((size_t)n);
    if (fread(f->data, 1, (size_t)n, fp) != (size_t)n) { fclose(fp); return; }
    fclose(fp);
    f->ok = stbtt_InitFont(&f->info, f->data, stbtt_GetFontOffsetForIndex(f->data, 0));
    if (f->ok) {
        int asc, desc, gap;
        stbtt_GetFontVMetrics(&f->info, &asc, &desc, &gap);
        f->ascent = (float)asc / (asc - desc);   /* (of the pixel height: where the baseline sits) */
    }
}

/* The glyph cache: (font, pixel height, codepoint) -> bitmap, an open-addressed table. */
typedef struct { const font_t* f; int px, cp, w, h, xo, yo, adv; uint8_t* bm; } glyph_t;
enum { GCN = 4096 };
static glyph_t s_gc[GCN];
static int s_gn;
static const glyph_t* glyph(const font_t* f, int px, int cp)
{
    unsigned k = ((unsigned)(uintptr_t)f >> 4) * 2654435761u ^ (unsigned)px * 40503u ^ (unsigned)cp * 9973u;
    for (;;) {
        glyph_t* g = &s_gc[k % GCN];
        if (g->f == f && g->px == px && g->cp == cp) return g;
        if (!g->f) break;
        k++;
    }
    if (s_gn > GCN * 3 / 4) {   /* full: start again */
        for (int i = 0; i < GCN; i++) { if (s_gc[i].bm) stbtt_FreeBitmap(s_gc[i].bm, NULL); }
        memset(s_gc, 0, sizeof s_gc);
        s_gn = 0;
        return glyph(f, px, cp);
    }
    glyph_t* g = &s_gc[k % GCN];
    s_gn++;
    const font_t* u = f;   /* a letter the menu's font lacks: from a fallback font */
    if (cp > 0x7F && !stbtt_FindGlyphIndex(&f->info, cp)) {
        if (F_fb.ok && stbtt_FindGlyphIndex(&F_fb.info, cp)) u = &F_fb;
        else if (F_cjk.ok && stbtt_FindGlyphIndex(&F_cjk.info, cp)) u = &F_cjk;
    }
    float sc = stbtt_ScaleForPixelHeight(&u->info, (float)px);
    if (u == &F_fb) {   /* (DejaVu's letters at the menu font's capital height, H to H; the CJK font keeps its size) */
        int a0, b0, a1, b1, c0, d0, c1, d1;
        if (stbtt_GetCodepointBox(&f->info, 'H', &a0, &b0, &a1, &b1) && stbtt_GetCodepointBox(&u->info, 'H', &c0, &d0, &c1, &d1) && d1 > d0)
            sc = stbtt_ScaleForPixelHeight(&f->info, (float)px) * (float)(b1 - b0) / (float)(d1 - d0);
    }
    int adv, lsb;
    stbtt_GetCodepointHMetrics(&u->info, cp, &adv, &lsb);
    g->f = f; g->px = px; g->cp = cp; g->adv = (int)lroundf(adv * sc);
    g->bm = stbtt_GetCodepointBitmap(&u->info, sc, sc, cp, &g->w, &g->h, &g->xo, &g->yo);
    return g;
}

/* The next letter of UTF-8 text (Portuguese's accents: two bytes), s moved past it. */
static int utf8(const char** s)
{
    const unsigned char* p = (const unsigned char*)*s;
    int c = *p++, n = c >= 0xF0 ? 3 : c >= 0xE0 ? 2 : c >= 0xC0 ? 1 : 0;
    if (n) c &= 0x3F >> n;
    for (; n && (*p & 0xC0) == 0x80; n--) c = (c << 6) | (*p++ & 0x3F);
    *s = (const char*)p;
    return c;
}

static int text_w(const font_t* f, int px, const char* s)
{
    if (!f->ok) return 0;
    int w = 0;
    while (*s) w += glyph(f, px, utf8(&s))->adv;
    return w;
}

/* x, y = left, baseline. */
static void text(const font_t* f, int px, int x, int y, uint32_t rgb, int a, const char* s)
{
    if (!f->ok || a <= 0) return;
    while (*s) {
        const glyph_t* g = glyph(f, px, utf8(&s));
        for (int j = 0; j < g->h; j++) {
            const int yy = y + g->yo + j;
            if (yy < s_cy0 || yy >= s_cy1) continue;
            for (int i = 0; i < g->w; i++) {
                const int xx = x + g->xo + i;
                if (xx < s_cx0 || xx >= s_cx1) continue;
                const int cov = g->bm[j * g->w + i];
                if (cov) blend_px(&s_fb[(size_t)yy * W + xx], rgb, cov * a / 255);
            }
        }
        x += g->adv;
    }
}

/* Text placed as ImGui places it (x, y = left, top of the line; px = the line's height): the menus
 * of the other recomps are laid out this way. */
static void textt(const font_t* f, int px, float x, float y, uint32_t rgb, int a, const char* s)
{
    text(f, px, (int)lroundf(x), (int)lroundf(y + f->ascent * px), rgb, a, s);
}

/* Letter-spaced; returns its width. */
static int spaced(const font_t* f, int px, float x, float y, uint32_t rgb, int a, const char* s, int sp)
{
    const float x0 = x;
    char c[8];
    while (*s) {
        const char* next = s;
        utf8(&next);
        memcpy(c, s, (size_t)(next - s)); c[next - s] = 0;
        textt(f, px, x, y, rgb, a, c); x += text_w(f, px, c) + sp;
        s = next;
    }
    return (int)(x - x0) - sp;
}

/* Wrapped at spaces to width (and at \n); returns the height (lines x px). draw 0: measure only. */
static int text_wrap(const font_t* f, int px, float x, float y, int width, uint32_t rgb, int a, const char* s, int draw)
{
    char line[512];
    int lines = 0;
    while (*s) {
        int n = 0, last_space = -1, w = 0;
        while (s[n] && s[n] != '\n') {
            const char* next = s + n;
            const int cw = glyph(f, px, utf8(&next))->adv;
            if (w + cw > width && n > 0) break;
            if (s[n] == ' ') last_space = n;
            w += cw; n = (int)(next - s);
        }
        int take = n, skip = n;
        if (s[n] && s[n] != '\n' && last_space > 0) { take = last_space; skip = last_space + 1; }
        else if (s[n] == '\n') skip = n + 1;
        if (take > (int)sizeof line - 1) take = (int)sizeof line - 1;
        memcpy(line, s, (size_t)take); line[take] = 0;
        if (draw) textt(f, px, x, y + lines * px, rgb, a, line);
        lines++;
        s += skip;
    }
    return lines * px;
}

/* Upper case, in place. */
/* Upper case, in place: UTF-8's accented Latin-1 letters too (á -> Á). */
static char* upper(char* s)
{
    for (unsigned char* p = (unsigned char*)s; *p; p++) {
        if (*p >= 'a' && *p <= 'z') *p = (unsigned char)(*p - 32);
        else if (*p == 0xC3 && p[1] >= 0xA0 && p[1] <= 0xBE && p[1] != 0xB7) { p[1] = (unsigned char)(p[1] - 0x20); p++; }
    }
    return s;
}

/* ---- music: the chosen game's song, looped, through one sceAudioOut port ---- */
static volatile int s_want_track = -1, s_audio_run = 1;
static volatile float s_volume = 0.7f;
static pthread_t s_audio_th;

static void* audio_main(void* arg)
{
    (void)arg;
    sceAudioOutInit();
    const int port = sceAudioOutOpen(0xFF, 0, 0, 256, 48000, 1);
    if (port < 0) { logf_("sceAudioOutOpen failed 0x%08X\n", (unsigned)port); return NULL; }
    drmp3 mp3; int open = -1;
    float gain = 0.0f;                      /* fades in on a new song, out before a change */
    double pos = 0.0;                       /* resampling position in source frames */
    int16_t src[2 * 4096]; int src_n = 0, src_base = 0;
    int16_t out[2 * 256];
    while (s_audio_run) {
        const int want = s_want_track;
        if (want != open && gain <= 0.001f) {
            if (open >= 0) drmp3_uninit(&mp3);
            open = -1;
            char path[128];
            snprintf(path, sizeof path, APP "/launcher/music_%s.mp3", want >= 0 ? kDir[want] : "");
            if (want >= 0 && drmp3_init_file(&mp3, path, NULL)) { open = want; pos = 0; src_n = 0; src_base = 0; }
            else if (want >= 0) { logf_("music %s missing\n", path); open = want; }
        }
        const float target = (want == open && open >= 0) ? s_volume : 0.0f;
        for (int i = 0; i < 256; i++) {
            gain += (target - gain) * 0.0005f;
            if (target == 0.0f && gain < 0.001f) gain = 0.0f;
            float l = 0, r = 0;
            if (open >= 0 && mp3.sampleRate) {
                const double step = (double)mp3.sampleRate / 48000.0;
                int need = (int)pos - src_base + 2;
                while (need > src_n) {   /* refill (keep the last frame for interpolation) */
                    if (src_n > 0) { src[0] = src[2 * (src_n - 1)]; src[1] = src[2 * (src_n - 1) + 1]; src_base += src_n - 1; src_n = 1; }
                    drmp3_uint64 got = drmp3_read_pcm_frames_s16(&mp3, 4095, src + 2 * src_n);
                    if (got == 0) { drmp3_seek_to_pcm_frame(&mp3, 0); pos = 0; src_base = 0; src_n = 0; continue; }
                    if (mp3.channels == 1) for (int k = (int)got - 1; k >= 0; k--) { src[2 * (src_n + k)] = src[src_n + k]; src[2 * (src_n + k) + 1] = src[src_n + k]; }
                    src_n += (int)got;
                    need = (int)pos - src_base + 2;
                }
                const int k = (int)pos - src_base;
                const float t = (float)(pos - floor(pos));
                l = (src[2 * k] * (1 - t) + src[2 * (k + 1)] * t) / 32768.0f;
                r = (src[2 * k + 1] * (1 - t) + src[2 * (k + 1) + 1] * t) / 32768.0f;
                pos += step;
            }
            l *= gain; r *= gain;
            out[2 * i] = (int16_t)(l > 1 ? 32767 : l < -1 ? -32767 : l * 32767);
            out[2 * i + 1] = (int16_t)(r > 1 ? 32767 : r < -1 ? -32767 : r * 32767);
        }
        sceAudioOutOutput(port, out);
    }
    if (open >= 0 && mp3.sampleRate) drmp3_uninit(&mp3);
    sceAudioOutClose(port);
    return NULL;
}

/* ---- the controller ---- */
enum { B_UP = 1, B_DOWN = 2, B_LEFT = 4, B_RIGHT = 8, B_CROSS = 16, B_CIRCLE = 32, B_L1 = 64, B_R1 = 128, B_SQUARE = 256, B_TRIANGLE = 512 };
typedef struct { uint32_t buttons; uint8_t lx, ly, rx, ry, l2, r2; uint16_t pad; uint8_t rest[240]; } pad_data_t;
static int s_pad = -1;
static uint32_t s_last;
static double s_repeat_at;
static int s_first = 1;
static uint32_t pad_pressed(void)
{
    if (s_pad < 0) {
        sceUserServiceInitialize(NULL);
        scePadInit();
        int32_t user = -1;
        if (sceUserServiceGetInitialUser(&user) == 0 && user >= 0) {
            s_pad = scePadOpen(user, 0, 0, NULL);
            if (s_pad < 0) s_pad = scePadGetHandle(user, 0, 0);
        }
        if (s_pad < 0) return 0;
    }
    pad_data_t d; memset(&d, 0, sizeof d);
    if (scePadReadState(s_pad, &d) != 0) return 0;
    uint32_t b = 0;
    if ((d.buttons & 0x10) || d.ly < 64) b |= B_UP;
    if ((d.buttons & 0x40) || d.ly > 192) b |= B_DOWN;
    if ((d.buttons & 0x80) || d.lx < 64) b |= B_LEFT;
    if ((d.buttons & 0x20) || d.lx > 192) b |= B_RIGHT;
    if (d.buttons & 0x4000) b |= B_CROSS;
    if (d.buttons & 0x2000) b |= B_CIRCLE;
    if (d.buttons & 0x8000) b |= B_SQUARE;
    if (d.buttons & 0x1000) b |= B_TRIANGLE;
    if (d.buttons & 0x400) b |= B_L1;
    if (d.buttons & 0x800) b |= B_R1;
    uint32_t pressed = b & ~s_last;
    const uint32_t dirs = B_UP | B_DOWN | B_LEFT | B_RIGHT;
    const double t = now_s();
    if (b & dirs) {
        if ((b & dirs) != (s_last & dirs)) s_repeat_at = t + 0.35;
        else if (t >= s_repeat_at) { pressed |= b & dirs; s_repeat_at = t + 0.09; }
    }
    s_last = b;
    if (s_first) { s_first = 0; return 0; }   /* the button that started the app */
    return pressed;
}

/* ---- Vulkan: the frame onto the TV ---- */
#define VKF(X) X(vkCreateInstance) X(vkEnumerateInstanceExtensionProperties)
#define VKI(X) X(vkEnumeratePhysicalDevices) X(vkGetPhysicalDeviceQueueFamilyProperties) X(vkCreateDevice) \
    X(vkGetDeviceProcAddr) X(vkGetPhysicalDeviceMemoryProperties) X(vkGetPhysicalDeviceSurfaceCapabilitiesKHR) \
    X(vkGetPhysicalDeviceSurfaceFormatsKHR) X(vkGetPhysicalDeviceSurfaceSupportKHR) \
    X(vkGetPhysicalDeviceDisplayPropertiesKHR) X(vkGetPhysicalDeviceDisplayPlanePropertiesKHR) \
    X(vkGetDisplayModePropertiesKHR) X(vkCreateDisplayPlaneSurfaceKHR)
#define VKD(X) X(vkGetDeviceQueue) X(vkCreateSwapchainKHR) X(vkGetSwapchainImagesKHR) X(vkAcquireNextImageKHR) \
    X(vkQueuePresentKHR) X(vkCreateCommandPool) X(vkAllocateCommandBuffers) X(vkBeginCommandBuffer) \
    X(vkEndCommandBuffer) X(vkQueueSubmit) X(vkCreateFence) X(vkWaitForFences) X(vkResetFences) \
    X(vkCreateSemaphore) X(vkCreateBuffer) X(vkGetBufferMemoryRequirements) X(vkAllocateMemory) \
    X(vkBindBufferMemory) X(vkMapMemory) X(vkCreateImage) X(vkGetImageMemoryRequirements) X(vkBindImageMemory) \
    X(vkCmdPipelineBarrier) X(vkCmdCopyBufferToImage) X(vkCmdBlitImage) X(vkResetCommandBuffer)
#define DECL(n) static PFN_##n p##n;
VKF(DECL) VKI(DECL) VKD(DECL)

static struct {
    VkInstance inst; VkPhysicalDevice phys; VkDevice dev; VkQueue q; uint32_t qf;
    VkSurfaceKHR surf; VkSwapchainKHR sc; VkImage sc_img[8]; uint32_t sc_n; VkExtent2D ext; VkFormat fmt;
    VkCommandPool pool; VkCommandBuffer cmd; VkFence fence; VkSemaphore acq, done;
    VkBuffer stage; VkDeviceMemory stage_mem; void* stage_ptr;
    VkImage pic; VkDeviceMemory pic_mem; int pic_init;
} V;

static PFN_vkVoidFunction gipa(VkInstance i, const char* n)
{
    PFN_vkVoidFunction f = vk_icdGetInstanceProcAddr(i, n);
    if (f) return f;
    if (!strcmp(n, "vkGetPhysicalDeviceProperties2")) return vk_icdGetInstanceProcAddr(i, "vkGetPhysicalDeviceProperties2KHR");
    if (!strcmp(n, "vkGetPhysicalDeviceFeatures2")) return vk_icdGetInstanceProcAddr(i, "vkGetPhysicalDeviceFeatures2KHR");
    return NULL;
}

static uint32_t mem_type(uint32_t bits, VkMemoryPropertyFlags want)
{
    VkPhysicalDeviceMemoryProperties mp;
    pvkGetPhysicalDeviceMemoryProperties(V.phys, &mp);
    for (uint32_t i = 0; i < mp.memoryTypeCount; i++)
        if ((bits & (1u << i)) && (mp.memoryTypes[i].propertyFlags & want) == want) return i;
    return 0;
}

static int vk_up(void)
{
    if (!vk_icdGetInstanceProcAddr) { logf_("RADV not linked\n"); return -1; }
#define LG(n) p##n = (PFN_##n)gipa(VK_NULL_HANDLE, #n);
    VKF(LG)
    const char* iext[] = { VK_KHR_SURFACE_EXTENSION_NAME, VK_KHR_DISPLAY_EXTENSION_NAME };
    VkApplicationInfo ai = { .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .pApplicationName = "inFamous ReCharged",
                             .apiVersion = VK_API_VERSION_1_0 };
    VkInstanceCreateInfo ci = { .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &ai,
                                .enabledExtensionCount = 2, .ppEnabledExtensionNames = iext };
    if (pvkCreateInstance(&ci, NULL, &V.inst) != VK_SUCCESS) { logf_("vkCreateInstance failed\n"); return -1; }
#define LI(n) if (!(p##n = (PFN_##n)gipa(V.inst, #n))) { logf_("missing %s\n", #n); return -1; }
    VKI(LI)
    uint32_t n = 1;
    if (pvkEnumeratePhysicalDevices(V.inst, &n, &V.phys) < 0 || !V.phys) { logf_("no GPU\n"); return -1; }
    /* the TV: the first display with a mode, 3840x2160 when offered (rsx_vulkan_backend.c) */
    VkDisplayPropertiesKHR disp[8]; VkDisplayPlanePropertiesKHR planes[16];
    uint32_t nd = 8, np = 16;
    if (pvkGetPhysicalDeviceDisplayPropertiesKHR(V.phys, &nd, disp) < 0 || !nd) { logf_("no display\n"); return -1; }
    if (pvkGetPhysicalDeviceDisplayPlanePropertiesKHR(V.phys, &np, planes) < 0 || !np) { logf_("no plane\n"); return -1; }
    VkDisplayKHR dsp = VK_NULL_HANDLE; VkDisplayModeKHR mode = VK_NULL_HANDLE; VkExtent2D ext = { 3840, 2160 };
    for (uint32_t i = 0; i < nd && !mode; i++) {
        VkDisplayModePropertiesKHR modes[32]; uint32_t nm = 32;
        if (pvkGetDisplayModePropertiesKHR(V.phys, disp[i].display, &nm, modes) < 0 || !nm) continue;
        dsp = disp[i].display; mode = modes[0].displayMode; ext = modes[0].parameters.visibleRegion;
        for (uint32_t m = 0; m < nm; m++)
            if (modes[m].parameters.visibleRegion.width == 3840 && modes[m].parameters.visibleRegion.height == 2160) {
                mode = modes[m].displayMode; ext = modes[m].parameters.visibleRegion; break; }
    }
    if (!mode) { logf_("no display mode\n"); return -1; }
    uint32_t plane = 0;
    for (uint32_t i = 0; i < np; i++)
        if (planes[i].currentDisplay == VK_NULL_HANDLE || planes[i].currentDisplay == dsp) { plane = i; break; }
    VkDisplaySurfaceCreateInfoKHR si = { .sType = VK_STRUCTURE_TYPE_DISPLAY_SURFACE_CREATE_INFO_KHR,
        .displayMode = mode, .planeIndex = plane, .planeStackIndex = planes[plane].currentStackIndex,
        .transform = VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR, .globalAlpha = 1.0f,
        .alphaMode = VK_DISPLAY_PLANE_ALPHA_OPAQUE_BIT_KHR, .imageExtent = ext };
    if (pvkCreateDisplayPlaneSurfaceKHR(V.inst, &si, NULL, &V.surf) != VK_SUCCESS) { logf_("display surface failed\n"); return -1; }
    /* a queue that does graphics and presents */
    VkQueueFamilyProperties qp[8]; uint32_t nq = 8;
    pvkGetPhysicalDeviceQueueFamilyProperties(V.phys, &nq, qp);
    V.qf = 0;
    for (uint32_t i = 0; i < nq; i++) {
        VkBool32 ok = VK_FALSE;
        pvkGetPhysicalDeviceSurfaceSupportKHR(V.phys, i, V.surf, &ok);
        if (ok && (qp[i].queueFlags & VK_QUEUE_GRAPHICS_BIT)) { V.qf = i; break; }
    }
    float prio = 1.0f;
    VkDeviceQueueCreateInfo qci = { .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueFamilyIndex = V.qf,
                                    .queueCount = 1, .pQueuePriorities = &prio };
    const char* dext[] = { VK_KHR_SWAPCHAIN_EXTENSION_NAME };
    VkDeviceCreateInfo dci = { .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1,
                               .pQueueCreateInfos = &qci, .enabledExtensionCount = 1, .ppEnabledExtensionNames = dext };
    if (pvkCreateDevice(V.phys, &dci, NULL, &V.dev) != VK_SUCCESS) { logf_("vkCreateDevice failed\n"); return -1; }
#define LD(n) if (!(p##n = (PFN_##n)pvkGetDeviceProcAddr(V.dev, #n))) { logf_("missing %s\n", #n); return -1; }
    VKD(LD)
    pvkGetDeviceQueue(V.dev, V.qf, 0, &V.q);
    /* the swapchain */
    VkSurfaceCapabilitiesKHR caps;
    pvkGetPhysicalDeviceSurfaceCapabilitiesKHR(V.phys, V.surf, &caps);
    VkSurfaceFormatKHR fmts[32]; uint32_t nf = 32;
    pvkGetPhysicalDeviceSurfaceFormatsKHR(V.phys, V.surf, &nf, fmts);
    VkSurfaceFormatKHR fmt = fmts[0];
    for (uint32_t i = 0; i < nf; i++) if (fmts[i].format == VK_FORMAT_B8G8R8A8_UNORM) { fmt = fmts[i]; break; }
    V.fmt = fmt.format;
    (void)sceSystemServiceHideSplashScreen();
    V.ext = caps.currentExtent;
    if (V.ext.width == 0xFFFFFFFFu) V.ext = ext;
    uint32_t count = caps.minImageCount + 1;
    if (caps.maxImageCount && count > caps.maxImageCount) count = caps.maxImageCount;
    VkSwapchainCreateInfoKHR sci = { .sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR, .surface = V.surf,
        .minImageCount = count, .imageFormat = fmt.format, .imageColorSpace = fmt.colorSpace, .imageExtent = V.ext,
        .imageArrayLayers = 1, .imageUsage = VK_IMAGE_USAGE_TRANSFER_DST_BIT, .imageSharingMode = VK_SHARING_MODE_EXCLUSIVE,
        .preTransform = caps.currentTransform, .compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR,
        .presentMode = VK_PRESENT_MODE_FIFO_KHR, .clipped = VK_TRUE };
    if (pvkCreateSwapchainKHR(V.dev, &sci, NULL, &V.sc) != VK_SUCCESS) { logf_("vkCreateSwapchainKHR failed\n"); return -1; }
    V.sc_n = 8;
    pvkGetSwapchainImagesKHR(V.dev, V.sc, &V.sc_n, V.sc_img);
    /* the 1920x1080 picture: a host buffer the CPU draws into and an image it is copied to */
    VkBufferCreateInfo bci = { .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = (VkDeviceSize)W * H * 4,
                               .usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT };
    pvkCreateBuffer(V.dev, &bci, NULL, &V.stage);
    VkMemoryRequirements mr; pvkGetBufferMemoryRequirements(V.dev, V.stage, &mr);
    VkMemoryAllocateInfo mai = { .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = mr.size,
        .memoryTypeIndex = mem_type(mr.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT) };
    if (pvkAllocateMemory(V.dev, &mai, NULL, &V.stage_mem) != VK_SUCCESS) { logf_("staging memory failed\n"); return -1; }
    pvkBindBufferMemory(V.dev, V.stage, V.stage_mem, 0);
    pvkMapMemory(V.dev, V.stage_mem, 0, VK_WHOLE_SIZE, 0, &V.stage_ptr);
    VkImageCreateInfo ici = { .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D,
        .format = VK_FORMAT_B8G8R8A8_UNORM, .extent = { W, H, 1 }, .mipLevels = 1, .arrayLayers = 1,
        .samples = VK_SAMPLE_COUNT_1_BIT, .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT, .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED };
    pvkCreateImage(V.dev, &ici, NULL, &V.pic);
    pvkGetImageMemoryRequirements(V.dev, V.pic, &mr);
    mai.allocationSize = mr.size; mai.memoryTypeIndex = mem_type(mr.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    if (pvkAllocateMemory(V.dev, &mai, NULL, &V.pic_mem) != VK_SUCCESS) { logf_("image memory failed\n"); return -1; }
    pvkBindImageMemory(V.dev, V.pic, V.pic_mem, 0);
    VkCommandPoolCreateInfo pci = { .sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
        .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, .queueFamilyIndex = V.qf };
    pvkCreateCommandPool(V.dev, &pci, NULL, &V.pool);
    VkCommandBufferAllocateInfo cai = { .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool = V.pool,
        .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1 };
    pvkAllocateCommandBuffers(V.dev, &cai, &V.cmd);
    VkFenceCreateInfo fci = { .sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, .flags = VK_FENCE_CREATE_SIGNALED_BIT };
    pvkCreateFence(V.dev, &fci, NULL, &V.fence);
    VkSemaphoreCreateInfo semi = { .sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO };
    pvkCreateSemaphore(V.dev, &semi, NULL, &V.acq);
    pvkCreateSemaphore(V.dev, &semi, NULL, &V.done);
    logf_("display %ux%u, swapchain %u images, format %d\n", V.ext.width, V.ext.height, V.sc_n, (int)V.fmt);
    return 0;
}

static void barrier(VkImage img, VkImageLayout from, VkImageLayout to, VkAccessFlags src, VkAccessFlags dst)
{
    VkImageMemoryBarrier b = { .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, .srcAccessMask = src, .dstAccessMask = dst,
        .oldLayout = from, .newLayout = to, .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = img, .subresourceRange = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 } };
    pvkCmdPipelineBarrier(V.cmd, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, 0, NULL, 0, NULL, 1, &b);
}

static void vk_present(void)
{
    pvkWaitForFences(V.dev, 1, &V.fence, VK_TRUE, UINT64_MAX);
    memcpy(V.stage_ptr, s_fb, (size_t)W * H * 4);
    uint32_t idx = 0;
    if (pvkAcquireNextImageKHR(V.dev, V.sc, UINT64_MAX, V.acq, VK_NULL_HANDLE, &idx) < 0) return;
    pvkResetFences(V.dev, 1, &V.fence);
    pvkResetCommandBuffer(V.cmd, 0);
    VkCommandBufferBeginInfo bi = { .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
                                    .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT };
    pvkBeginCommandBuffer(V.cmd, &bi);
    barrier(V.pic, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 0, VK_ACCESS_TRANSFER_WRITE_BIT);
    VkBufferImageCopy cp = { .imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 }, .imageExtent = { W, H, 1 } };
    pvkCmdCopyBufferToImage(V.cmd, V.stage, V.pic, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &cp);
    barrier(V.pic, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
            VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_TRANSFER_READ_BIT);
    barrier(V.sc_img[idx], VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 0, VK_ACCESS_TRANSFER_WRITE_BIT);
    VkImageBlit bl = { .srcSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 }, .srcOffsets = { { 0, 0, 0 }, { W, H, 1 } },
                       .dstSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 },
                       .dstOffsets = { { 0, 0, 0 }, { (int32_t)V.ext.width, (int32_t)V.ext.height, 1 } } };
    pvkCmdBlitImage(V.cmd, V.pic, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, V.sc_img[idx], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                    1, &bl, VK_FILTER_LINEAR);
    barrier(V.sc_img[idx], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR, VK_ACCESS_TRANSFER_WRITE_BIT, 0);
    pvkEndCommandBuffer(V.cmd);
    VkPipelineStageFlags ws = VK_PIPELINE_STAGE_TRANSFER_BIT;
    VkSubmitInfo si = { .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .waitSemaphoreCount = 1, .pWaitSemaphores = &V.acq,
        .pWaitDstStageMask = &ws, .commandBufferCount = 1, .pCommandBuffers = &V.cmd,
        .signalSemaphoreCount = 1, .pSignalSemaphores = &V.done };
    pvkQueueSubmit(V.q, 1, &si, V.fence);
    VkPresentInfoKHR pi = { .sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR, .waitSemaphoreCount = 1, .pWaitSemaphores = &V.done,
        .swapchainCount = 1, .pSwapchains = &V.sc, .pImageIndices = &idx };
    pvkQueuePresentKHR(V.q, &pi);
}

/* ---- the screens: the layout of the other recomps' menus (Saints Row: ReInstated's), at 1080p ---- */
#define C_WHITE 0xECE8E2
#define C_GREY 0x96928C
#define C_DIM 0x5A5854
#define C_TEXT 0xCDCAC4
#define C_ACCENT 0x38BDFF   /* inFamous's: Cole's lightning blue */
enum { P_HOME, P_CONTENT, P_SAVES, P_TROPHIES, P_SETTINGS, P_CREDITS, NPAGES };
static const char* page_name(int i)
{
    /* HOME CONTENT SAVES TROPHIES SETTINGS CREDITS in each kLangCode language (en-gb = en) */
    static const char* const n[16][NPAGES] = {
        { "HOME", "CONTENT", "SAVES", "TROPHIES", "SETTINGS", "CREDITS" },
        { "ACCUEIL", "CONTENU", "SAUVEGARDES", "TROPHÉES", "PARAMÈTRES", "CRÉDITS" },
        { "INICIO", "CONTENIDO", "PARTIDAS", "TROFEOS", "AJUSTES", "CRÉDITOS" },
        { "START", "INHALTE", "SPIELSTÄNDE", "TROPHÄEN", "EINSTELLUNGEN", "MITWIRKENDE" },
        { "HOME", "CONTENUTI", "SALVATAGGI", "TROFEI", "IMPOSTAZIONI", "RICONOSCIMENTI" },
        { "START", "INHOUD", "OPSLAGEN", "TROFEEËN", "INSTELLINGEN", "MAKERS" },
        { "INÍCIO", "CONTEÚDO", "SAVES", "TROFÉUS", "AJUSTES", "CRÉDITOS" },
        { "ГЛАВНАЯ", "КОНТЕНТ", "СОХРАНЕНИЯ", "ПРИЗЫ", "НАСТРОЙКИ", "АВТОРЫ" },
        { "START", "ZAWARTOŚĆ", "ZAPISY", "TROFEA", "USTAWIENIA", "TWÓRCY" },
        { "HOME", "CONTENT", "SAVES", "TROPHIES", "SETTINGS", "CREDITS" },
        { "INICIO", "CONTENIDO", "PARTIDAS", "TROFEOS", "AJUSTES", "CRÉDITOS" },
        { "INÍCIO", "CONTEÚDO", "JOGOS GUARDADOS", "TROFÉUS", "DEFINIÇÕES", "CRÉDITOS" },
        { "ホーム", "コンテンツ", "セーブ", "トロフィー", "設定", "クレジット" },
        { "홈", "콘텐츠", "세이브", "트로피", "설정", "크레딧" },
        { "首頁", "內容", "存檔", "獎盃", "設定", "製作人員" },
        { "ANA SAYFA", "İÇERİK", "KAYITLAR", "KUPALAR", "AYARLAR", "EMEĞİ GEÇENLER" } };
    return n[s_ml >= 0 && s_ml < 16 ? s_ml : 0][i];
}
enum { R_GPU, R_UPS, R_SHARP, R_AA, R_ANISO, R_LOOK, R_FG, R_FPS, R_LANG, R_SKIP_INTRO, R_SKIP_MOVIES, R_DLC, R_MUSIC, R_FX, R_DIAG, NROWS };

static img_t s_base[NGAMES];               /* each game's picture with the menu's shades baked in */
static img_t s_logo[NGAMES], s_logo_small[NGAMES], s_title;
static img_t s_logo_set[NGAMES], s_logo_set_small[NGAMES];   /* (SETTINGS' game list) */
static int s_installed[NGAMES];
static int s_needs_cache[NGAMES];   /* installed without the first-boot data (repair with X) */
static int s_inst_logged;
static const int kLogoH[NGAMES] = { 104, 104, 160 }, kLogoSmallH[NGAMES] = { 54, 54, 82 };   /* (FoB's: two lines) */
static const int kLogoSetH[NGAMES] = { 53, 53, 81 }, kLogoSetSmallH[NGAMES] = { 37, 37, 56 };

/* The menu's state: the page, its row, and what's easing toward where it's going. SETTINGS: in the
 * game list (in_list 0) or in that game's settings (1). */
static struct {
    int page, row, content_row, set_game, in_list;
    int save_game, save_row;    /* SAVES: whose saves, which backup */
    int tr_game, tr_scroll;     /* TROPHIES: whose, scrolled by */
    float shown_game, page_dark, page_in, tab_x, tab_w, tab_tx, tab_tw, scroll, time;
    int confirm_game;           /* (CONTENT: the game TRIANGLE was pressed on) */
    float confirm_t, reset_t;   /* (SQUARE pressed once / the recommended settings put back: when) */
    char error[160];
} M = { .confirm_t = -100, .reset_t = -100 };

static int PA(int a) { return (int)(a * (M.page_in < 1 ? M.page_in : 1)); }   /* faded in with the page */
static float PDX(void) { return (1 - (M.page_in < 1 ? M.page_in : 1)) * 24; }

/* A game's picture as the background: over a near-black, at 200/255 (Saints Row's), dark down the
 * menu's side and under the tab bar and footer. Made once per game; HOME shows it as is. */
static void bake_base(img_t* im)
{
    for (int y = 0; y < H; y++) {
        const int top = y < 170 ? 200 - y * 200 / 170 : 0;
        const int bot = y >= H - 150 ? (y - (H - 150)) * 210 / 150 : 0;
        for (int x = 0; x < W; x++) {
            uint32_t* p = &im->px[(size_t)y * W + x];
            const uint32_t s = *p;
            uint32_t c = 0xFF080808u;
            blend_px(&c, s, 200);
            const int side = x < W * 62 / 100 ? 235 - x * 235 / (W * 62 / 100) : 0;
            blend_px(&c, 0, side);
            blend_px(&c, 0, top);
            blend_px(&c, 0, bot);
            *p = c;
        }
    }
}

/* The background: the shown game's picture (two cross-fading while the choice moves), darkened by
 * the page's dark (none on HOME, most of it on the other pages). */
static void draw_background(void)
{
    const int g0 = (int)floorf(M.shown_game), g1 = g0 + 1 < NGAMES ? g0 + 1 : g0;
    const int w1 = (int)((M.shown_game - g0) * 256), w0 = 256 - w1;
    const int k = (int)((1 - M.page_dark) * 256);
    const uint32_t* a = s_base[g0].px;
    const uint32_t* b = s_base[g1].px;
    if (w1 < 2 && k > 254) { memcpy(s_fb, a, (size_t)W * H * 4); return; }
    for (size_t i = 0; i < (size_t)W * H; i++) {
        uint32_t c = a[i];
        uint32_t r = (c >> 16) & 255, g = (c >> 8) & 255, bl = c & 255;
        if (w1 >= 2) {
            const uint32_t d = b[i];
            r = (r * w0 + ((d >> 16) & 255) * w1) >> 8;
            g = (g * w0 + ((d >> 8) & 255) * w1) >> 8;
            bl = (bl * w0 + (d & 255) * w1) >> 8;
        }
        s_fb[i] = 0xFF000000u | (((r * k) >> 8) << 16) | (((g * k) >> 8) << 8) | ((bl * k) >> 8);
    }
}

static void draw_tabs(void)
{
    const int y = 58;
    int x = 140, ts = 40;
    /* the L1 / R1 marks either side */
    const int bw1 = text_w(&F_body, 20, "L1") + 18;
    rrect(x, y + 9, x + bw1, y + 37, 6, 1.5f, C_GREY, 255);
    textt(&F_body, 20, x + 9, y + 12, C_GREY, 255, "L1");
    x += bw1 + 30;
    {   /* (page names too long for the bar - Russian's - drawn smaller, R1 kept clear of the header's name) */
        const int right = (s_title.px ? W - 140 - s_title.w : W - 140 - text_w(&F_body, 20, "inFAMOUS  ReCHARGED")) - 24
                          - (text_w(&F_body, 20, "R1") + 18 - 22);
        int names = 0;
        for (int i = 0; i < NPAGES; i++) names += text_w(&F_item, 40, page_name(i));
        if (names > 0 && x + names + 52 * NPAGES > right) { ts = 40 * (right - x - 52 * NPAGES) / names; if (ts < 24) ts = 24; }
    }
    for (int i = 0; i < NPAGES; i++) {
        const int w = text_w(&F_item, ts, page_name(i));
        if (i == M.page) { M.tab_tx = x; M.tab_tw = w; if (M.tab_w == 0) { M.tab_x = x; M.tab_w = w; } }
        textt(&F_item, ts, x, y + (40 - ts) * 0.5f, i == M.page ? C_WHITE : C_GREY, 255, page_name(i));
        x += w + 52;
    }
    const int bw2 = text_w(&F_body, 20, "R1") + 18, bx = x - 22;
    rrect(bx, y + 9, bx + bw2, y + 37, 6, 1.5f, C_GREY, 255);
    textt(&F_body, 20, bx + 9, y + 12, C_GREY, 255, "R1");
    /* the project's name at the right (a title taller than 96 pixels, its glow, in proportion on the
     * tabs' middle) */
    if (s_title.px) {
        const int ty = s_title.h > 46 ? y + 20 - s_title.h / 2 : y - 2;
        img_draw(&s_title, W - 140 - s_title.w, ty, 255);
    } else {
        textt(&F_body, 20, W - 140 - text_w(&F_body, 20, "inFAMOUS  ReCHARGED"), y + 12, C_DIM, 255, "inFAMOUS  ReCHARGED");
    }
    rect((int)lroundf(M.tab_x), y + 56, (int)lroundf(M.tab_w), 5, C_ACCENT, 255);
    rect(140, y + 61, W - 280, 1, 0xFFFFFF, 40);
}

/* The footer's button hints, SQUARE and TRIANGLE (QUADRADO, TRIÂNGULO) drawn as the DualSense's
 * symbols, outlined like its buttons (X and O read as theirs already); returns the width. */
static int hints_draw(int x, int y, uint32_t rgb, int draw, const char* t)
{
    static const char* const words[] = { "SQUARE", "QUADRADO", "TRIANGLE", "TRIÂNGULO" };
    const int x0 = x, icon = 15, cy = y + 11;
    char part[256];
    while (*t) {
        const char* at = NULL;
        int word = -1;
        for (int k = 0; k < 4; k++) {
            const char* a = strstr(t, words[k]);
            if (a && (!at || a < at)) { at = a; word = k; }
        }
        const size_t n = at ? (size_t)(at - t) : strlen(t);
        if (n) {
            memcpy(part, t, n < sizeof part ? n : sizeof part - 1); part[n < sizeof part ? n : sizeof part - 1] = 0;
            if (draw) textt(&F_body, 22, x, y, rgb, 255, part);
            x += text_w(&F_body, 22, part);
        }
        if (!at) break;
        if (draw && word < 2) {
            rect(x + 1, cy - 7, icon - 2, 2, rgb, 255); rect(x + 1, cy + 5, icon - 2, 2, rgb, 255);
            rect(x + 1, cy - 7, 2, 14, rgb, 255); rect(x + icon - 3, cy - 7, 2, 14, rgb, 255);
        } else if (draw) {
            for (int j = 0; j < 13; j++) {   /* (an outline: the two sides, then the base) */
                const float hw = (icon - 1) * 0.5f * j / 12.0f;
                rect((int)(x + icon * 0.5f - hw), cy - 7 + j, 2, 1, rgb, 255);
                rect((int)(x + icon * 0.5f + hw) - 1, cy - 7 + j, 2, 1, rgb, 255);
            }
            rect(x, cy + 5, icon, 2, rgb, 255);
        }
        x += icon;
        t = at + strlen(words[word]);
    }
    return x - x0;
}

/* The clock (clock 1) and the SAVES page's dates: English and English (UK) as before (WED / NOV 11 / 07:32 PM, Nov 11 19:27),
 * Portuguese (Brazil) with its own day and month names (QUA / 11 NOV / 19:32, 11 nov 19:27); every other language numbers
 * only, year first, 24 hours (2026-11-11 19:32): the launcher has no per-language date names or orders beyond these. */
static void when_text(char* out, size_t n, const struct tm* tm, int clock)
{
    static const char* const days[] = { "dom", "seg", "ter", "qua", "qui", "sex", "sáb" };
    static const char* const months[] = { "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez" };
    if (s_pt && clock) snprintf(out, n, "%s / %02d %s / %02d:%02d", days[tm->tm_wday % 7], tm->tm_mday, months[tm->tm_mon % 12], tm->tm_hour, tm->tm_min);
    else if (s_pt) snprintf(out, n, "%02d %s %02d:%02d", tm->tm_mday, months[tm->tm_mon % 12], tm->tm_hour, tm->tm_min);
    else if (s_ml == 0 || s_ml == 9) strftime(out, n, clock ? "%a / %b %d / %I:%M %p" : "%b %d %H:%M", tm);
    else strftime(out, n, "%Y-%m-%d %H:%M", tm);
}

static void draw_footer(void)
{
    const int y = H - 92;
    const char* hints =
        M.page == P_HOME && !s_installed[S.game] ? T("UP DOWN  GAME      X  INSTALL      TRIANGLE  LOOK AGAIN      L1 R1  PAGES", "CIMA BAIXO  JOGO      X  INSTALAR      TRIÂNGULO  PROCURAR      L1 R1  PÁGINAS")
        : M.page == P_HOME ? T("UP DOWN  GAME      X  PLAY      L1 R1  PAGES", "CIMA BAIXO  JOGO      X  JOGAR      L1 R1  PÁGINAS")
        : M.page == P_TROPHIES ? T("LEFT RIGHT  GAME      UP DOWN  SCROLL      O  BACK      L1 R1  PAGES", "ESQ DIR  JOGO      CIMA BAIXO  ROLAR      O  VOLTAR      L1 R1  PÁGINAS")
        : M.page == P_SAVES ? T("LEFT RIGHT  GAME      UP DOWN  BACKUP      SQUARE  BACK UP NOW      X TWICE  RESTORE      TRIANGLE TWICE  DELETE      L1 R1  PAGES",
                                "ESQ DIR  JOGO      CIMA BAIXO  BACKUP      QUADRADO  GUARDAR AGORA      X 2X  RESTAURAR      TRIÂNGULO 2X  APAGAR      L1 R1  PÁGINAS")
        : M.page == P_CONTENT ? T("UP DOWN  GAME      X  INSTALL      TRIANGLE TWICE  UNINSTALL      SQUARE  LOOK AGAIN      O  BACK      L1 R1  PAGES",
                                  "CIMA BAIXO  JOGO      X  INSTALAR      TRIÂNGULO 2X  DESINSTALAR      QUADRADO  PROCURAR      O  VOLTAR      L1 R1  PÁGINAS")
        : M.page == P_SETTINGS && !M.in_list ? T("UP DOWN  GAME      X  SETTINGS      SQUARE  RECOMMENDED      O  BACK      L1 R1  PAGES", "CIMA BAIXO  JOGO      X  AJUSTES      QUADRADO  RECOMENDADO      O  VOLTAR      L1 R1  PÁGINAS")
        : M.page == P_SETTINGS ? T("UP DOWN  MOVE      LEFT RIGHT  CHANGE      SQUARE  RECOMMENDED      O  GAMES      L1 R1  PAGES", "CIMA BAIXO  MOVER      ESQUERDA DIREITA  MUDAR      QUADRADO  RECOMENDADO      O  JOGOS      L1 R1  "
                                   "PÁGINAS")
        : T("O  BACK      L1 R1  PAGES", "O  VOLTAR      L1 R1  PÁGINAS");
    const int hw = hints_draw(140, y, 0, 0, hints);
    /* HOME leaves the picture undimmed: a shade in the corner under the hints, fading out to the left
     * and upward */
    float sh = 1.0f - M.page_dark / 0.74f;
    if (sh < 0) sh = 0;
    if (sh > 0.01f) {
        const int xs = W - 140 - hw - 40, ys = H - 150, f = 160, c = (int)(200 * sh);
        shade(xs, ys, W, H, c, c, c, c);
        shade(xs, ys - f, W, ys, 0, 0, c, c);
        shade(xs - f, ys, xs, H, 0, c, c, 0);
        shade(xs - f, ys - f, xs, ys, 0, 0, c, 0);
    }
    rect(140, y - 18, W - 280, 1, 0xFFFFFF, 40);
    char date[64] = "";
    const time_t now = time(NULL);
    const struct tm* tm = localtime(&now);
    if (tm) when_text(date, sizeof date, tm, 1);
    upper(date);
    if (140 + text_w(&F_body, 22, date) + 40 <= W - 140 - hw)   /* (hints as long as Russian SAVES': no room for the clock) */
        textt(&F_body, 22, 140, y, C_ACCENT, 255, date);
    hints_draw(W - 140 - hw, y, C_ACCENT, 1, hints);
}

/* A message on a dark panel with the accent's bar at its left; returns the y under it. */
static float panel_msg(float x, float y, float w, const char* msg, uint32_t bar)
{
    const int th = text_wrap(&F_body, 26, 0, 0, (int)w, 0, 0, msg, 0);
    rrect(x - 16, y - 12, x + w + 16, y + th + 12, 6, 0, 0x06101C, PA(225));
    rect((int)(x - 16), (int)(y - 12), 6, th + 24, bar, PA(255));
    text_wrap(&F_body, 26, x, y, (int)w, C_WHITE, PA(255), msg, 1);
    return y + th + 42;
}

/* inFAMOUS 2's updates from PSN (installer.c updl_*): the ones to download for game g (its disc found, updates
 * missing), 0 none; and the download's progress / failure as a message ("" when there's nothing to say).
 * X once only says where it connects (M.confirm_game UPDL_CONFIRM, 3 s); X again starts it (updl_go). */
enum { UPDL_CONFIRM = 300 };   /* (M.confirm_game: CONTENT's games 0-2, SAVES 100+ / 200+) */
static int confirming(void);
static unsigned updl_offer(int g) { return g == INST_IF2 && !s_installed[g] ? inst_if2_missing() : 0; }
static void updl_text(char* msg, size_t n, int g)
{
    msg[0] = 0;
    if (g != INST_IF2) return;
    if (s_updl.state != 1 && updl_offer(g) && confirming() && M.confirm_game == UPDL_CONFIRM) {
        uint64_t mb = 0; const unsigned m = updl_offer(g);
        for (int u = 0; u < 4; u++) if (m & 1u << u) mb += kUpdlPkgs[u].size;
        snprintf(msg, n, m == 0xF ? T("This connects over the internet to Sony's PlayStation 3 update server\nfor inFAMOUS 2's four official updates (%.0f MB). PRESS X AGAIN TO START.",
                                      "Isto se conecta pela internet ao servidor de atualizações do PlayStation 3 da Sony\npara as quatro atualizações oficiais de inFAMOUS 2 (%.0f MB). APERTE X DE NOVO PARA COMEÇAR.")
                                  : T("This connects over the internet to Sony's PlayStation 3 update server\nfor inFAMOUS 2's missing official updates (%.0f MB). PRESS X AGAIN TO START.",
                                      "Isto se conecta pela internet ao servidor de atualizações do PlayStation 3 da Sony\npara as atualizações oficiais de inFAMOUS 2 que faltam (%.0f MB). APERTE X DE NOVO PARA COMEÇAR."), mb / 1e6);
    } else if (s_updl.state == 1)
        snprintf(msg, n, T("DOWNLOADING inFAMOUS 2'S UPDATES  %d%%\n%s (%d of %d)   %.0f OF %.0f MB\nKeep the app open until it's done.%s%s",
                           "BAIXANDO AS ATUALIZAÇÕES DE inFAMOUS 2  %d%%\n%s (%d de %d)   %.0f DE %.0f MB\nDeixe o app aberto até terminar.%s%s"),
                 (int)(s_updl.total ? 100.0 * s_updl.done / s_updl.total : 0), TI(s_updl.cur), s_updl.file, s_updl.nfiles,
                 s_updl.done / 1e6, s_updl.total / 1e6, s_updl.err[0] ? "\n" : "", s_updl.err[0] ? TI(s_updl.err) : "");
    else if (s_updl.state == 3 && updl_offer(g))
        snprintf(msg, n, T("THE DOWNLOAD STOPPED\n%s\nPress X to try again (it goes on from where it stopped).",
                           "O DOWNLOAD PAROU\n%s\nAperte X para tentar de novo (ele continua de onde parou)."), TI(s_updl.err));
    else if (updl_offer(g)) {
        uint64_t mb = 0; const unsigned m = updl_offer(g);
        for (int u = 0; u < 4; u++) if (m & 1u << u) mb += kUpdlPkgs[u].size;
        snprintf(msg, n, T("Press X to download them from PlayStation Network (%.0f MB, into install/).",
                           "Aperte X para baixá-las da PlayStation Network (%.0f MB, em install/)."), mb / 1e6);
    }
}
static int updl_go(int g)   /* X with only updates missing: the notice first, X again within 3 s starts the download */
{
    const unsigned m = updl_offer(g);
    if (!m || s_updl.state == 1 || s_inst.state == 1) return -1;
    if (!(confirming() && M.confirm_game == UPDL_CONFIRM)) {
        M.confirm_t = M.time; M.confirm_game = UPDL_CONFIRM;
        logf_("updates: X once: the notice (Sony's PS3 update server, over the internet) is shown; X again within 3 s starts\n");
        return 0;
    }
    M.confirm_t = -100;
    if (updl_start(APP, m)) { logf_("updates: couldn't start: %s\n", s_updl.err); return -1; }
    logf_("updates: download started: %d file(s), %.0f MB, from http://%s into " APP "/install (mask 0x%X)\n", s_updl.nfiles, s_updl.total / 1e6, kUpdlHost, m);
    return 0;
}

/* A game that isn't installed: what the installer found for it, its progress, or what's missing. */
static float draw_install(float left, float y, int g)
{
    char msg[1200];
    if (!s_installed[g] && g == INST_IF2 && s_updl.state == 1) {
        updl_text(msg, sizeof msg, g);
        const float y1 = panel_msg(left, y, 900, msg, C_ACCENT);
        rect((int)left - 16, (int)y1 - 30, 932, 8, 0x06101C, PA(225));
        rect((int)left - 16, (int)y1 - 30, (int)(932 * (s_updl.total ? (double)s_updl.done / s_updl.total : 0)), 8, C_ACCENT, PA(255));
        return y1 + 6;
    }
    if (s_inst.state == 1 && s_inst.game == g) {
        const double f = s_inst.total ? (double)s_inst.done / s_inst.total : 0;
        snprintf(msg, sizeof msg, T("INSTALLING  %d%%   %.1f OF %.1f GB\n%s\nKeep the app open until it's done.",
                                    "INSTALANDO  %d%%   %.1f DE %.1f GB\n%s\nDeixe o app aberto até terminar."),
                 (int)(f * 100), s_inst.done / 1e9, s_inst.total / 1e9, TI(s_inst.cur));
        const float y1 = panel_msg(left, y, 900, msg, C_ACCENT);
        rect((int)left - 16, (int)y1 - 30, 932, 8, 0x06101C, PA(225));
        rect((int)left - 16, (int)y1 - 30, (int)(932 * f), 8, C_ACCENT, PA(255));
        return y1 + 6;
    }
    if (s_inst.state == 3 && s_inst.game == g) {
        snprintf(msg, sizeof msg, T("THE INSTALL STOPPED\n%s\nPress X to try again.", "A INSTALAÇÃO PAROU\n%s\nAperte X para tentar de novo."), TI(s_inst.err));
        return panel_msg(left, y, 900, msg, 0xE63228);
    }
    if (s_installed[g] && s_needs_cache[g] && inst_needs_eboot(APP, g)) {
        snprintf(msg, sizeof msg, "%s", T("REPAIR NEEDED\nThis install was made by an older version and lacks the game's program file (EBOOT). Press X to make it from your dump (it must still be in install/ or on a USB drive; FoB also needs its .rap).",
                                          "REPARO NECESSÁRIO\nEsta instalação foi feita por uma versão antiga e não tem o arquivo do programa do jogo (EBOOT). Aperte X para criá-lo a partir do seu dump (ele precisa estar em install/ ou num USB; FoB também precisa do .rap)."));
        return panel_msg(left, y, 900, msg, C_ACCENT);
    }
    if (s_installed[g] && s_needs_cache[g]) {
        snprintf(msg, sizeof msg, T("FIRST-BOOT DATA MISSING\nThis install doesn't have the data the game copies on its first start (it would copy it for hours while you play). Press X to prepare it now (about 1.3 GB from the installed game).",
                                    "DADOS DA PRIMEIRA INICIALIZAÇÃO FALTANDO\nEsta instalação não tem os dados que o jogo copia na primeira vez (ele copiaria por horas enquanto você joga). Aperte X para prepará-los agora (cerca de 1,3 GB do jogo instalado)."));
        return panel_msg(left, y, 900, msg, C_ACCENT);
    }
    inst_src_t* o[8]; char need[300];
    const int n = inst_plan(g, o, need, sizeof need);
    if (n) {
        char from[600] = ""; uint64_t gb = 0; int untested = 0;
        for (int i = 0; i < n; i++) {
            const size_t l = strlen(from);
            snprintf(from + l, sizeof from - l, "%s%s", i ? ", " : "", o[i]->name);
            gb += o[i]->total;
            if (!kInstKnown[o[i]->known].tested) untested = 1;
        }
        snprintf(msg, sizeof msg, T("%s ISN'T INSTALLED YET\nReady to install from: %s (%.1f GB).%s\nPress X to install. The files you copied stay; delete them afterwards to free the space.",
                                    "%s AINDA NÃO ESTÁ INSTALADO\nPronto para instalar de: %s (%.1f GB).%s\nAperte X para instalar. Os arquivos copiados ficam; apague-os depois para liberar espaço."),
                 kName[g], from, gb / 1e9, untested ? T(" This edition hasn't been tested yet.", " Esta edição ainda não foi testada.") : "");
        return panel_msg(left, y, 900, msg, C_ACCENT);
    }
    snprintf(msg, sizeof msg, T("%s ISN'T INSTALLED\nCopy %s into PPSA95463/install on the console (or onto a USB drive), then press TRIANGLE to look again.",
                                "%s NÃO ESTÁ INSTALADO\nCopie %s para PPSA95463/install no console (ou num pendrive) e aperte TRIÂNGULO para procurar de novo."),
             kName[g], TI(need));
    if (updl_offer(g)) { char u[600]; updl_text(u, sizeof u, g); snprintf(msg + strlen(msg), sizeof msg - strlen(msg), "\n%s", u); }
    for (int i = 0; i < s_inst_nnotes && strlen(msg) + 210 < sizeof msg; i++) {
        const size_t l = strlen(msg);
        snprintf(msg + l, sizeof msg - l, "\n%s", TI(s_inst_notes[i]));
    }
    return panel_msg(left, y, 900, msg, C_ACCENT);
}

static void tr_counts(int g, int* got, int* all);
static void draw_home(void)
{
    const float left = 140 + PDX();
    float y = 200;
    /* the three games: the chosen one's logo large with PLAY, the others' small */
    for (int g = 0; g < NGAMES; g++) {
        const int sel = g == S.game;
        const img_t* logo = sel ? &s_logo[g] : &s_logo_small[g];
        const int h = sel ? kLogoH[g] : kLogoSmallH[g];
        if (sel) {
            const float pulse = 0.7f + 0.3f * sinf(M.time * 5.0f);
            rect((int)(left - 38), (int)(y + h * 0.12f), 14, (int)(h * 0.76f), C_ACCENT, PA((int)(255 * pulse)));
        }
        if (logo->px) img_draw(logo, (int)left, (int)y, PA(sel ? 255 : 200));
        else textt(&F_title, h, left, y - h * 0.1f, sel ? C_WHITE : C_GREY, PA(255), kName[g]);
        y += h + (sel ? 14 : 26);
        if (!sel) continue;
        textt(&F_item, 72, left, y, C_WHITE, PA(255), s_installed[g] ? T("PLAY", "JOGAR") : T("INSTALL", "INSTALAR"));
        y += 72 + 20;
        if (M.error[0]) y = panel_msg(left, y, 900, M.error, 0xE63228);
        if (!s_installed[g]) {
            y = draw_install(left, y, g);
        } else if (s_needs_cache[g] || (s_inst.state == 1 && s_inst.game == g)) {
            y = draw_install(left, y, g);   /* repair: the game's first-boot data */
        } else {
            y += text_wrap(&F_body, 26, left, y, 900, C_GREY, PA(255), T(kBlurb[g], kBlurbPt[g]), 1) + 28;
            int got, all; tr_counts(g, &got, &all);
            if (all > 0) { char tl[80]; snprintf(tl, sizeof tl, T("TROPHIES  %d OF %d  -  %d%%", "TROFÉUS  %d DE %d  -  %d%%"), got, all, got * 100 / all);
                           textt(&F_body, 26, left, y, C_ACCENT, PA(255), tl); y += 40; }
        }
        y += 30;
    }
}

static int confirming(void);
/* After an install: offer to delete the dumps it used from install/ (MGR's keep/delete prompt). X twice deletes, O keeps. */
static int s_cleanup_g = -1, s_cleanup_n; static char s_cleanup_path[8][512]; static int s_cleanup_dir[8]; static uint64_t s_cleanup_bytes;
static void cleanup_offer(int g)
{
    inst_src_t* o[8]; char need[300]; s_cleanup_n = 0; s_cleanup_bytes = 0;
    const int n = inst_plan(g, o, need, sizeof need);
    for (int i = 0; i < n && s_cleanup_n < 8; i++) {
        if (strncmp(o[i]->path, APP "/install/", strlen(APP "/install/"))) continue;   /* only what's in install/ (not USB) */
        snprintf(s_cleanup_path[s_cleanup_n], sizeof s_cleanup_path[0], "%s", o[i]->path);
        s_cleanup_dir[s_cleanup_n] = o[i]->kind == SRC_DIR;
        s_cleanup_bytes += o[i]->total; s_cleanup_n++;
    }
    s_cleanup_g = s_cleanup_n ? g : -1;
}
static void cleanup_do(void)
{
    for (int i = 0; i < s_cleanup_n; i++) {
        if (s_cleanup_dir[i]) inst_rmtree(s_cleanup_path[i]); else unlink(s_cleanup_path[i]);
        logf_("cleanup: deleted %s\n", s_cleanup_path[i]);
    }
    s_cleanup_g = -1; inst_scan(APP);
}
/* CONTENT (2026-11-09, as the other ports' launchers): each game's state; X installs (or prepares the missing first-boot
 * data), TRIANGLE twice uninstalls (the saves in <game>/game/gamedata stay), SQUARE looks in install/ again. */
static volatile int s_uninst_busy;
static void* uninst_thread(void* arg)
{
    const int g = (int)(intptr_t)arg; char p[300];
    snprintf(p, sizeof p, APP "/%s/game/PS3_GAME", kDir[g]); inst_rmtree(p);
    snprintf(p, sizeof p, APP "/%s/game/PS3_GAME.part", kDir[g]); inst_rmtree(p);
    snprintf(p, sizeof p, APP "/%s/game/dev_hdd0/game", kDir[g]); inst_rmtree(p);
    snprintf(p, sizeof p, APP "/%s/installed.txt", kDir[g]); unlink(p);
    logf_("uninstall %s: done (saves kept)\n", kDir[g]);
    s_uninst_busy = 0;
    return NULL;
}
static void content_uninstall(int g)
{
    if (s_uninst_busy || s_inst.state == 1) return;
    s_uninst_busy = 1; s_installed[g] = 0; s_needs_cache[g] = 0;
    pthread_t t;
    if (pthread_create(&t, NULL, uninst_thread, (void*)(intptr_t)g)) { s_uninst_busy = 0; return; }
    pthread_detach(t);
}
static void draw_content(void)
{
    const float left = 140 + PDX();
    float y = 200;
    for (int r = 0; r < NGAMES; r++) {
        const int sel = r == M.content_row, fs = 40;
        if (sel) rect((int)(left - 30), (int)(y + 8), 10, fs - 8, C_ACCENT, PA(255));
        textt(&F_item, fs, left, y, sel ? C_WHITE : C_GREY, PA(255), kName[r]);
        char st[64];
        if (s_inst.state == 1 && s_inst.game == r) snprintf(st, sizeof st, T("INSTALLING  %d%%", "INSTALANDO  %d%%"), (int)(s_inst.total ? 100.0 * s_inst.done / s_inst.total : 0));
        else if (r == INST_IF2 && !s_installed[r] && s_updl.state == 1) snprintf(st, sizeof st, T("DOWNLOADING  %d%%", "BAIXANDO  %d%%"), (int)(s_updl.total ? 100.0 * s_updl.done / s_updl.total : 0));
        else if (s_uninst_busy && !s_installed[r]) snprintf(st, sizeof st, "%s", T("REMOVING...", "REMOVENDO..."));
        else if (s_installed[r] && s_needs_cache[r] && inst_needs_eboot(APP, r)) snprintf(st, sizeof st, "%s", T("REPAIR NEEDED", "REPARO NECESSÁRIO"));
        else if (s_installed[r] && s_needs_cache[r]) snprintf(st, sizeof st, "%s", T("FIRST-BOOT DATA MISSING", "FALTAM DADOS INICIAIS"));
        else snprintf(st, sizeof st, "%s", s_installed[r] ? T("INSTALLED", "INSTALADO") : T("NOT INSTALLED", "NÃO INSTALADO"));
        textt(&F_body, 28, left + 560, y + 8, s_installed[r] ? C_WHITE : C_GREY, PA(255), st);
        y += fs + 6 + 18;
    }
    /* the focused row's details, at the right */
    const int g = M.content_row;
    const float px = 1180 + PDX(), pw = W - 140 - px;
    rect((int)(px - 40), 200, 1, 560, 0xFFFFFF, PA(40));
    char msg[1600]; msg[0] = 0;
    if (s_inst.state == 1 && s_inst.game == g) {
        snprintf(msg, sizeof msg, T("INSTALLING  %.1f OF %.1f GB\n%s\nKeep the app open until it's done.", "INSTALANDO  %.1f DE %.1f GB\n%s\nDeixe o app aberto até terminar."),
                 s_inst.done / 1e9, s_inst.total / 1e9, TI(s_inst.cur));
    } else if (s_installed[g] && s_needs_cache[g] && inst_needs_eboot(APP, g)) {
        snprintf(msg, sizeof msg, "%s", T("This install lacks the game's program file (EBOOT). X makes it from your dump (install/ or USB; FoB also needs its .rap).",
                                          "Esta instalação não tem o arquivo do programa (EBOOT). X o cria a partir do seu dump (install/ ou USB; FoB também precisa do .rap)."));
    } else if (s_installed[g] && s_needs_cache[g]) {
        snprintf(msg, sizeof msg, "%s", T("The data this game copies on its first start is missing. X prepares it from the installed game (about a minute).",
                                          "Faltam os dados que o jogo copia na primeira vez. X prepara-os a partir do jogo instalado (cerca de um minuto)."));
    } else if (s_installed[g]) {
        char from[600] = "", p[200]; snprintf(p, sizeof p, APP "/%s/installed.txt", kDir[g]);
        FILE* f = fopen(p, "r");
        if (f) { char l[200]; size_t k = 0; while (fgets(l, sizeof l, f) && k < sizeof from - 210) { k += (size_t)snprintf(from + k, sizeof from - k, "  %s", l); } fclose(f); }
        snprintf(msg, sizeof msg, T("INSTALLED%s%s\n\nTRIANGLE twice: uninstall (your saves stay; the dumps in install/ are not touched).",
                                    "INSTALADO%s%s\n\nTRIÂNGULO duas vezes: desinstalar (seus saves ficam; os arquivos em install/ não são tocados)."),
                 from[0] ? T(" from:\n", " a partir de:\n") : "", from);
        if (confirming() && M.confirm_game == g) snprintf(msg + strlen(msg), sizeof msg - strlen(msg), "%s", T("\n\nPRESS TRIANGLE AGAIN TO UNINSTALL", "\n\nAPERTE TRIÂNGULO DE NOVO PARA DESINSTALAR"));
    } else {
        inst_src_t* o[8]; char need[300];
        const int n = inst_plan(g, o, need, sizeof need);
        if (n) { size_t k = (size_t)snprintf(msg, sizeof msg, "%s", T("READY TO INSTALL from install/:\n", "PRONTO PARA INSTALAR de install/:\n"));
                 for (int i = 0; i < n && k < sizeof msg - 200; i++) k += (size_t)snprintf(msg + k, sizeof msg - k, "  %s\n", o[i]->name);
                 snprintf(msg + k, sizeof msg - k, "%s", T("\nX: install.", "\nX: instalar.")); }
        else if (g == INST_IF2 && s_updl.state == 1) updl_text(msg, sizeof msg, g);
        else if (updl_offer(g)) { char u[700]; updl_text(u, sizeof u, g);
            snprintf(msg, sizeof msg, T("NOT INSTALLED\nMissing: %s\n%s\nOr copy them into PPSA95463/install (or a USB drive), then SQUARE to look again.",
                                        "NÃO INSTALADO\nFalta: %s\n%s\nOu copie-as em PPSA95463/install (ou num pen drive) e aperte QUADRADO para procurar de novo."), TI(need), u); }
        else snprintf(msg, sizeof msg, T("NOT INSTALLED\nMissing: %s\nCopy your dumps into PPSA95463/install (or a USB drive), then SQUARE to look again.",
                                         "NÃO INSTALADO\nFalta: %s\nCopie seus arquivos em PPSA95463/install (ou num pen drive) e aperte QUADRADO para procurar de novo."), TI(need));
        for (int i = 0; i < s_inst_nnotes && strlen(msg) < sizeof msg - 300; i++) snprintf(msg + strlen(msg), sizeof msg - strlen(msg), "\n%s", TI(s_inst_notes[i]));
    }
    text_wrap(&F_body, 26, px, 204, (int)pw, C_TEXT, PA(255), msg, 1);
}

/* SAVES (2026-11-09, as the other ports): each game's saves (<game>/game/gamedata/.../savedata) and their backups in
 * <app>/saves_backup/<game>/<date_time>/. SQUARE backs up now, X twice restores the chosen backup (the current saves are
 * backed up first), TRIANGLE twice deletes a backup. Saves are small: plain copies. */
static void save_dir(int g, char* out, size_t n) { snprintf(out, n, APP "/%s/game/gamedata/dev_hdd0/home/00000001/savedata", kDir[g]); }
static int save_copy_tree(const char* src, const char* dst)
{
    struct stat st; if (stat(src, &st)) return -1;
    if (S_ISDIR(st.st_mode)) {
        mkdir(dst, 0777);
        DIR* d = opendir(src); if (!d) return -1;
        struct dirent* de; int r = 0;
        while ((de = readdir(d))) {
            if (!strcmp(de->d_name, ".") || !strcmp(de->d_name, "..")) continue;
            char a[600], b[600]; snprintf(a, sizeof a, "%s/%s", src, de->d_name); snprintf(b, sizeof b, "%s/%s", dst, de->d_name);
            r |= save_copy_tree(a, b);
        }
        closedir(d); return r;
    }
    FILE* i = fopen(src, "rb"); if (!i) return -1;
    FILE* o = fopen(dst, "wb"); if (!o) { fclose(i); return -1; }
    char buf[65536]; size_t k; int r = 0;
    while ((k = fread(buf, 1, sizeof buf, i)) > 0) if (fwrite(buf, 1, k, o) != k) { r = -1; break; }
    fclose(i); if (fclose(o)) r = -1;
    return r;
}
static int save_count_slots(const char* dir, time_t* newest)
{
    DIR* d = opendir(dir); if (!d) return 0;
    struct dirent* de; int n = 0;
    while ((de = readdir(d))) {
        if (de->d_name[0] == '.') continue;
        char p[600]; struct stat st; snprintf(p, sizeof p, "%s/%s", dir, de->d_name);
        if (!stat(p, &st) && S_ISDIR(st.st_mode)) { n++; if (newest && st.st_mtime > *newest) *newest = st.st_mtime; }
    }
    closedir(d); return n;
}
static char s_bk[32][24]; static int s_nbk = -1, s_bk_game = -1;   /* the chosen game's backups, newest first */
static void saves_list(int g)
{
    char p[300]; snprintf(p, sizeof p, APP "/saves_backup/%s", kDir[g]);
    s_nbk = 0; s_bk_game = g;
    DIR* d = opendir(p); if (!d) return;
    struct dirent* de;
    while ((de = readdir(d)) && s_nbk < 32)   /* (a name that doesn't fit would be cut: its path would name another folder) */
        if (de->d_name[0] != '.' && strlen(de->d_name) < sizeof s_bk[0]) snprintf(s_bk[s_nbk++], sizeof s_bk[0], "%s", de->d_name);
    closedir(d);
    for (int i = 0; i < s_nbk; i++) for (int j = i + 1; j < s_nbk; j++) if (strcmp(s_bk[i], s_bk[j]) < 0) { char t[24]; memcpy(t, s_bk[i], 24); memcpy(s_bk[i], s_bk[j], 24); memcpy(s_bk[j], t, 24); }
}
static char s_save_msg[200]; static double s_save_msg_t = -100;
static int saves_backup(int g)
{
    char src[300], dst[400]; save_dir(g, src, sizeof src);
    time_t now = time(NULL); char stamp[24]; strftime(stamp, sizeof stamp, "%Y%m%d_%H%M%S", localtime(&now));
    struct stat st;   /* (a backup from the same second exists: a new folder, never a copy over that one) */
    for (int k = 2; k < 100; k++) {
        snprintf(dst, sizeof dst, APP "/saves_backup/%s/%s", kDir[g], stamp);
        if (stat(dst, &st)) break;
        stamp[15] = 0; snprintf(stamp + 15, sizeof stamp - 15, "_%d", k);
    }
    snprintf(dst, sizeof dst, APP "/saves_backup/%s/%s/", kDir[g], stamp); inst_mkdirs(dst);
    dst[strlen(dst) - 1] = 0;
    const int r = save_copy_tree(src, dst);
    logf_("saves %s: backup %s -> %s\n", kDir[g], stamp, r ? "FAILED" : "ok");
    saves_list(g);
    return r;
}
/* (2026-11-12) The chosen backup's folder, or 0 for a row that isn't one (never an empty stamp: that path is the
 * game's whole saves_backup folder). */
static int saves_bk_path(int g, int row, char* out, size_t n)
{
    if (row < 0 || row >= s_nbk || s_bk_game != g || !s_bk[row][0] || s_bk[row][0] == '.' || strchr(s_bk[row], '/')) return 0;
    snprintf(out, n, APP "/saves_backup/%s/%s", kDir[g], s_bk[row]);
    return 1;
}
static void saves_msg_rm(const char* what)   /* s_save_msg + log: what failed, from inst_rmtree's first failure */
{
    snprintf(s_save_msg, sizeof s_save_msg, "%s (%s: %s)", what, s_rm_op, strerror(s_rm_err));
    s_save_msg_t = M.time;
    logf_("saves: %s: %s %s: errno %d (%s)\n", what, s_rm_op, s_rm_path, s_rm_err, strerror(s_rm_err));
}
/* X twice. The stamp is copied first: saves_backup() lists the backups again, and s_bk[row] then names the next
 * newer one (row 0: the backup just made of the current saves). The live saves are moved aside, not deleted, and
 * put back if the copy fails; the restore needs the backup of the current saves and a non-empty source. */
static void saves_restore(int g, int row)
{
    char stamp[24], src[400], dst[300], old[320], mk[320];
    if (!saves_bk_path(g, row, src, sizeof src)) return;
    snprintf(stamp, sizeof stamp, "%s", s_bk[row]);
    struct stat st;
    if (stat(src, &st) || !S_ISDIR(st.st_mode) || save_count_slots(src, NULL) == 0) {
        snprintf(s_save_msg, sizeof s_save_msg, "%s", T("This backup is empty: nothing restored.", "Este backup está vazio: nada restaurado."));
        s_save_msg_t = M.time; logf_("saves %s: restore %s: empty or missing source, nothing done\n", kDir[g], stamp); return;
    }
    save_dir(g, dst, sizeof dst); snprintf(old, sizeof old, "%s.before_restore", dst);
    if (save_count_slots(dst, NULL) > 0 && saves_backup(g)) {   /* (no current saves: nothing to back up) */
        snprintf(s_save_msg, sizeof s_save_msg, "%s", T("Couldn't back up the current saves first: nothing restored.", "Não foi possível guardar os saves atuais antes: nada restaurado.")); s_save_msg_t = M.time; return;
    }
    s_rm_err = 0; inst_rmtree(old);   /* (one left by an earlier restore) */
    const int moved = !stat(dst, &st);
    if (moved && rename(dst, old)) {
        snprintf(s_save_msg, sizeof s_save_msg, "%s (%s)", T("Restore failed: nothing changed.", "Falha ao restaurar: nada mudou."), strerror(errno));
        s_save_msg_t = M.time; logf_("saves %s: restore %s: rename %s: %s\n", kDir[g], stamp, dst, strerror(errno)); return;
    }
    snprintf(mk, sizeof mk, "%s/", dst); inst_mkdirs(mk);
    const int r = save_copy_tree(src, dst);
    if (r) {   /* the current saves back as they were */
        s_rm_err = 0; const int clean = inst_rmtree(dst);
        const int back = moved ? rename(old, dst) : clean;
        logf_("saves %s: restore %s FAILED, current saves %s\n", kDir[g], stamp, !back ? "put back" : moved ? "left in savedata.before_restore" : "(none) - partial copy left");
        if (!back) snprintf(s_save_msg, sizeof s_save_msg, "%s", T("Restore failed: your current saves were kept.", "Falha ao restaurar: os saves atuais foram mantidos."));
        else snprintf(s_save_msg, sizeof s_save_msg, "%s", T("Restore failed and the saves folder is incomplete: restore your newest backup.",
                                                              "Falha ao restaurar e a pasta de saves ficou incompleta: restaure o backup mais recente."));
    } else {
        s_rm_err = 0;
        if (inst_rmtree(old)) logf_("saves %s: restore: old saves left in %s (%s %s: %s)\n", kDir[g], old, s_rm_op, s_rm_path, strerror(s_rm_err));
        snprintf(s_save_msg, sizeof s_save_msg, T("Restored the backup of %s.", "Backup de %s restaurado."), stamp);
        logf_("saves %s: restore %s -> ok\n", kDir[g], stamp);
    }
    s_save_msg_t = M.time;
}
/* TRIANGLE twice. If the console refuses the delete, the folder is renamed to a hidden name (saves_list skips
 * names starting with '.'), so it leaves the list and nothing is lost; the reason is shown and logged. */
static void saves_delete(int g, int row)
{
    char d[300], stamp[24];
    if (!saves_bk_path(g, row, d, sizeof d)) return;
    snprintf(stamp, sizeof stamp, "%s", s_bk[row]);
    s_rm_err = 0;
    if (inst_rmtree(d) == 0) {
        logf_("saves %s: deleted backup %s\n", kDir[g], stamp);
        snprintf(s_save_msg, sizeof s_save_msg, "%s", T("Backup deleted.", "Backup apagado."));
        s_save_msg_t = M.time;
    } else {
        saves_msg_rm(T("Couldn't delete the backup", "Não foi possível apagar o backup"));
        char h[320]; snprintf(h, sizeof h, APP "/saves_backup/%s/.deleted_%s", kDir[g], stamp);
        if (!rename(d, h)) logf_("saves %s: backup %s hidden as %s\n", kDir[g], stamp, h);
        else logf_("saves %s: rename %s: %s\n", kDir[g], d, strerror(errno));
    }
    saves_list(g);
}
static void draw_saves(void)
{
    const float left = 140 + PDX();
    float y = 200;
    if (s_bk_game != M.save_game) saves_list(M.save_game);
    for (int r = 0; r < NGAMES; r++) {
        const int sel = r == M.save_game, fs = 40;
        if (sel) rect((int)(left - 30), (int)(y + 8), 10, fs - 8, C_ACCENT, PA(255));
        textt(&F_item, fs, left, y, sel ? C_WHITE : C_GREY, PA(255), kName[r]);
        char d[300], st[96]; time_t nw = 0; save_dir(r, d, sizeof d);
        const int n = save_count_slots(d, &nw);
        if (n) { char t[40] = ""; const struct tm* lt = localtime(&nw); if (lt) when_text(t, sizeof t, lt, 0); snprintf(st, sizeof st, T("%d SAVE(S)  %s", "%d SAVE(S)  %s"), n, t); }
        else snprintf(st, sizeof st, "%s", T("NO SAVES", "SEM SAVES"));
        textt(&F_body, 28, left + 560, y + 8, n ? C_WHITE : C_GREY, PA(255), st);
        y += fs + 6 + 18;
    }
    const float px = 1180 + PDX(), pw = W - 140 - px;
    rect((int)(px - 40), 200, 1, 560, 0xFFFFFF, PA(40));
    textt(&F_item, 32, px, 200, C_WHITE, PA(255), T("BACKUPS", "BACKUPS"));
    float by = 250;
    if (!s_nbk) text_wrap(&F_body, 26, px, by, (int)pw, C_GREY, PA(255), T("No backups yet. SQUARE backs up this game's saves now.", "Nenhum backup ainda. QUADRADO faz o backup dos saves deste jogo agora."), 1);
    if (M.save_row >= s_nbk) M.save_row = s_nbk ? s_nbk - 1 : 0;
    const int first = M.save_row >= 12 ? M.save_row - 11 : 0;   /* (the chosen row always on screen: X/TRIANGLE act on it) */
    for (int i = first; i < s_nbk && i < first + 12; i++) {
        const int sel = i == M.save_row;
        char lab[40]; const char* b = s_bk[i];
        snprintf(lab, sizeof lab, "%.4s-%.2s-%.2s  %.2s:%.2s:%.2s", b, b + 4, b + 6, b + 9, b + 11, b + 13);
        if (sel) rect((int)(px - 22), (int)(by + 6), 8, 22, C_ACCENT, PA(255));
        textt(&F_body, 28, px, by, sel ? C_WHITE : C_GREY, PA(255), lab);
        by += 40;
    }
    char tail[300] = "";
    if (confirming() && M.confirm_game == 100 + M.save_game) snprintf(tail, sizeof tail, "%s", T("PRESS X AGAIN TO RESTORE (your current saves are backed up first)", "APERTE X DE NOVO PARA RESTAURAR (os saves atuais são guardados antes)"));
    else if (confirming() && M.confirm_game == 200 + M.save_game) snprintf(tail, sizeof tail, "%s", T("PRESS TRIANGLE AGAIN TO DELETE THIS BACKUP", "APERTE TRIÂNGULO DE NOVO PARA APAGAR ESTE BACKUP"));
    else if (M.time - s_save_msg_t < 4.0) snprintf(tail, sizeof tail, "%s", s_save_msg);
    if (tail[0]) text_wrap(&F_body, 26, px, 720, (int)pw, C_ACCENT, PA(255), tail, 1);
}

/* TROPHIES (2026-11-09): each game's trophy list from its own TROPHY.TRP (PS3_GAME/TROPDIR/<commId>/, TROP.SFM: XML)
 * and the unlocks the runtime keeps in <game>/game/gamedata/trophies/<commId>.json ({ "id": N, "timestamp": unix }). */
typedef struct { int id, hidden; char type; char name[72], detail[180]; long long when; } trophy_t;
static trophy_t s_tr[NGAMES][80]; static int s_ntr[NGAMES] = { -1, -1, -1 }; static double s_tr_t[NGAMES] = { -100, -100, -100 };
static void tr_xml_text(const char* a, const char* tag, char* out, size_t n)
{
    char o[24], c[24]; snprintf(o, sizeof o, "<%s>", tag); snprintf(c, sizeof c, "</%s>", tag);
    const char* p = strstr(a, o); out[0] = 0; if (!p) return; p += strlen(o);
    const char* q = strstr(p, c); if (!q) return;
    size_t k = 0;
    for (; p < q && k + 1 < n; p++) {   /* (the few XML entities trophy text uses) */
        if (*p == '&') { if (!strncmp(p, "&amp;", 5)) { out[k++] = '&'; p += 4; continue; } if (!strncmp(p, "&apos;", 6)) { out[k++] = '\''; p += 5; continue; }
                         if (!strncmp(p, "&quot;", 6)) { out[k++] = '"'; p += 5; continue; } if (!strncmp(p, "&lt;", 4)) { out[k++] = '<'; p += 3; continue; }
                         if (!strncmp(p, "&gt;", 4)) { out[k++] = '>'; p += 3; continue; } }
        out[k++] = *p;
    }
    out[k] = 0;
}
static void tr_load(int g)
{
    s_ntr[g] = 0; s_tr_t[g] = M.time;
    char dir[300], comm[64] = ""; snprintf(dir, sizeof dir, APP "/%s/game/PS3_GAME/TROPDIR", kDir[g]);
    DIR* d = opendir(dir); if (!d) return;
    struct dirent* de; while ((de = readdir(d))) if (de->d_name[0] != '.') { snprintf(comm, sizeof comm, "%s", de->d_name); break; }
    closedir(d); if (!comm[0]) return;
    char trp[400]; snprintf(trp, sizeof trp, "%s/%s/TROPHY.TRP", dir, comm);
    FILE* f = fopen(trp, "rb"); if (!f) return;
    unsigned char h[0x40]; char* xml = NULL;
    if (fread(h, 1, sizeof h, f) == sizeof h && h[0] == 0xDC && h[1] == 0xA2 && h[2] == 0x4D) {
        const unsigned cnt = (unsigned)h[16] << 24 | h[17] << 16 | h[18] << 8 | h[19], esz = (unsigned)h[20] << 24 | h[21] << 16 | h[22] << 8 | h[23];
        for (unsigned i = 0; i < cnt && i < 512 && esz >= 48; i++) {
            unsigned char e[48];
            if (fseek(f, 0x40 + (long)i * esz, SEEK_SET) || fread(e, 1, 48, f) != 48) break;
            if (strcmp((const char*)e, "TROP.SFM")) continue;
            unsigned long long off = 0, sz = 0; for (int k = 0; k < 8; k++) { off = off << 8 | e[32 + k]; sz = sz << 8 | e[40 + k]; }
            if (sz > (4u << 20) || fseek(f, (long)off, SEEK_SET)) break;
            xml = (char*)malloc((size_t)sz + 1);
            if (xml && fread(xml, 1, (size_t)sz, f) == sz) xml[sz] = 0; else { free(xml); xml = NULL; }
            break;
        }
    }
    fclose(f); if (!xml) return;
    for (const char* p = strstr(xml, "<trophy "); p && s_ntr[g] < 80; p = strstr(p + 1, "<trophy ")) {
        const char* end = strstr(p, "</trophy>"); if (!end) break;
        trophy_t* t = &s_tr[g][s_ntr[g]]; memset(t, 0, sizeof *t);
        const char* a = strstr(p, "id=\""); t->id = a && a < end ? atoi(a + 4) : s_ntr[g];
        a = strstr(p, "hidden=\""); t->hidden = a && a < end && !strncmp(a + 8, "yes", 3);
        a = strstr(p, "ttype=\""); t->type = a && a < end ? a[7] : 'B';
        char one[1200]; size_t len = (size_t)(end - p) < sizeof one - 1 ? (size_t)(end - p) : sizeof one - 1; memcpy(one, p, len); one[len] = 0;
        tr_xml_text(one, "name", t->name, sizeof t->name); tr_xml_text(one, "detail", t->detail, sizeof t->detail);
        s_ntr[g]++;
    }
    free(xml);
    char js[400]; snprintf(js, sizeof js, APP "/%s/game/gamedata/trophies/%s.json", kDir[g], comm);
    f = fopen(js, "r");
    if (!f) {   /* 2026-11-12: TROPDIR's folder is "<commId>_00", the runtime's file is "<commId>.json" (the list always read 0%) */
        char c2[64]; snprintf(c2, sizeof c2, "%s", comm); char* u = strrchr(c2, '_'); if (u) *u = 0;
        snprintf(js, sizeof js, APP "/%s/game/gamedata/trophies/%s.json", kDir[g], c2); f = fopen(js, "r");
    }
    if (f) {
        char l[256];
        while (fgets(l, sizeof l, f)) {
            const char* a = strstr(l, "\"id\":"); const char* b = strstr(l, "\"timestamp\":");
            if (!a || !b) continue;
            const int id = atoi(a + 5); const long long ts = atoll(b + 12);
            for (int i = 0; i < s_ntr[g]; i++) if (s_tr[g][i].id == id) s_tr[g][i].when = ts ? ts : 1;
        }
        fclose(f);
    }
}
static void tr_counts(int g, int* got, int* all)
{
    if (s_ntr[g] < 0 || M.time - s_tr_t[g] > 5.0) tr_load(g);   /* (re-read now and then: a game may have run) */
    *got = 0; *all = s_ntr[g];
    for (int i = 0; i < s_ntr[g]; i++) if (s_tr[g][i].when) (*got)++;
}
static uint32_t tr_col(char t) { return t == 'P' ? 0xB8D4F0 : t == 'G' ? 0xF0C040 : t == 'S' ? 0xC8C8D0 : 0xC88A50; }
static void draw_trophies(void)
{
    const float left = 140 + PDX();
    float y = 200;
    for (int r = 0; r < NGAMES; r++) {
        const int sel = r == M.tr_game, fs = 40; int got, all; tr_counts(r, &got, &all);
        if (sel) rect((int)(left - 30), (int)(y + 8), 10, fs - 8, C_ACCENT, PA(255));
        textt(&F_item, fs, left, y, sel ? C_WHITE : C_GREY, PA(255), kName[r]);
        char st[64];
        if (all > 0) snprintf(st, sizeof st, T("%d / %d   %d%%", "%d / %d   %d%%"), got, all, got * 100 / all);
        else snprintf(st, sizeof st, "%s", T("NOT INSTALLED", "NÃO INSTALADO"));
        textt(&F_body, 28, left + 560, y + 8, got ? C_WHITE : C_GREY, PA(255), st);
        y += fs + 6 + 18;
    }
#ifdef LAUNCHER_HOST
    { static int once; if (!once && getenv("LHOST_TR")) { once = 1; M.tr_game = atoi(getenv("LHOST_TR")); } }
#endif
    const int g = M.tr_game; int got, all; tr_counts(g, &got, &all);
    const float px = 1180 + PDX(), pw = W - 140 - px;
    rect((int)(px - 40), 200, 1, 560, 0xFFFFFF, PA(40));
    if (all <= 0) return;
    int n_by[4] = { 0 }, g_by[4] = { 0 }; const char tt[4] = { 'P', 'G', 'S', 'B' };
    for (int i = 0; i < all; i++) for (int k = 0; k < 4; k++) if (s_tr[g][i].type == tt[k]) { n_by[k]++; if (s_tr[g][i].when) g_by[k]++; }
    char head[120]; snprintf(head, sizeof head, T("PLATINUM %d/%d   GOLD %d/%d   SILVER %d/%d   BRONZE %d/%d", "PLATINA %d/%d   OURO %d/%d   PRATA %d/%d   BRONZE %d/%d"),
                             g_by[0], n_by[0], g_by[1], n_by[1], g_by[2], n_by[2], g_by[3], n_by[3]);
    textt(&F_body, 24, px, 200, C_TEXT, PA(255), head);
    /* earned first (newest first), then the rest in the game's order; hidden ones unearned show as ??? */
    int ord[80], no = 0;
    for (int i = 0; i < all; i++) if (s_tr[g][i].when) ord[no++] = i;
    for (int i = 0; i < no; i++) for (int j = i + 1; j < no; j++) if (s_tr[g][ord[j]].when > s_tr[g][ord[i]].when) { int t = ord[i]; ord[i] = ord[j]; ord[j] = t; }
    for (int i = 0; i < all; i++) if (!s_tr[g][i].when) ord[no++] = i;
    if (M.tr_scroll > all - 6) M.tr_scroll = all - 6 > 0 ? all - 6 : 0;
    float ty = 250;
    clip(0, 240, W, 780);
    for (int k = M.tr_scroll; k < no && ty < 770; k++) {
        const trophy_t* t = &s_tr[g][ord[k]];
        const int earned = t->when != 0;
        rect((int)px, (int)(ty + 6), 14, 14, tr_col(t->type), PA(earned ? 255 : 90));
        textt(&F_body, 26, px + 26, ty, earned ? C_WHITE : C_GREY, PA(255), t->hidden && !earned ? T("Hidden trophy", "Troféu oculto") : t->name);
        char sub[220];
        if (earned && t->when > 1) { time_t w = (time_t)t->when; char d[32]; strftime(d, sizeof d, "%Y-%m-%d", localtime(&w)); snprintf(sub, sizeof sub, "%s  -  %s", d, t->detail); }
        else snprintf(sub, sizeof sub, "%s", t->hidden && !earned ? "???" : t->detail);
        ty += 32 + text_wrap(&F_body, 22, px + 26, ty + 32, (int)pw - 26, C_GREY, PA(255), sub, 1) + 14;
    }
    clip(0, 0, W, H);
}

typedef struct { const char* section; const char* label; char value[48]; const char* help; int slider; } line_t;   /* (48: "AUTO (ESPAÑOL (LATINOAMÉRICA))" is 32 bytes) */

static void settings_lines(line_t* l)
{
    const char* const sec[NROWS] = { T("GRAPHICS", "GRÁFICOS"), T("GRAPHICS", "GRÁFICOS"), T("GRAPHICS", "GRÁFICOS"), T("GRAPHICS", "GRÁFICOS"), T("GRAPHICS", "GRÁFICOS"), T("GRAPHICS", "GRÁFICOS"), T("GRAPHICS", "GRÁFICOS"), T("GRAPHICS", "GRÁFICOS"), T("GAME", "JOGO"), T("GAME", "JOGO"), T("GAME", "JOGO"), T("GAME", "JOGO"), T("MENU", "MENU"), T("MENU", "MENU"), T("TROUBLESHOOTING", "SOLUÇÃO DE PROBLEMAS") };
    const char* const lab[NROWS] = { T("GPU LIGHTING", "ILUMINAÇÃO NA GPU"), T("UPSCALING", "AMPLIAÇÃO DA IMAGEM"), T("SHARPNESS", "NITIDEZ"), T("ANTI-ALIASING", "ANTISSERRILHADO"), T("TEXTURE FILTERING", "FILTRAGEM DE TEXTURAS"), T("LOOK", "VISUAL"), T("FRAME GENERATION", "GERAÇÃO DE QUADROS"), T("FPS COUNTER", "CONTADOR DE FPS"), T("LANGUAGE", "IDIOMA"), T("SKIP INTRO MOVIES", "PULAR VÍDEOS DE ABERTURA"), T("SKIP CUTSCENE MOVIES", "PULAR VÍDEOS DA HISTÓRIA"),
                                            T("DLC COSTUMES", "TRAJES DLC"), T("MENU MUSIC", "MÚSICA DO MENU"), T("MENU EFFECTS", "EFEITOS DO MENU"), T("DIAGNOSTICS", "DIAGNÓSTICO") };
    const char* const help[NROWS] = {
        T("Lighting and ambient occlusion on the PS5's GPU (faster). OFF uses the original SPU path.", "Iluminação e oclusão de ambiente na GPU do PS5 (mais rápido). DESLIGADO usa o caminho original das "
          "SPUs."),
        T("How the game's 720p picture is enlarged to your TV. FSR 1 (AMD FidelityFX Super Resolution) keeps edges and detail sharp; BILINEAR is the plain, softer stretch.",
          "Como a imagem de 720p do jogo é ampliada para a sua TV. FSR 1 (AMD FidelityFX Super Resolution) mantém bordas e detalhes nítidos; BILINEAR é a ampliação simples, mais suave."),
        T("How much FSR 1 sharpens the enlarged picture. HIGH is the crispest; MEDIUM and LOW are softer and hide noise and shimmer. Needs FSR 1.",
          "Quanto o FSR 1 deixa a imagem ampliada nítida. ALTA é a mais nítida; MÉDIA e BAIXA são mais suaves e escondem ruído e cintilação. Precisa do FSR 1."),
        T("Smooths jagged edges before the picture is enlarged. FXAA is the lighter, softer filter; SMAA (1x) gives cleaner edges and keeps texture detail sharper. Needs FSR 1.", "Suaviza as bordas serrilhadas antes de a imagem ser ampliada. FXAA é o filtro mais leve e suave; SMAA (1x) deixa as bordas mais limpas e mantém os detalhes das texturas mais nítidos. Precisa do FSR 1."),
        T("Anisotropic filtering: roads, walls and floors seen at an angle stay sharp instead of going blurry. 16X is the sharpest; GAME DEFAULT is the PS3's filtering.",
          "Filtragem anisotrópica: ruas, paredes e pisos vistos de lado ficam nítidos em vez de borrados. 16X é a mais nítida; PADRÃO DO JOGO é a filtragem do PS3."),
        T("A finishing filter over the whole picture (needs FSR 1). REMASTER: deeper contrast, richer colour, crisper detail. COMIC, CEL, BORDERLANDS, INK NOIR, SOFT INK, TOON LIGHT, PAINTERLY, VINTAGE PRINT, SKETCH, HDR POP: art styles. In game, L3+R3 opens the quick menu to try them live.",
          "Um filtro final sobre a imagem (precisa do FSR 1). REMASTER: mais contraste, cores mais ricas e detalhes mais nítidos. COMIC, CEL, BORDERLANDS, INK NOIR, SOFT INK, TOON LIGHT, PAINTERLY, VINTAGE PRINT, SKETCH, HDR POP: estilos artísticos. No jogo, L3+R3 abre o menu rápido para testá-los ao vivo."),
        T("Adds a frame between each two the game draws, so motion looks about twice as smooth (paused during pre-rendered movies). With it on, the FPS counter's big number counts the frames on screen and \"game N\" beside it the game's own.",
          "Adiciona um quadro entre cada dois que o jogo desenha: o movimento fica cerca de duas vezes mais suave (pausada durante os vídeos pré-renderizados). Ligada, o número grande do contador de FPS conta os quadros na tela e \"game N\" ao lado, os do próprio jogo."),
        T("Shows the frame rate at the left edge of the screen while you play. SIMPLE is frames a second and the frame time. DETAILED adds the slowest frames, a graph of the last ones, the picture's size and how long the renderer takes.",
          "Mostra a taxa de quadros na borda esquerda da tela enquanto você joga. SIMPLES: quadros por segundo e o tempo de quadro. DETALHADO: também os quadros mais lentos, um gráfico dos últimos, o tamanho da imagem e o tempo do renderizador."),
        T("The game's language, where the game has it (otherwise English).", "O idioma do jogo, onde o jogo o tem (senão, inglês). PORTUGUÊS também deixa este menu em português."),
        T("Skips the logo and splash movies when a game starts.", "Pula os vídeos de logo e de abertura quando um jogo começa."),
        T("Skips every pre-rendered movie (comic-book and story videos). In-game TVs still play.", "Pula todos os vídeos pré-renderizados (os de história em quadrinhos e da história). As TVs dentro "
          "do jogo continuam passando."),
        T("Unlocks the DLC and pre-order extras: Kessler, inFAMOUS 1 Cole, Kevin Butler, Reaper and Zombie skins, Skin Pack 1, the amp and bonus skins, the gold amp and the four pre-order powers. Pick them in the game's costume menu. inFAMOUS 1 has none.",
          "Desbloqueia os extras de DLC e pré-venda: os trajes Kessler, Cole do inFAMOUS 1, Kevin Butler, Reaper e Zumbi, o Pacote de Trajes 1, os trajes de amp e bônus, o amp dourado e os quatro poderes de pré-venda. Escolha-os no menu de trajes do jogo. O inFAMOUS 1 não tem."),
        T("Launcher music volume (the same for every game).", "O volume da música do launcher (o mesmo para todos os jogos)."),
        T("Lightning, sparks and glow that move on the launcher's screens. OFF keeps the menu still (the same for every game).",
          "Raios, faíscas e brilhos que se movem nas telas do launcher. DESLIGADO deixa o menu parado (o mesmo para todos os jogos)."),
        T("Frame timeline, screenshots and logs for troubleshooting (logs/ in each game's folder).", "Linha do tempo dos quadros, capturas de tela e logs para solução de problemas (logs/ na pasta de "
          "cada jogo)."),
    };
    const gset_t* g = &G[M.set_game];
    for (int r = 0; r < NROWS; r++) {
        l[r].section = sec[r]; l[r].label = lab[r]; l[r].help = help[r]; l[r].slider = r == R_MUSIC;
        switch (r) {
        case R_GPU: snprintf(l[r].value, sizeof l[r].value, "%s", M.set_game == 0 ? T("NOT IN THIS GAME", "NÃO HÁ NESTE JOGO") : g->gpu_effects ? T("ON", "LIGADO") : T("OFF", "DESLIGADO")); break;   /* (inFAMOUS 1: gpu_light.c / gpu_ssao.c are stubs, ps5_app.c sets no hooks) */
        case R_UPS: snprintf(l[r].value, sizeof l[r].value, "%s", g->no_fsr ? "BILINEAR" : "FSR 1"); break;
        case R_AA: snprintf(l[r].value, sizeof l[r].value, "%s", g->no_aa ? T("OFF", "DESLIGADO") : g->smaa ? "SMAA" : "FXAA"); break;
        case R_ANISO: { static const char* const n[4] = { "16X", "8X", "4X", "2X" };
                        snprintf(l[r].value, sizeof l[r].value, "%s", g->no_aniso ? T("GAME DEFAULT", "PADRÃO DO JOGO") : n[g->aniso_dn & 3]); break; }
        case R_SHARP: snprintf(l[r].value, sizeof l[r].value, "%s", g->sharp == 2 ? T("LOW", "BAIXA") : g->sharp == 1 ? T("MEDIUM", "MÉDIA") : T("HIGH", "ALTA")); break;
        case R_LOOK: { static const char* const n[12] = { "ORIGINAL", "REMASTER", "COMIC", "CEL", "BORDERLANDS", "INK NOIR", "SOFT INK",
                                                         "TOON LIGHT", "PAINTERLY", "VINTAGE PRINT", "SKETCH", "HDR POP" };
                       snprintf(l[r].value, sizeof l[r].value, "%s", n[g->look >= 0 && g->look < 12 ? g->look : 0]); break; }
        case R_FG: snprintf(l[r].value, sizeof l[r].value, "%s", g->framegen ? T("ON", "LIGADO") : T("OFF", "DESLIGADO")); break;
        case R_FPS: snprintf(l[r].value, sizeof l[r].value, "%s", g->fps_counter == 2 ? T("DETAILED", "DETALHADO") : g->fps_counter == 1 ? T("SIMPLE", "SIMPLES") : T("OFF", "DESLIGADO")); break;
        case R_LANG: {
            const char* name = (s_pt ? kLangNamePt : kLangName)[lang_of(g)];
            if (g->lang == LANG_AUTO) snprintf(l[r].value, sizeof l[r].value, "AUTO (%s)", name);
            else snprintf(l[r].value, sizeof l[r].value, "%s", name);
            break; }
        case R_SKIP_INTRO: snprintf(l[r].value, sizeof l[r].value, "%s", g->skip_intro ? T("ON", "LIGADO") : T("OFF", "DESLIGADO")); break;
        case R_SKIP_MOVIES: snprintf(l[r].value, sizeof l[r].value, "%s", g->skip_movies ? T("ON", "LIGADO") : T("OFF", "DESLIGADO")); break;
        case R_DLC: snprintf(l[r].value, sizeof l[r].value, "%s", M.set_game == 0 ? T("NOT IN THIS GAME", "NÃO HÁ NESTE JOGO") : g->no_dlc ? T("OFF", "DESLIGADO") : T("ON", "LIGADO")); break;
        case R_MUSIC: snprintf(l[r].value, sizeof l[r].value, "%d%%", S.music); break;
        case R_FX: snprintf(l[r].value, sizeof l[r].value, "%s", S.fx ? T("ON", "LIGADO") : T("OFF", "DESLIGADO")); break;
        default: snprintf(l[r].value, sizeof l[r].value, "%s", g->diagnostics ? T("ON", "LIGADO") : T("OFF", "DESLIGADO")); break;
        }
    }
}

/* SQUARE on SETTINGS: pressed once (3 s to press again), or the settings just put back. */
static int confirming(void) { return M.time - M.confirm_t < 3.0f; }

/* SETTINGS' left side: the games, as on HOME (the chosen one large with the accent's bar, pulsing
 * while the list has the pad), each with its own settings at the right. */
static void draw_settings_games(float left, float top)
{
    spaced(&F_body, 19, left, top, C_ACCENT, PA(255), T("GAMES", "JOGOS"), 3);
    float y = top + 46;
    for (int g = 0; g < NGAMES; g++) {
        const int sel = g == M.set_game;
        const img_t* logo = sel ? &s_logo_set[g] : &s_logo_set_small[g];
        const int h = sel ? kLogoSetH[g] : kLogoSetSmallH[g];
        if (sel) {
            const float pulse = M.in_list ? 1.0f : 0.7f + 0.3f * sinf(M.time * 5.0f);
            rect((int)(left - 38), (int)(y + h * 0.12f), 14, (int)(h * 0.76f), C_ACCENT, PA((int)(255 * pulse)));
        }
        if (logo->px) img_draw(logo, (int)left, (int)y, PA(sel ? 255 : 170));
        else textt(&F_item, h * 2 / 3, left, y, sel ? C_WHITE : C_GREY, PA(255), kName[g]);
        y += h + 26;
    }
}

static void draw_settings(void)
{
    const float games_left = 140 + PDX(), left = 580 + PDX();
    line_t l[NROWS];
    settings_lines(l);
    const float fs = 36, top = 190, bottom = H - 120;
    draw_settings_games(games_left, top);
    rect((int)(left - 60), 190, 1, 570, 0xFFFFFF, PA(40));
    /* where each row and section heading goes (scrolled so the focused row stays in view) */
    float row_y[NROWS], head_y[NROWS], y = 0;
    for (int r = 0; r < NROWS; r++) {
        head_y[r] = -1;
        if (!r || strcmp(l[r - 1].section, l[r].section)) {
            if (r) y += 14;
            head_y[r] = y;
            y += 36;
        }
        row_y[r] = y;
        y += fs + 16;
    }
    const float view = bottom - top, most = y - view > 0 ? y - view : 0;
    float want = row_y[M.row] - view * 0.45f;
    want = want < 0 ? 0 : want > most ? most : want;
    M.scroll += (want - M.scroll) * 0.25f;
    const float px = 1360 + PDX(), pw = W - 140 - px;
    clip(0, (int)(top - 4), (int)(px - 40), (int)bottom);
    for (int r = 0; r < NROWS; r++) {
        if (head_y[r] >= 0) spaced(&F_body, 19, left, top + head_y[r] - M.scroll, C_ACCENT, PA(255), l[r].section, 3);
        y = top + row_y[r] - M.scroll;
        const int sel = M.in_list && r == M.row;
        const uint32_t col = sel ? C_WHITE : C_GREY;
        if (sel) rect((int)(left - 30), (int)(y + 8), 10, (int)fs - 8, C_ACCENT, PA(255));
        textt(&F_item, (int)fs, left, y, col, PA(255), l[r].label);
        char v[64];
        snprintf(v, sizeof v, l[r].slider ? "%s" : "<  %s  >", l[r].value);
        {   /* (a value wider than its column, up to the help's divider, drawn smaller, as the credits' names) */
            const int room = (int)(px - 40 - (left + 380)), vw = text_w(&F_item, (int)fs, v);
            const int vs = !l[r].slider && vw > room ? (int)(fs * room / vw) : (int)fs;
            textt(&F_item, vs, left + 380, y + (fs - vs) * 0.5f, sel ? C_ACCENT : col, PA(255), v); }
        if (l[r].slider) {
            const float x0 = left + 480, w = 220, yy = y + fs * 0.6f;
            rect((int)x0, (int)(yy - 3), (int)w, 6, C_DIM, PA(255));
            rect((int)x0, (int)(yy - 3), (int)(w * S.music / 100.0f), 6, sel ? C_ACCENT : C_GREY, PA(255));
        }
    }
    unclip();
    /* the focused row's help, at the right (in the game list: what the list is for) */
    rect((int)(px - 40), 190, 1, 570, 0xFFFFFF, PA(40));
    char about[256];
    snprintf(about, sizeof about, T("%s's own settings: each game keeps its own. X or RIGHT to change them. SQUARE puts back "
             "the recommended settings, the ones it was tested with.", "%s: os ajustes deste jogo, cada jogo tem os seus. X ou DIREITA para mudá-los. QUADRADO volta aos "
                                    "ajustes recomendados, os que foram testados."), kName[M.set_game]);
    textt(&F_item, 34, px, 190, C_WHITE, PA(255), M.in_list ? l[M.row].label : kName[M.set_game]);
    text_wrap(&F_body, 26, px, 244, (int)pw, C_TEXT, PA(255), M.in_list ? l[M.row].help : about, 1);
    if (confirming())
        text_wrap(&F_body, 22, px, 676, (int)pw, C_ACCENT, PA(255), T("PRESS SQUARE AGAIN TO PUT BACK THE RECOMMENDED SETTINGS", "APERTE QUADRADO DE NOVO PARA VOLTAR ÀS CONFIGURAÇÕES RECOMENDADAS"), 1);
    else if (M.time - M.reset_t < 3.0f)
        text_wrap(&F_body, 22, px, 700, (int)pw, C_ACCENT, PA(255), T("RECOMMENDED SETTINGS PUT BACK", "CONFIGURAÇÕES RECOMENDADAS RESTAURADAS"), 1);
    else
        textt(&F_body, 22, px, 700, C_DIM, PA(255), T("Saved as you change it.", "Salvo assim que você muda."));
}

static void draw_credits(void)
{
    const float x = 140 + PDX(), w = 860;
    float y = 180;
    clip(0, 0, W, H - 120);   /* (not into the clock) */
#define ENTRY(name, body) do { \
        const int ns = text_w(&F_item, 26, name) > w ? (int)(26 * w / text_w(&F_item, 26, name)) : 26; \
        textt(&F_item, ns, x, y, C_WHITE, PA(255), name); y += 34; \
        y += text_wrap(&F_body, 20, x, y, (int)w, C_GREY, PA(255), body, 1) + 20; } while (0)
    /* the project */
    textt(&F_title, 60, x, y - 6, C_WHITE, PA(255), "inFAMOUS");
    spaced(&F_item, 30, x + text_w(&F_title, 60, "inFAMOUS") + 22, y + 24, C_ACCENT, PA(255), "RECHARGED", 6);
    y += 84;
    ENTRY(T("BY CHAOSTHEORY1075", "POR CHAOSTHEORY1075"), T("inFAMOUS: ReCharged - inFAMOUS, inFAMOUS 2 and Festival of Blood on the PS5.\n"
                                "Static recompilations of the PS3 games, built from your own copies.", "inFAMOUS: ReCharged - inFAMOUS, inFAMOUS 2 e Festival of Blood no PS5.\nRecompilações estáticas dos jogos de PS3, feitas a partir das suas próprias cópias."));
    textt(&F_body, 20, x, y, C_ACCENT, PA(255), T("ALL THE CREDIT GOES TO", "TODO O CRÉDITO VAI PARA"));
    y += 40;
    ENTRY("INFAMOUS2-RECOMP  -  ERIKOMIS", T("inFAMOUS 2 and Festival of Blood: erikomis' infamous2-recomp.", "inFAMOUS 2 e Festival of Blood: o infamous2-recomp do erikomis."));
    ENTRY("INFAMOUSREBORN  -  WHOMPAY", T("inFAMOUS: whompay's inFAMOUSreborn.", "inFAMOUS: o inFAMOUSreborn do whompay."));
    ENTRY("PS3RECOMP  -  SP00NZNET", T("PS3 runtime: sp00nznet's ps3recomp.  Graphics: Mesa RADV.", "Runtime de PS3: o ps3recomp do sp00nznet.  Gráficos: Mesa RADV."));
#undef ENTRY

    const float px = 1060 + PDX(), pw = W - 140 - px;
    float py = 180;
    /* the shout-out, on a panel of its own */
    {
        const char* thanks = T("For Empire City, New Marais and Pyre Night: Cole, Zeke, Trish, Kuo and Nix, the Ray "
                             "Sphere and the Beast, and every choice between hero and infamous.", "Por Empire City, New Marais e a Noite da Fogueira: Cole, Zeke, Trish, Kuo e Nix, a Ray Sphere e a "
                               "Besta, e cada escolha entre herói e infame.");
        const int th = text_wrap(&F_body, 22, 0, 0, (int)(pw - 48), 0, 0, thanks, 0);
        rrect(px - 24, py - 16, px + pw, py + 96 + th, 6, 0, 0x080808, PA(170));
        rect((int)(px - 24), (int)(py - 16), 6, 112 + th, C_ACCENT, PA(255));
        textt(&F_body, 20, px, py, C_ACCENT, PA(255), T("SPECIAL THANKS", "AGRADECIMENTOS ESPECIAIS"));
        textt(&F_item, 40, px, py + 30, C_WHITE, PA(255), "SUCKER PUNCH PRODUCTIONS");
        text_wrap(&F_body, 22, px, py + 84, (int)(pw - 48), C_GREY, PA(255), thanks, 1);
        py += 96 + th + 46;
    }
    textt(&F_body, 20, px, py, C_ACCENT, PA(255), T("PLEASE NOTE", "OBSERVAÇÃO"));
    py += 36;
    const char* note = T("inFAMOUS is a trademark of Sony Interactive Entertainment. Developed by Sucker Punch "
                       "Productions.\nNot affiliated with or endorsed by Sony or Sucker Punch.", "inFAMOUS é uma marca registrada da Sony Interactive Entertainment. Desenvolvido pela Sucker Punch "
                         "Productions.\nSem ligação com nem aval da Sony ou da Sucker Punch.");
    py += text_wrap(&F_body, 20, px, py, (int)pw, C_GREY, PA(255), note, 1) + 28;
    textt(&F_body, 20, px, py, C_ACCENT, PA(255), T("BUILT WITH", "FEITO COM"));
    py += 36;
    text_wrap(&F_body, 19, px, py, (int)pw, C_GREY, PA(255),
              T("PS5 Payload SDK  /  Mesa RADV (Vulkan)\nstb_image, stb_truetype, dr_mp3  /  Oswald and Inter (SIL Open "
              "Font License)\nBlackBearReloaded's PS5 AT9 Converter (the home screen music)", "PS5 Payload SDK  /  Mesa RADV (Vulkan)\nstb_image, stb_truetype, dr_mp3  /  Oswald e Inter (SIL Open "
                "Font License)\nPS5 AT9 Converter de BlackBearReloaded (a música da tela inicial)"), 1);
    unclip();
}

/* ---- MENU EFFECTS (launcher.ini menu_effects, SETTINGS > MENU EFFECTS): the menu made to move, drawn into the frame
 * like everything else (no new pictures, all from M.time and a hash): lightning that strikes the background's sky,
 * sparks and embers rising, arcs crawling on the chosen game's name, a burst along the tabs on a page change and a big
 * one when a game starts; bats for Festival of Blood. Blue-white for inFAMOUS, blue and red for inFAMOUS 2 (its two
 * sides), blood red for Festival of Blood. Light is added (fx_px), never drawn over the menu's text: the background's
 * part is drawn before the text, kept right of the menu's column (clip), and the front part stays on the logo / the
 * tab rule. Budget: a few hundred thousand pixels a frame at most (host_test measure: see the patch notes). ---- */
static struct { float page_t, game_t, launch_t, strike_k; } FX = { -100, -100, -100, 0 };
static void fx_event_game(void) { FX.game_t = M.time; }
static void fx_event_launch(void) { FX.launch_t = M.time; }

static uint32_t fx_h(uint32_t x)
{
    x ^= x >> 16; x *= 0x7FEB352Du; x ^= x >> 15; x *= 0x846CA68Bu; x ^= x >> 16;
    return x;
}
static float fx_r(uint32_t s) { return (float)(fx_h(s) >> 8) * (1.0f / 16777216.0f); }   /* 0..1 */
static float fx_cos(float a) { return sinf(a + 1.5707963f); }
/* s_fx_ramp > 0: light fades in over 180 pixels right of that x (no hard edge at the background's clip); s_fx_dark:
 * light drawn as a dark halo and a solid core (blended, not added) - Festival of Blood's pale picture, where added red
 * turns white. */
static float s_fx_ramp, s_fx_rampy;   /* (s_fx_rampy > 0: and fades out over the 120 pixels above that y) */
static int s_fx_dark;

/* Light added to a pixel (saturating). */
static inline uint32_t fx_sat(uint32_t a, uint32_t b)   /* a + b per byte (R, G, B), saturating; alpha FF */
{
    const uint32_t s = (a & 0x7F7F7Fu) + (b & 0x7F7F7Fu), x = (a ^ b) & 0x808080u;
    const uint32_t c = ((a & b) | (s & x)) & 0x808080u;
    return 0xFF000000u | (s ^ x) | ((c << 1) - (c >> 7));
}
static inline uint32_t fx_mix(uint32_t d, uint32_t s, uint32_t a)   /* d toward s by a/256 */
{
    const uint32_t rb = ((s & 0xFF00FFu) * a + (d & 0xFF00FFu) * (256 - a)) >> 8 & 0xFF00FFu;
    const uint32_t g = ((s & 0xFF00u) * a + (d & 0xFF00u) * (256 - a)) >> 8 & 0xFF00u;
    return 0xFF000000u | rb | g;
}
static inline void fx_px(uint32_t* d, int r, int g, int b)
{
    const uint32_t D = *d;
    const int R = (int)((D >> 16) & 255) + r, G = (int)((D >> 8) & 255) + g, B = (int)(D & 255) + b;
    *d = 0xFF000000u | (uint32_t)(R > 255 ? 255 : R) << 16 | (uint32_t)(G > 255 ? 255 : G) << 8 | (uint32_t)(B > 255 ? 255 : B);
}

/* A stroke of light from x0,y0 to x1,y1: a hot core (radius cw, colour core) in a glow (radius gr, colour glow), added
 * at strength k. cap0 0: no round cap at the start (the joint of a polyline is lit once, by the previous stroke). */
static void fx_seg(float x0, float y0, float x1, float y1, float cw, float gr, uint32_t glow, uint32_t core, float k, int cap0)
{
    if (k <= 0.004f) return;
    if (k > 1.5f) k = 1.5f;
    const float R = gr > cw + 1 ? gr : cw + 1, R2 = R * R, igr2 = 1.0f / (gr > 0.5f ? gr * gr : 0.25f);
    const float Rc = cw + 0.5f, Rc2 = Rc * Rc, iRc = 0.5f / Rc;
    int iy0 = (int)floorf((y0 < y1 ? y0 : y1) - R), iy1 = (int)ceilf((y0 > y1 ? y0 : y1) + R);
    if (iy0 < s_cy0) iy0 = s_cy0;
    if (iy1 > s_cy1) iy1 = s_cy1;
    const float dx = x1 - x0, dy = y1 - y0, l2 = dx * dx + dy * dy, il2 = l2 > 1e-4f ? 1.0f / l2 : 0;
    const float gR = ((glow >> 16) & 255) * k, gG = ((glow >> 8) & 255) * k, gB = (glow & 255) * k;
    const float cR = ((core >> 16) & 255) * k, cG = ((core >> 8) & 255) * k, cB = (core & 255) * k;
    for (int y = iy0; y < iy1; y++) {
        const float py = y + 0.5f, ry = py - y0;
        /* (this row's columns: the part of the stroke within R of the row, widened by R) */
        float ta = 0, tb = 1;
        if (dy > 1e-3f || dy < -1e-3f) {
            ta = (ry - R) / dy; tb = (ry + R) / dy;
            if (ta > tb) { const float s = ta; ta = tb; tb = s; }
            if (ta < 0) ta = 0;
            if (tb > 1) tb = 1;
            if (ta > tb) continue;
        } else if (ry > R || ry < -R) continue;
        const float xa = x0 + dx * ta, xb = x0 + dx * tb;
        int ix0 = (int)floorf((xa < xb ? xa : xb) - R), ix1 = (int)ceilf((xa > xb ? xa : xb) + R);
        if (ix0 < s_cx0) ix0 = s_cx0;
        if (ix1 > s_cx1) ix1 = s_cx1;
        uint32_t* row = s_fb + (size_t)y * W;
        float wy = 1;
        if (s_fx_rampy > 0) { wy = (s_fx_rampy - py) * (1.0f / 120); if (wy <= 0) continue; if (wy > 1) wy = 1; }
        const float rmp = s_fx_ramp, tmin = cap0 ? 0.0f : -1e9f;
        if (rmp > 0 && ix0 < (int)rmp) ix0 = (int)rmp;
        if (s_fx_dark) {
            for (int x = ix0; x < ix1; x++) {
                const float rx = x + 0.5f - x0;
                float t = (rx * dx + ry * dy) * il2;
                if (t < tmin) continue;
                t = t < 0 ? 0 : t > 1 ? 1 : t;
                const float ex = rx - dx * t, ey = ry - dy * t, d2 = ex * ex + ey * ey;
                if (d2 >= R2) continue;
                float w = wy;
                if (rmp > 0) { const float v = (x - rmp) * (1.0f / 180); w *= v < 1 ? v : 1; }
                float gg = 1.0f - d2 * igr2; gg = gg > 0 ? gg * gg : 0; gg *= gg;
                float cc = (Rc2 - d2) * iRc; cc = cc <= 0 ? 0 : cc >= 1 ? 1 : cc;
                const int ha = (int)(gg * k * 190 * w), ca = (int)(cc * k * 255 * w);
                if (ha > 0) row[x] = fx_mix(row[x], 0x1A0004, (uint32_t)(ha > 256 ? 256 : ha));
                if (ca > 0) row[x] = fx_mix(row[x], core, (uint32_t)(ca > 256 ? 256 : ca));
                if (d2 < cw * cw * 0.16f) fx_px(row + x, (int)(90 * k * w), (int)(60 * k * w), (int)(60 * k * w));
            }
            continue;
        }
        for (int x = ix0; x < ix1; x++) {   /* (branch-free: vectorises) */
            const float rx = x + 0.5f - x0;
            const float t0 = (rx * dx + ry * dy) * il2, on = t0 < tmin ? 0.0f : 1.0f, t = t0 < 0 ? 0 : t0 > 1 ? 1 : t0;
            const float ex = rx - dx * t, ey = ry - dy * t, d2 = ex * ex + ey * ey;
            float w = wy * on;
            if (rmp > 0) { const float v = (x - rmp) * (1.0f / 180); w *= v < 1 ? v : 1; }
            float gg = 1.0f - d2 * igr2; gg = gg > 0 ? gg * gg : 0; gg *= gg * w;   /* ((1 - d²/R²)^4: ~ (1 - d/R)², no root) */
            float cc = (Rc2 - d2) * iRc; cc = cc <= 0 ? 0 : cc >= 1 ? 1 : cc; cc *= w;
            int r = (int)(gR * gg + cR * cc), g = (int)(gG * gg + cG * cc), b = (int)(gB * gg + cB * cc);
            r = r > 255 ? 255 : r; g = g > 255 ? 255 : g; b = b > 255 ? 255 : b;
            row[x] = fx_sat(row[x], (uint32_t)r << 16 | (uint32_t)g << 8 | (uint32_t)b);
        }
    }
}

/* A round soft light (quadratic falloff) of radius r. */
static void fx_flash(float cx, float cy, float r, uint32_t rgb, float k)
{
    if (k <= 0.004f || r < 1) return;
    const float ir2 = 1.0f / (r * r);
    const uint32_t rb = rgb & 0xFF00FFu, gc = rgb & 0xFF00u;
    int iy0 = (int)floorf(cy - r), iy1 = (int)ceilf(cy + r);
    if (iy0 < s_cy0) iy0 = s_cy0;
    if (iy1 > s_cy1) iy1 = s_cy1;
    const float rmp = s_fx_ramp;
    for (int y = iy0; y < iy1; y++) {
        const float ddy = y + 0.5f - cy, qy = 1.0f - ddy * ddy * ir2;
        if (qy <= 0) continue;
        float wy = 1;
        if (s_fx_rampy > 0) { wy = (s_fx_rampy - y - 0.5f) * (1.0f / 120); if (wy <= 0) continue; if (wy > 1) wy = 1; }
        const float hw = r * sqrtf(qy), kq = k * wy * 256;
        int ix0 = (int)floorf(cx - hw), ix1 = (int)ceilf(cx + hw);
        if (rmp > 0 && ix0 < (int)rmp) ix0 = (int)rmp;
        if (ix0 < s_cx0) ix0 = s_cx0;
        if (ix1 > s_cx1) ix1 = s_cx1;
        uint32_t* row = s_fb + (size_t)y * W;
        if (s_fx_dark) {
            for (int x = ix0; x < ix1; x++) {
                const float ddx = x + 0.5f - cx;
                float q = qy - ddx * ddx * ir2; q = q > 0 ? q * q : 0;
                if (rmp > 0) { const float w = (x - rmp) * (1.0f / 180); q *= w < 1 ? w : 1; }
                const int a = (int)(q * kq);
                if (a > 0) row[x] = fx_mix(row[x], rgb, (uint32_t)(a > 256 ? 256 : a));
            }
            continue;
        }
        for (int x = ix0; x < ix1; x++) {   /* (branch-free: vectorises) */
            const float ddx = x + 0.5f - cx;
            float q = qy - ddx * ddx * ir2; q = q > 0 ? q * q : 0;
            if (rmp > 0) { const float w = (x - rmp) * (1.0f / 180); q *= w < 1 ? w : 1; }
            int qi = (int)(q * kq); qi = qi > 256 ? 256 : qi;
            row[x] = fx_sat(row[x], (((rb * (uint32_t)qi) >> 8) & 0xFF00FFu) | (((gc * (uint32_t)qi) >> 8) & 0xFF00u));
        }
    }
}

/* A bolt: x0,y0 to x1,y1 split 2^lv times, each middle pushed sideways (midpoint displacement) by up to rough/2 of its
 * span; the coarse shape from seed, the finest two levels from jit (re-rolled a few times a second: the crackle).
 * Into bx/by (2^lv + 1 points); returns 2^lv. */
enum { FX_LV = 6, FX_NP = (1 << FX_LV) + 1 };
static float s_fxa_x[FX_NP], s_fxa_y[FX_NP], s_fxb_x[FX_NP], s_fxb_y[FX_NP];
static int fx_bolt(float* bx, float* by, int lv, float x0, float y0, float x1, float y1, float rough, uint32_t seed, uint32_t jit)
{
    const int n = 1 << lv;
    bx[0] = x0; by[0] = y0; bx[n] = x1; by[n] = y1;
    for (int st = n; st > 1; st >>= 1) {
        const uint32_t sd = st <= 4 ? jit : seed;
        for (int i = st / 2; i < n; i += st) {
            const int a = i - st / 2, b = i + st / 2;
            const float dx = bx[b] - bx[a], dy = by[b] - by[a];
            const float o = (fx_r(sd * 977u + (uint32_t)i * 131u + (uint32_t)st * 7u) - 0.5f) * rough;
            bx[i] = (bx[a] + bx[b]) * 0.5f - dy * o;
            by[i] = (by[a] + by[b]) * 0.5f + dx * o;
        }
    }
    return n;
}
static void fx_bolt_draw(const float* bx, const float* by, int n, float cw, float gr, uint32_t glow, uint32_t core, float k, float taper)
{
    for (int i = 0; i < n; i++) {
        const float f = 1.0f - taper * (float)i / (float)n;
        fx_seg(bx[i], by[i], bx[i + 1], by[i + 1], cw * f, gr * (0.55f + 0.45f * f), glow, core, k * (0.4f + 0.6f * f), i == 0);
    }
}

/* Each game's light: glow and core (inFAMOUS 2: [1] blue, [3] red). */
static const uint32_t kFxGlow[4] = { 0x2E9BFF, 0x2E9BFF, 0xE01028, 0xFF3A16 };
static const uint32_t kFxCore[4] = { 0xE4F3FF, 0xE4F3FF, 0xFF2A3C, 0xFFE0C8 };

/* ---- the background (drawn after it, before the menu) ---- */

/* Sparks and embers rising on the picture's right side (fading out toward the menu's column, above the footer). */
static void fx_embers(int g, float t, float vis)
{
    static const uint32_t warm[3] = { 0xFF8A3A, 0xFF7A2A, 0xFF2A14 }, cold[3] = { 0x6CC4FF, 0x6CC4FF, 0xB0A8A8 };
    static const float cold_share[3] = { 0.65f, 0.3f, 0.2f };
    for (int i = 0; i < 44; i++) {
        const uint32_t si = (uint32_t)i * 2654435761u + (uint32_t)g * 0x51ED27u;
        const float L = 4.5f + 6.0f * fx_r(si);
        const float tt = t + fx_r(si + 1) * L, cyc = floorf(tt / L), u = tt / L - cyc;
        const uint32_t sc = si ^ (uint32_t)(int)cyc * 0x9E3779B9u;
        const float x0 = 1010 + fx_r(sc + 2) * 890, y0 = 930 - fx_r(sc + 3) * 240, rise = 240 + fx_r(sc + 4) * 420;
        const float sw = 0.7f + fx_r(sc + 5), drift = (fx_r(sc + 6) - 0.3f) * 170;
        const float x = x0 + 24 * sinf(t * sw + (float)i) + u * drift, y = y0 - u * rise;
        if (y < 150) continue;
        float b = sinf(u * 3.1415927f); b *= b;
        b *= (0.35f + 0.65f * fx_r(sc + 7)) * (0.7f + 0.3f * sinf(t * 9.0f + (float)i * 1.7f));
        const float xm = (x - 960) / 320;
        b *= xm < 0 ? 0.2f : xm > 1 ? 1 : 0.2f + 0.8f * xm;
        const int is_cold = fx_r(sc + 8) < cold_share[g];
        const uint32_t c = is_cold ? (g == 1 && (i & 1) ? 0x6CC4FF : cold[g]) : warm[g];
        const float vx = 24 * sw * fx_cos(t * sw + (float)i) + drift / L, vy = -rise / L;
        const float sz = 0.7f + 1.3f * fx_r(sc + 9);
        if (g == 2) fx_seg(x, y, x - vx * 0.06f, y - vy * 0.06f, sz * 0.8f, sz * 2.5f, c, is_cold ? 0x302C2C : 0xA00A14, b * vis, 1);
        else fx_seg(x, y, x - vx * 0.06f, y - vy * 0.06f, sz, sz * 4.5f + 2, c, is_cold ? 0xEAF6FF : 0xFFE6B0, b * vis * (is_cold ? 1.0f : 0.85f), 1);
    }
}

/* Lightning in the picture's sky: about every 3.4 s a strike (two or three strokes, a flash lighting the clouds), with
 * branches; inFAMOUS 2: blue or red, now and then both at once. Faint sheet lightning in between. Kept to x >= 1060 and
 * above the footer by the caller's clip, the bolt's top clear of the header's name. */
static void fx_strikes(int g, float t, float vis, float A, float ysky)
{
    clip((int)A, 0, W, H - 150);
    s_fx_ramp = A;
    FX.strike_k = 0;
    {   /* sheet lightning: a dim glow somewhere in the upper sky */
        const float P = 1.3f, c = floorf(t / P), u = t - c * P;
        const uint32_t cs = (uint32_t)(int)c * 40503u + (uint32_t)g * 977u;
        if (u < 0.22f && fx_r(cs) < 0.55f) {
            const float k = (1 - u / 0.22f) * (fx_r(cs * 7u + (uint32_t)(int)(u * 30)) < 0.6f ? 1.0f : 0.4f);
            const int col = g == 1 && fx_r(cs + 3) < 0.5f ? 3 : g;
            fx_flash(A + 120 + fx_r(cs + 1) * (1800 - A - 120), 160 + fx_r(cs + 2) * 220, 200 + fx_r(cs + 4) * 90, s_fx_dark ? 0x500010 : kFxGlow[col], (s_fx_dark ? 0.10f : 0.16f) * k * vis);
        }
    }
    const float P = 3.4f, c = floorf(t / P);
    const uint32_t cs = (uint32_t)(int)c * 7919u + (uint32_t)g * 104729u;
    const float start = c * P + 0.3f + fx_r(cs) * 1.9f, u = t - start, D = 0.55f;
    if (u < 0 || u > D || fx_r(cs + 1) > 0.88f) return;
    const int fl = (int)(u * 26);
    float env = 1.0f - u / D;
    env *= u < 0.06f ? 1.0f : fx_r(cs * 31u + (uint32_t)fl) < 0.65f ? 1.0f : 0.22f;
    env *= vis;
    const int sky = ysky > 0 && ((int)c & 1);   /* (a wide name: every other strike in the sky above it) */
    if (sky) { A = 1060; clip((int)A, 0, W, (int)ysky); s_fx_ramp = A; s_fx_rampy = ysky; }
    const int both = g == 1 && fx_r(cs + 2) < 0.4f;
    for (int s = 0; s <= both; s++) {
        const uint32_t ss = cs * 13u + (uint32_t)s * 0x2545F491u;
        const int col = g == 1 ? (both ? (s ? 3 : 1) : ((int)c & 1) ? 3 : 1) : g;
        const float a0 = A + 90, sp = 1850 - a0;   /* (the free part of the sky, right of the menu's column) */
        const float x0 = both ? a0 + sp * (s ? 0.42f + 0.16f * fx_r(ss + 3) : 0.16f * fx_r(ss + 3)) : a0 + sp * 0.5f * fx_r(ss + 3);
        float x1 = both ? a0 + sp * (s ? 0.6f + 0.35f * fx_r(ss + 4) : 0.15f + 0.3f * fx_r(ss + 4)) : a0 + sp * (0.15f + 0.85f * fx_r(ss + 4));
        const float tl = W - 140 - (s_title.px ? s_title.w : text_w(&F_body, 20, "inFAMOUS  ReCHARGED")) - 90;
        const float y0 = x0 > tl ? 126 : -24;   /* (under the header's name, not through it) */
        const float y1 = sky ? ysky - 50 - fx_r(ss + 5) * 110 : 470 + fx_r(ss + 5) * 330;
        const uint32_t jit = ss ^ (uint32_t)(fl / 2) * 0x9E3779B9u;
        /* the clouds lit from inside, then the bolt */
        fx_flash(x0 + (x1 - x0) * 0.35f, y1 * 0.3f, 430, s_fx_dark ? 0x58000E : kFxGlow[col], (s_fx_dark ? 0.22f : 0.30f) * env);
        fx_flash(x1, y1, 150, s_fx_dark ? 0x7A0010 : kFxGlow[col], 0.35f * env);
        const int n = fx_bolt(s_fxa_x, s_fxa_y, FX_LV, x0, y0, x1, y1, 0.62f, ss, jit);
        fx_bolt_draw(s_fxa_x, s_fxa_y, n, s_fx_dark ? 2.4f : 1.7f, s_fx_dark ? 24 : 17, kFxGlow[col], kFxCore[col], env, 0.35f);
        for (int b = 0; b < 4; b++) {   /* branches, thinner, off the main bolt's middle */
            const uint32_t bs = ss * 31u + (uint32_t)b * 0x68E31DA4u;
            if (fx_r(bs) < 0.25f) continue;
            const int at = 10 + (int)(fx_r(bs + 1) * 40);
            const float ddx = s_fxa_x[at + 4] - s_fxa_x[at], ddy = s_fxa_y[at + 4] - s_fxa_y[at];
            const float dl = sqrtf(ddx * ddx + ddy * ddy) + 1e-3f;
            const float ang = (fx_r(bs + 2) < 0.5f ? -1.0f : 1.0f) * (0.35f + 0.55f * fx_r(bs + 3)), len = 80 + fx_r(bs + 4) * 200;
            const float ca = fx_cos(ang), sa = sinf(ang), ux = ddx / dl, uy = ddy / dl;
            const float ex = s_fxa_x[at] + (ux * ca - uy * sa) * len, ey = s_fxa_y[at] + (ux * sa + uy * ca) * len;
            const int m = fx_bolt(s_fxb_x, s_fxb_y, 4, s_fxa_x[at], s_fxa_y[at], ex, ey, 0.7f, bs, jit + (uint32_t)b);
            fx_bolt_draw(s_fxb_x, s_fxb_y, m, 1.0f, 10, kFxGlow[col], kFxCore[col], env * 0.75f, 0.85f);
        }
    }
    FX.strike_k = env;
}

/* Festival of Blood: a few bats crossing the sky now and then. */
static void fx_tri(float ax, float ay, float bx, float by, float cx, float cy, uint32_t rgb, int a)
{
    const float area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
    if (area > -0.5f && area < 0.5f) return;
    const float ia = 1.0f / area;
    int x0 = (int)floorf(ax < bx ? (ax < cx ? ax : cx) : (bx < cx ? bx : cx)), x1 = (int)ceilf(ax > bx ? (ax > cx ? ax : cx) : (bx > cx ? bx : cx));
    int y0 = (int)floorf(ay < by ? (ay < cy ? ay : cy) : (by < cy ? by : cy)), y1 = (int)ceilf(ay > by ? (ay > cy ? ay : cy) : (by > cy ? by : cy));
    if (x0 < s_cx0) x0 = s_cx0;
    if (y0 < s_cy0) y0 = s_cy0;
    if (x1 > s_cx1) x1 = s_cx1;
    if (y1 > s_cy1) y1 = s_cy1;
    for (int y = y0; y < y1; y++)
        for (int x = x0; x < x1; x++) {
            const float px = x + 0.5f, py = y + 0.5f;
            const float w0 = ((bx - px) * (cy - py) - (by - py) * (cx - px)) * ia;
            const float w1 = ((cx - px) * (ay - py) - (cy - py) * (ax - px)) * ia;
            const float w2 = 1.0f - w0 - w1;
            if (w0 < 0 || w1 < 0 || w2 < 0) continue;
            blend_px(&s_fb[(size_t)y * W + x], rgb, a);
        }
}
static void fx_bats(float t, float vis)
{
    const float P = 13.0f, c = floorf(t / P), u = t - c * P, dur = 8.0f;
    if (u > dur) return;
    const uint32_t cs = (uint32_t)(int)c * 2246822519u;
    const float y0 = 175 + fx_r(cs) * 90;
    for (int i = 0; i < 5; i++) {
        const uint32_t bs = cs + (uint32_t)i * 374761393u;
        const float ui = (u - fx_r(bs) * 0.9f) / (dur - 1.0f);
        if (ui < 0 || ui > 1) continue;
        const float x = W + 70 - ui * (W + 70 - 1020) - i * 26.0f, y = y0 + (fx_r(bs + 1) - 0.5f) * 50 + 16 * sinf(t * 2.1f + (float)i * 1.3f);
        const float s = 0.55f + 0.45f * fx_r(bs + 2), f = sinf(t * (12.0f + 4.0f * fx_r(bs + 3)) + (float)i * 2.0f);
        float a = x < 1240 ? (x - 1090) / 150 : 1.0f;
        if (a <= 0) continue;
        const int al = (int)(215 * a * vis);
        const uint32_t col = 0x06070B;
        for (int side = -1; side <= 1; side += 2) {   /* a wing: shoulder, tip, two scallops; the flap lifts the tip */
            const float sx = (float)side * s;
            fx_tri(x + 2 * sx, y - 1 * s, x + 25 * sx, y - (4 + 11 * f) * s, x + 17 * sx, y + (3 - 4 * f) * s, col, al);
            fx_tri(x + 2 * sx, y - 1 * s, x + 17 * sx, y + (3 - 4 * f) * s, x + 7 * sx, y + 5 * s, col, al);
        }
        fx_tri(x, y - 6 * s, x - 3 * s, y + 4 * s, x + 3 * s, y + 4 * s, col, al);
    }
}

/* Points on the outline of each game's HOME logo (or its name in the title font), from the top-left; made once. */
enum { FX_EDGE = 600 };
static int16_t s_fx_ex[NGAMES][FX_EDGE], s_fx_ey[NGAMES][FX_EDGE];
static int s_fx_en[NGAMES] = { -1, -1, -1 };
static void fx_logo_rect(int g, float* x, float* y, int* w, int* h)
{
    float yy = 200;
    for (int i = 0; i < g; i++) yy += kLogoSmallH[i] + 26;   /* (draw_home's layout: the others above it, small) */
    *x = 140 + PDX(); *y = yy; *h = kLogoH[g];
    *w = s_logo[g].px ? s_logo[g].w : text_w(&F_title, kLogoH[g], kName[g]);
}
static void fx_edges(int g)
{
    int n = 0, seen = 0;
    for (int pass = 0; pass < 2; pass++) {
        const int stride = pass ? seen / FX_EDGE + 1 : 1;
        int k = 0;
        if (s_logo[g].px) {
            const img_t* im = &s_logo[g];
            for (int y = 1; y < im->h - 1; y++)
                for (int x = 1; x < im->w - 1; x++) {
                    const uint32_t* p = &im->px[(size_t)y * im->w + x];
                    if ((p[0] >> 24) < 128) continue;
                    if ((p[-1] >> 24) >= 128 && (p[1] >> 24) >= 128 && (p[-im->w] >> 24) >= 128 && (p[im->w] >> 24) >= 128) continue;
                    if (!pass) { seen++; continue; }
                    if (k++ % stride == 0 && n < FX_EDGE) { s_fx_ex[g][n] = (int16_t)x; s_fx_ey[g][n] = (int16_t)y; n++; }
                }
        } else if (F_title.ok) {
            const int h = kLogoH[g], base = (int)lroundf(-h * 0.1f + F_title.ascent * h);
            int x = 0;
            for (const char* s = kName[g]; *s;) {
                const glyph_t* gl = glyph(&F_title, h, utf8(&s));
                for (int j = 1; j < gl->h - 1; j++)
                    for (int i = 1; i < gl->w - 1; i++) {
                        const uint8_t* q = &gl->bm[j * gl->w + i];
                        if (q[0] < 128 || (q[-1] >= 128 && q[1] >= 128 && q[-gl->w] >= 128 && q[gl->w] >= 128)) continue;
                        if (!pass) { seen++; continue; }
                        if (k++ % stride == 0 && n < FX_EDGE) { s_fx_ex[g][n] = (int16_t)(x + gl->xo + i); s_fx_ey[g][n] = (int16_t)(base + gl->yo + j); n++; }
                    }
                x += gl->adv;
            }
        }
    }
    s_fx_en[g] = n;
}

/* The chosen game's name charged: its shape blurred once (two box blurs) into a halo drawn behind it, flickering with
 * the arcs (Festival of Blood: a dark red shadow, which also sets the white name off its pale picture). */
enum { FX_AW = 1600, FX_AH = 240, FX_AP = 22 };
static uint8_t s_fx_aura[NGAMES][FX_AW * FX_AH];
static int s_fx_aw[NGAMES], s_fx_ah[NGAMES] = { -1, -1, -1 };
static void fx_blur_line(uint8_t* p, int n, int step, int r)
{
    static uint8_t tmp[FX_AW > FX_AH ? FX_AW : FX_AH];
    for (int i = 0; i < n; i++) tmp[i] = p[i * step];
    int sum = 0;
    for (int i = -r; i <= r; i++) sum += i >= 0 && i < n ? tmp[i] : 0;
    for (int i = 0; i < n; i++) {
        p[i * step] = (uint8_t)(sum / (2 * r + 1));
        const int add = i + r + 1, sub = i - r;
        sum += (add < n ? tmp[add] : 0) - (sub >= 0 ? tmp[sub] : 0);
    }
}
static void fx_aura_build(int g)
{
    float lx, ly; int lw, lh;
    fx_logo_rect(g, &lx, &ly, &lw, &lh);
    const int aw = lw + 2 * FX_AP > FX_AW ? FX_AW : lw + 2 * FX_AP, ah = lh + 2 * FX_AP > FX_AH ? FX_AH : lh + 2 * FX_AP;
    uint8_t* m = s_fx_aura[g];
    memset(m, 0, sizeof s_fx_aura[g]);
    if (s_logo[g].px) {
        for (int y = 0; y < s_logo[g].h && y + FX_AP < ah; y++)
            for (int x = 0; x < s_logo[g].w && x + FX_AP < aw; x++) m[(y + FX_AP) * aw + x + FX_AP] = (uint8_t)(s_logo[g].px[(size_t)y * s_logo[g].w + x] >> 24);
    } else if (F_title.ok) {
        const int h = kLogoH[g], base = (int)lroundf(-h * 0.1f + F_title.ascent * h);
        int x = 0;
        for (const char* s = kName[g]; *s;) {
            const glyph_t* gl = glyph(&F_title, h, utf8(&s));
            for (int j = 0; j < gl->h; j++)
                for (int i = 0; i < gl->w; i++) {
                    const int xx = x + gl->xo + i + FX_AP, yy = base + gl->yo + j + FX_AP;
                    if (xx >= 0 && xx < aw && yy >= 0 && yy < ah) m[yy * aw + xx] = gl->bm[j * gl->w + i];
                }
            x += gl->adv;
        }
    }
    for (int it = 0; it < 2; it++) {
        for (int y = 0; y < ah; y++) fx_blur_line(m + y * aw, aw, 1, 7);
        for (int x = 0; x < aw; x++) fx_blur_line(m + x, ah, aw, 7);
    }
    s_fx_aw[g] = aw; s_fx_ah[g] = ah;
}
static void fx_aura(float t)
{
    const int g = S.game;
    if (s_fx_ah[g] < 0) fx_aura_build(g);
    float lx, ly; int lw, lh;
    fx_logo_rect(g, &lx, &ly, &lw, &lh);
    const float pin = M.page_in < 1 ? M.page_in : 1, gt = t - FX.game_t, burst = gt >= 0 && gt < 0.45f ? 1.0f - gt / 0.45f : 0;
    float k = (0.55f + 0.2f * sinf(t * 2.3f) + 0.25f * (fx_r((uint32_t)(int)(t * 18)) < 0.25f ? 1.0f : 0) + 0.8f * burst) * pin;
    const uint32_t c = kFxGlow[g];
    const int aw = s_fx_aw[g], ah = s_fx_ah[g], ox = (int)lx - FX_AP, oy = (int)ly - FX_AP;
    const int xs = ox < s_cx0 ? s_cx0 - ox : 0, xe = ox + aw > s_cx1 ? s_cx1 - ox : aw;
    const uint32_t kk = (uint32_t)(k * 256), ka = (uint32_t)(k * 0.75f * 256), rb = c & 0xFF00FFu, gc = c & 0xFF00u;
    for (int y = 0; y < ah; y++) {
        const int yy = oy + y;
        if (yy < s_cy0 || yy >= s_cy1) continue;
        const uint8_t* m = s_fx_aura[g] + y * aw;
        uint32_t* row = s_fb + (size_t)yy * W + ox;
        if (s_fx_dark)
            for (int x = xs; x < xe; x++) { uint32_t a = m[x] * ka >> 8; a = a > 230 ? 230 : a; row[x] = fx_mix(row[x], 0x2A0006, a); }
        else
            for (int x = xs; x < xe; x++) {
                uint32_t q = m[x] * kk >> 8; q = q > 256 ? 256 : q;
                row[x] = fx_sat(row[x], (rb * q >> 8 & 0xFF00FFu) | (gc * q >> 8 & 0xFF00u));
            }
    }
}

static void fx_back(void)
{
    if (!S.fx) return;
    const float t = M.time;
    const int g = (int)(M.shown_game + 0.5f);
    float home = 1.0f - M.page_dark / 0.74f;
    home = home < 0 ? 0 : home > 1 ? 1 : home;
    s_fx_dark = g == 2;
    clip(0, 0, W, H - 150);
    fx_embers(g, t, 0.35f + 0.65f * home);
    unclip();
    FX.strike_k = 0;
    if (M.page == P_HOME && s_cleanup_g < 0) { s_fx_dark = S.game == 2; fx_aura(t); s_fx_dark = g == 2; }
    if (home > 0.02f) {
        /* right of the menu's column and of the chosen name (Festival of Blood's runs far right), above the footer */
        float lx, ly; int lw, lh;
        fx_logo_rect(S.game, &lx, &ly, &lw, &lh);
        const float A = lx + lw + 40 > 1060 ? lx + lw + 40 : 1060;
        fx_strikes(g, t, home, A, A > 1300 ? ly - 14 : 0);
        s_fx_ramp = s_fx_rampy = 0;
        clip(1060, 130, W, (int)ly - 10);
        if (g == 2) fx_bats(t, home);
        unclip();
    }
    s_fx_dark = 0;
}

/* ---- in front (after the menu): on the chosen game's name, the tabs' rule, the start of a game ---- */

/* Arcs jumping between points of the chosen game's name (a burst of them for 0.45 s after the choice changes), and the
 * accent bar beside it glowing. Clipped to the name's box: not onto PLAY. */
static void fx_logo(float t)
{
    const int g = S.game;
    float lx, ly; int lw, lh;
    fx_logo_rect(g, &lx, &ly, &lw, &lh);
    if (s_fx_en[g] < 0) fx_edges(g);
    const float pin = M.page_in < 1 ? M.page_in : 1;
    const float gt = t - FX.game_t, burst = gt >= 0 && gt < 0.45f ? 1.0f - gt / 0.45f : 0;
    {   /* the bar: draw_home's, lit */
        const float pulse = 0.7f + 0.3f * sinf(t * 5.0f), bx = lx - 31;
        fx_seg(bx, ly + lh * 0.12f + 6, bx, ly + lh * 0.88f - 6, 0, 30, C_ACCENT, 0, (0.28f * pulse + 0.4f * burst) * pin, 1);
    }
    const int n = s_fx_en[g];
    if (n < 8) return;
    clip((int)lx - 26, (int)ly - 22, (int)lx + lw + 30, (int)ly + lh + 6);
    s_fx_dark = g == 2;
    const int slots = 6 + (int)(burst * 8);
    for (int j = 0; j < slots; j++) {
        const float P = 0.45f + 0.6f * fx_r((uint32_t)j * 77u + 5u);
        const float tt = t + (float)j * 0.31f, c = floorf(tt / P), u = tt - c * P;
        const uint32_t sc = (uint32_t)(int)c * 0x9E3779B9u + (uint32_t)j * 1013u + (uint32_t)g;
        float k;
        if (j >= 6) k = burst;
        else {
            const float life = 0.10f + 0.18f * fx_r(sc);
            if (fx_r(sc + 1) > 0.8f || u > life) continue;
            k = 1.0f - 0.5f * u / life;
        }
        const int a = (int)(fx_r(sc + 2) * n) % n;
        int b = -1;
        for (int tries = 0; tries < 8 && b < 0; tries++) {
            const int q = (int)(fx_r(sc + 3 + (uint32_t)tries) * n) % n;
            const float ddx = s_fx_ex[g][q] - s_fx_ex[g][a], ddy = s_fx_ey[g][q] - s_fx_ey[g][a], d2 = ddx * ddx + ddy * ddy;
            if (d2 > 14 * 14 && d2 < 90 * 90) b = q;
        }
        if (b < 0) continue;
        const int col = g == 1 && (j & 1) ? 3 : g;
        const int m = fx_bolt(s_fxb_x, s_fxb_y, 4, lx + s_fx_ex[g][a], ly + s_fx_ey[g][a], lx + s_fx_ex[g][b], ly + s_fx_ey[g][b], 0.6f, sc, sc ^ (uint32_t)(int)(t * 30) * 0x85EBCA6Bu);
        fx_bolt_draw(s_fxb_x, s_fxb_y, m, 0.9f, 9, kFxGlow[col], kFxCore[col], k * pin * (s_fx_dark ? 0.7f : 1.0f), 0.2f);
    }
    s_fx_dark = 0;
    unclip();
}

/* A page change: the new tab's underline flares and two bolts run out along the header's rule (0.55 s). */
static void fx_page_burst(float t)
{
    const float u = t - FX.page_t, D = 0.55f;
    if (u < 0 || u > D) return;
    const float k = 1.0f - u / D, cy = 58 + 58.5f, cx = M.tab_x + M.tab_w * 0.5f;
    clip(100, 102, W - 100, 150);
    fx_seg(M.tab_x, cy, M.tab_x + M.tab_w, cy, 2, 24, C_ACCENT, 0xFFFFFF, k, 1);
    const float reach = 120 + 1500 * sqrtf(u / D);
    const uint32_t jit = (uint32_t)(int)(t * 30) * 0x9E3779B9u;
    for (int s = -1; s <= 1; s += 2) {
        float ex = cx + s * reach;
        ex = ex < 140 ? 140 : ex > W - 140 ? W - 140 : ex;
        const int m = fx_bolt(s_fxb_x, s_fxb_y, 5, cx, cy + 2, ex, 119.5f, 0.22f, (uint32_t)s * 7u + (uint32_t)(int)(FX.page_t * 10), jit + (uint32_t)s);
        fx_bolt_draw(s_fxb_x, s_fxb_y, m, 0.9f, 10, kFxGlow[0], kFxCore[0], k, 0.9f);
    }
    unclip();
}

/* The header's name, lit by each strike. */
static void fx_title(void)
{
    const float k = FX.strike_k;
    if (k <= 0.02f) return;
    if (s_title.px) {
        const int ty = s_title.h > 46 ? 58 + 20 - s_title.h / 2 : 58 - 2, x0 = W - 140 - s_title.w;
        for (int j = 0; j < s_title.h; j++)
            for (int i = 0; i < s_title.w; i++) {
                const uint32_t s = s_title.px[(size_t)j * s_title.w + i];
                const float a = (s >> 24) * k * (0.45f / 255.0f);
                if (a > 0.004f) fx_px(&s_fb[(size_t)(ty + j) * W + x0 + i], (int)(((s >> 16) & 255) * a), (int)(((s >> 8) & 255) * a), (int)((s & 255) * a));
            }
    } else {
        textt(&F_body, 20, W - 140 - text_w(&F_body, 20, "inFAMOUS  ReCHARGED"), 58 + 12, C_WHITE, (int)(200 * k), "inFAMOUS  ReCHARGED");
    }
}

/* X on PLAY: bolts from the screen's edges into the chosen game's name and a flash swelling out of it (0.9 s, under the
 * fade to black). */
static void fx_launch(float t)
{
    const float u = t - FX.launch_t, D = 0.9f;
    if (u < 0 || u > D) return;
    const int g = S.game;
    float lx, ly; int lw, lh;
    fx_logo_rect(g, &lx, &ly, &lw, &lh);
    const float cx = lx + lw * 0.5f, cy = ly + lh * 0.5f, ramp = u < 0.12f ? u / 0.12f : 1.0f;
    const int n = s_fx_en[g] > 0 ? s_fx_en[g] : 0;
    const uint32_t jit = (uint32_t)(int)(t * 30) * 0x9E3779B9u;
    for (int i = 0; i < 4; i++) {
        const uint32_t bs = (uint32_t)i * 0x27D4EB2Fu + (uint32_t)(int)(FX.launch_t * 7);
        const float e = fx_r(bs);
        const float sx = i < 2 ? W + 20 : 500 + e * (W - 700), sy = i < 2 ? 160 + e * 700 : (i & 1 ? -20 : H + 20);
        const float tx = n ? lx + s_fx_ex[g][(int)(fx_r(bs + 1) * n) % n] : cx, ty = n ? ly + s_fx_ey[g][(int)(fx_r(bs + 2) * n) % n] : cy;
        const int col = g == 1 && (i & 1) ? 3 : g;
        const int m = fx_bolt(s_fxa_x, s_fxa_y, FX_LV, sx, sy, tx, ty, 0.5f, bs, jit + (uint32_t)i);
        fx_bolt_draw(s_fxa_x, s_fxa_y, m, 1.6f, 12, kFxGlow[col], kFxCore[col], ramp * (fx_r(jit + (uint32_t)i) < 0.75f ? 1.0f : 0.3f), 0.3f);
    }
    const float f = u / D;   /* (a burst of light out of the name, gone as the fade to black takes over) */
    if (f < 0.6f) fx_flash(cx, cy, 240 + 900 * f, kFxGlow[g], 0.9f * (1.0f - f / 0.6f));
}

static void fx_front(void)
{
    if (!S.fx) return;
    const float t = M.time;
    fx_title();
    if (M.page == P_HOME && s_cleanup_g < 0) fx_logo(t);
    fx_page_burst(t);
    fx_launch(t);
}

static void draw_frame(float fade)
{
    s_ml = lang_of(&G[M.page == P_SETTINGS ? M.set_game : S.game]);
    s_pt = s_ml == LANG_PT;
    draw_background();
    fx_back();
    draw_tabs();
    switch (M.page) {
    case P_HOME: draw_home(); break;
    case P_CONTENT: draw_content(); break;
    case P_SAVES: draw_saves(); break;
    case P_TROPHIES: draw_trophies(); break;
    case P_SETTINGS: draw_settings(); break;
    default: draw_credits(); break;
    }
    draw_footer();
    fx_front();
#ifdef LAUNCHER_HOST
    if (getenv("LHOST_CLEANUP") && s_cleanup_g < 0) { s_cleanup_g = 0; s_cleanup_n = 1; s_cleanup_bytes = 7628128256ull; }
#endif
    if (s_cleanup_g >= 0) {   /* the delete/keep prompt */
        rect(0, 0, W, H, 0x000000, PA(170));
        char msg[900];
        snprintf(msg, sizeof msg, T("%s IS INSTALLED\n\nDelete the %d file(s) it was installed from in install/ (%.1f GB) to free the space?\n\nX  DELETE      O  KEEP%s",
                                    "%s ESTÁ INSTALADO\n\nApagar o(s) %d arquivo(s) de install/ usados na instalação (%.1f GB) para liberar espaço?\n\nX  APAGAR      O  MANTER%s"),
                 kName[s_cleanup_g], s_cleanup_n, s_cleanup_bytes / 1e9,
                 confirming() ? T("\n\nPRESS X AGAIN TO DELETE", "\n\nAPERTE X DE NOVO PARA APAGAR") : "");
        rect(W / 2 - 500, H / 2 - 180, 1000, 300, 0x06101C, PA(255));
        panel_msg(W / 2 - 480, H / 2 - 160, 960, msg, C_ACCENT);
    }
    if (fade > 0) rect(0, 0, W, H, 0x000000, (int)(fade * 255));
}

/* The menu's easing, dt seconds on. */
static void animate(float dt)
{
    M.time += dt;
    float k = dt * 5.0f; if (k > 1) k = 1;
    /* (SETTINGS: the picture of the game whose settings they are) */
    const int shown = M.page == P_SETTINGS ? M.set_game : S.game;
    M.shown_game += (shown - M.shown_game) * k;
    if (fabsf(shown - M.shown_game) < 0.004f) M.shown_game = (float)shown;
    k = dt * 6.0f; if (k > 1) k = 1;
    const float dark = M.page == P_HOME ? 0.0f : 0.74f;
    M.page_dark += (dark - M.page_dark) * k;
    if (fabsf(dark - M.page_dark) < 0.003f) M.page_dark = dark;
    M.page_in += dt * 6.0f; if (M.page_in > 1) M.page_in = 1;
    k = dt * 14.0f; if (k > 1) k = 1;
    M.tab_x += (M.tab_tx - M.tab_x) * k;
    M.tab_w += (M.tab_tw - M.tab_w) * k;
}

static void set_page(int p)
{
    if (p == M.page) return;
    M.page = p; M.page_in = 0; M.confirm_t = -100;
    FX.page_t = M.time;
    if (p == P_SETTINGS) { M.set_game = S.game; M.in_list = 0; }   /* (the game HOME has chosen, first) */
}

int main(int argc, char** argv)
{
    (void)argc; (void)argv;
    mkdir(APP "/logs", 0777);
    s_log = fopen(APP "/logs/launcher.log", "w");
    s_updl_logf = logf_;   /* (the update download's lines into this log) */
    logf_("inFamous: ReCharged launcher, built %s %s\n", __DATE__, __TIME__);
    settings_load();
    s_fb = malloc((size_t)W * H * 4);
    font_load(&F_title, APP "/launcher/font_title.ttf");
    font_load(&F_item, APP "/launcher/font_item.ttf");
    font_load(&F_body, APP "/launcher/font_body.ttf");
    font_load(&F_fb, APP "/launcher/font_fallback.ttf");
    font_load(&F_cjk, APP "/launcher/font_cjk.ttc");
    {   /* the header's name: 96 pixels tall drawn 46 (taller: its glow, in proportion) */
        int tw = 0, th = 0, n;
        if (stbi_info(APP "/launcher/title.png", &tw, &th, &n) && th > 0)
            s_title = img_load(APP "/launcher/title.png", (int)lroundf(tw * 46.0f * (th > 96 ? th / 96.0f : 1) / th),
                               (int)lroundf(46.0f * (th > 96 ? th / 96.0f : 1)), 0);
    }
    for (int i = 0; i < NGAMES; i++) {
        char p[160];
        snprintf(p, sizeof p, APP "/launcher/bg_%s.jpg", kDir[i]);
        s_base[i] = img_load(p, W, H, 1);
        bake_base(&s_base[i]);
        snprintf(p, sizeof p, APP "/launcher/logo_%s.png", kDir[i]);
        if (file_exists(p)) {
            s_logo[i] = img_load_h(p, kLogoH[i]); s_logo_small[i] = img_load_h(p, kLogoSmallH[i]);
            s_logo_set[i] = img_load_h(p, kLogoSetH[i]); s_logo_set_small[i] = img_load_h(p, kLogoSetSmallH[i]);
        }
        char bin[64], data[96];
        snprintf(bin, sizeof bin, APP "/%s.bin", kDir[i]);
        snprintf(data, sizeof data, APP "/%s/game/PS3_GAME", kDir[i]);
        s_installed[i] = file_exists(bin) && file_exists(data);
        logf_("%s: %s %s\n", kName[i], file_exists(bin) ? "program ok" : "NO PROGRAM", file_exists(data) ? "data ok" : "NO DATA");
    }
    if (!s_installed[0] || !s_installed[1] || !s_installed[2]) {
        inst_scan(APP);
        for (int i = 0; i < s_inst_nsrc; i++) logf_("install source: %s %s %s %s\n", s_inst_src[i].name, s_inst_src[i].tid, s_inst_src[i].ver, s_inst_src[i].cat);
        for (int i = 0; i < s_inst_nnotes; i++) logf_("install note: %s\n", s_inst_notes[i]);
    }
    M.shown_game = (float)S.game;
#ifdef LAUNCHER_HOST
    /* PC check (host_test.sh): pages drawn into <APP>/shot_<k>.ppm, eased in. */
    { /* page, row, game; SETTINGS: in the game list (4), in a game's settings (5), SQUARE once (6) */
      const int shots[8][3] = { { P_HOME, 0, 0 }, { P_SETTINGS, 1, 1 }, { P_HOME, 0, 2 }, { P_CONTENT, 1, 1 },
                                { P_SETTINGS, 1, 1 }, { P_SETTINGS, 2, 2 }, { P_SETTINGS, 4, 0 }, { P_CREDITS, 0, 1 } };
      G[2].skip_movies = 0;   /* (a game's own settings, unlike the others') */
      for (int k = 0; k < 8; k++) {
          M.page = shots[k][0]; M.row = M.content_row = shots[k][1]; S.game = M.set_game = shots[k][2];
          M.in_list = k == 5 || k == 6;
          M.confirm_t = k == 6 ? M.time + 2.0f : -100;
          if (k == 1) snprintf(M.error, sizeof M.error, "Couldn't start inFAMOUS 2 (0x80020001).");
          else M.error[0] = 0;
          if (k == 2) s_installed[2] = 0;
          for (int f = 0; f < 120; f++) { animate(1 / 60.0f); draw_frame(0); }
          char p[256]; snprintf(p, sizeof p, APP "/shot_%d.ppm", k);
          FILE* f = fopen(p, "wb"); fprintf(f, "P6\n%d %d\n255\n", W, H);
          for (size_t i = 0; i < (size_t)W * H; i++) { uint8_t c[3] = { (uint8_t)(s_fb[i] >> 16), (uint8_t)(s_fb[i] >> 8), (uint8_t)s_fb[i] }; fwrite(c, 1, 3, f); }
          fclose(f);
      }
      return 0; }
#endif
    if (vk_up() != 0) { logf_("no display: starting the last game\n"); }
    s_volume = S.music / 100.0f;
    s_want_track = S.game;
    pthread_create(&s_audio_th, NULL, audio_main, NULL);

    int leaving = 0;
    double leave_t = 0, start_t = now_s();
    /* Autostart (development): /app0/autostart.txt naming a game folder (if1, if2, fob) starts that game at
     * once; the file is emptied first, so the next launch shows the menu again. */
    { FILE* af = fopen(APP "/autostart.txt", "r");
      if (af) {
          char line[64] = "", want[16] = "";
          if (!fgets(line, sizeof line, af) || sscanf(line, "%15s", want) != 1) want[0] = 0;
          fclose(af);
          { FILE* z = fopen(APP "/autostart.txt", "w"); if (z) fclose(z); }   /* emptied, not removed: no new import */
          for (int i = 0; i < NGAMES; i++)
              if (!strcmp(want, kDir[i]) && s_installed[i]) { S.game = i; leaving = 1; s_volume = 0; logf_("autostart: %s\n", kName[i]); }
      } }
    double last = now_s();
    for (;;) {
        const double t = now_s();
        const double dt = t - last; last = t;
        const uint32_t p = leaving ? 0 : pad_pressed();
        if (s_cleanup_g >= 0) {   /* the delete/keep prompt has the pad */
            if (p & B_CROSS) { if (confirming()) { cleanup_do(); M.confirm_t = -100; } else M.confirm_t = M.time; }
            else if (p & B_CIRCLE) { logf_("cleanup: kept the install files\n"); s_cleanup_g = -1; M.confirm_t = -100; }
        } else {
        if (p & B_L1) set_page((M.page + NPAGES - 1) % NPAGES);
        if (p & B_R1) set_page((M.page + 1) % NPAGES);
        if ((p & B_CIRCLE) && M.page == P_SETTINGS && M.in_list) M.in_list = 0;   /* (back to the games first) */
        else if ((p & B_CIRCLE) && M.page != P_HOME) set_page(P_HOME);
        if (M.page == P_HOME) {
            if (p & B_UP) { S.game = (S.game + NGAMES - 1) % NGAMES; M.error[0] = 0; M.confirm_t = -100; fx_event_game(); }
            if (p & B_DOWN) { S.game = (S.game + 1) % NGAMES; M.error[0] = 0; M.confirm_t = -100; fx_event_game(); }
            if ((p & B_CROSS) && s_installed[S.game] && s_needs_cache[S.game] && s_inst.state != 1) {
                if (inst_start_remote_mode(APP, S.game, 1) == 0) logf_("repair %s: sent to the installer payload\n", kDir[S.game]);
                else if (inst_start_cache(APP, S.game) == 0) logf_("repair %s: in the app\n", kDir[S.game]);
            }
            else if ((p & B_CROSS) && s_installed[S.game] && s_inst.state != 1) {
                if (s_updl.state != 1) { leaving = 1; leave_t = 0; s_volume = 0; fx_event_launch(); }   /* (not while downloading: LoadExec would end that thread) */
                else snprintf(M.error, sizeof M.error, "%s", T("inFAMOUS 2's updates are downloading: wait until they're done, then start the game.",
                                                               "As atualizações de inFAMOUS 2 estão baixando: espere terminar e inicie o jogo."));
            }
            else if ((p & B_CROSS) && s_inst.state != 1) {
                inst_src_t* o_[8]; char need_[300];
                if (!inst_plan(S.game, o_, need_, sizeof need_)) {
                    if (S.game == INST_IF2 && (s_updl.state == 1 || updl_go(S.game) == 0)) {   /* only its updates missing: downloading them */
                        if (s_inst.state == 3 && s_inst.game == S.game) s_inst.state = 0;
                    } else {
                        memset(&s_inst, 0, sizeof s_inst); s_inst.game = S.game; s_inst.state = 3;
                        snprintf(s_inst.err, sizeof s_inst.err, "Missing %s", need_);
                        logf_("install %s: %s\n", kDir[S.game], s_inst.err);
                    }
                } else if (inst_start_remote(APP, S.game) == 0) logf_("install %s: sent to the installer payload (port 9021)\n", kDir[S.game]);
                else if (inst_start(APP, S.game) == 0) logf_("install %s: no payload loader, installing in the app (%d sources)\n", kDir[S.game], s_inst.nsrc);
                else logf_("install %s: %s\n", kDir[S.game], s_inst.err);
            }
            if ((p & B_TRIANGLE) && !s_installed[S.game] && s_inst.state != 1) inst_scan(APP);
            s_want_track = S.game;
        } else if (M.page == P_TROPHIES) {
            if (p & B_UP) M.tr_scroll = M.tr_scroll > 0 ? M.tr_scroll - 1 : 0;
            if (p & B_DOWN) M.tr_scroll++;
            if (p & (B_LEFT | B_RIGHT)) { M.tr_game = (M.tr_game + ((p & B_LEFT) ? NGAMES - 1 : 1)) % NGAMES; M.tr_scroll = 0; }
        } else if (M.page == P_SAVES) {
            if (p & B_UP) { M.save_row = M.save_row > 0 ? M.save_row - 1 : 0; M.confirm_t = -100; }
            if (p & B_DOWN) { M.save_row++; M.confirm_t = -100; }
            if (p & (B_LEFT | B_RIGHT)) { M.save_game = (M.save_game + ((p & B_LEFT) ? NGAMES - 1 : 1)) % NGAMES; M.save_row = 0; M.confirm_t = -100; }
            if ((p & B_SQUARE) && s_inst.state != 1) {
                const int r = saves_backup(M.save_game);
                snprintf(s_save_msg, sizeof s_save_msg, "%s", r ? T("Backup failed (no saves yet?).", "Falha no backup (ainda sem saves?).") : T("Saves backed up.", "Saves guardados."));
                s_save_msg_t = M.time;
            }
            if ((p & B_CROSS) && s_nbk > 0 && s_inst.state != 1) {
                if (confirming() && M.confirm_game == 100 + M.save_game) { saves_restore(M.save_game, M.save_row); M.confirm_t = -100; }
                else { M.confirm_t = M.time; M.confirm_game = 100 + M.save_game; }
            }
            if ((p & B_TRIANGLE) && s_nbk > 0) {
                if (confirming() && M.confirm_game == 200 + M.save_game) { saves_delete(M.save_game, M.save_row); M.confirm_t = -100; }
                else { M.confirm_t = M.time; M.confirm_game = 200 + M.save_game; }
            }
        } else if (M.page == P_CONTENT) {
            if (p & B_UP) { M.content_row = (M.content_row + NGAMES - 1) % NGAMES; M.confirm_t = -100; }
            if (p & B_DOWN) { M.content_row = (M.content_row + 1) % NGAMES; M.confirm_t = -100; }
            const int cg = M.content_row;
            if ((p & B_CROSS) && s_inst.state != 1 && !s_uninst_busy) {
                if (s_installed[cg] && s_needs_cache[cg]) {
                    if (inst_start_remote_mode(APP, cg, 1) != 0) inst_start_cache(APP, cg);
                } else if (!s_installed[cg]) {
                    inst_src_t* o_[8]; char need_[300];
                    if (inst_plan(cg, o_, need_, sizeof need_)) {
                        if (inst_start_remote(APP, cg) == 0) logf_("install %s: sent to the installer payload (CONTENT)\n", kDir[cg]);
                        else if (inst_start(APP, cg) == 0) logf_("install %s: in the app (CONTENT)\n", kDir[cg]);
                    } else updl_go(cg);   /* inFAMOUS 2 with only its updates missing: download them */
                }
            }
            if ((p & B_TRIANGLE) && s_installed[cg] && s_inst.state != 1 && !s_uninst_busy) {
                if (confirming() && M.confirm_game == cg) { content_uninstall(cg); M.confirm_t = -100; logf_("uninstall %s\n", kDir[cg]); }
                else { M.confirm_t = M.time; M.confirm_game = cg; }
            }
            if ((p & B_SQUARE) && s_inst.state != 1) inst_scan(APP);
        } else if (M.page == P_SETTINGS && !M.in_list) {
            /* the game list: whose settings */
            if (p & B_UP) { M.set_game = (M.set_game + NGAMES - 1) % NGAMES; M.confirm_t = -100; }
            if (p & B_DOWN) { M.set_game = (M.set_game + 1) % NGAMES; M.confirm_t = -100; }
            if (p & (B_RIGHT | B_CROSS)) M.in_list = 1;
        } else if (M.page == P_SETTINGS) {
            gset_t* g = &G[M.set_game];
            if (p & B_UP) M.row = (M.row + NROWS - 1) % NROWS;
            if (p & B_DOWN) M.row = (M.row + 1) % NROWS;
            const int d = (p & B_LEFT) ? -1 : (p & (B_RIGHT | B_CROSS)) ? 1 : 0;
            if (d) switch (M.row) {
                case R_SKIP_INTRO: g->skip_intro ^= 1; break;
                case R_SKIP_MOVIES: g->skip_movies ^= 1; break;
                case R_DLC: if (M.set_game != 0) g->no_dlc ^= 1; break;
                case R_LANG: g->lang = (g->lang + 1 + d + NLANG + 1) % (NLANG + 1) - 1; break;   /* (AUTO first) */
                case R_GPU: if (M.set_game != 0) g->gpu_effects ^= 1; break;
                case R_UPS: g->no_fsr ^= 1; break;
                case R_AA: { int st = g->no_aa ? 0 : g->smaa ? 2 : 1; st = (st + 3 + d) % 3;   /* OFF / FXAA / SMAA */
                             g->no_aa = st == 0; g->smaa = st == 2; break; }
                case R_ANISO: { int st = g->no_aniso ? 4 : (g->aniso_dn & 3); st = (st + 5 + d) % 5;
                                g->no_aniso = st == 4; g->aniso_dn = st == 4 ? 0 : st; break; }
                case R_SHARP: g->sharp = (g->sharp + 3 + d) % 3; break;
                case R_LOOK: g->look = (g->look + 12 + d) % 12; break;   /* 12 looks */
                case R_FG: g->framegen ^= 1; break;
                case R_FPS: g->fps_counter = (g->fps_counter + 3 + d) % 3; break;
                case R_DIAG: g->diagnostics ^= 1; break;
                case R_FX: S.fx ^= 1; break;
                default: S.music += d * 10; if (S.music < 0) S.music = 0; if (S.music > 100) S.music = 100;
                         s_volume = S.music / 100.0f; break;
            }
            if (d) settings_save();
        }
        /* SQUARE, twice: the chosen game's recommended settings back (the menu music stays) */
        if ((p & B_SQUARE) && M.page == P_SETTINGS) {
            if (confirming()) {
                G[M.set_game] = kRecommended[M.set_game];
                settings_save();
                M.confirm_t = -100; M.reset_t = M.time;
                logf_("%s: recommended settings put back\n", kName[M.set_game]);
            } else {
                M.confirm_t = M.time;
            }
        }
        }   /* (the delete/keep prompt) */
        { static double nc_t = -10; if (M.time - nc_t > 2.0) { nc_t = M.time; for (int i = 0; i < NGAMES; i++) s_needs_cache[i] = s_installed[i] && inst_needs_cache(APP, i); } }
        if (s_inst.state == 2 && !s_installed[s_inst.game]) {
            char bin[64], data[96];
            snprintf(bin, sizeof bin, APP "/%s.bin", kDir[s_inst.game]);
            snprintf(data, sizeof data, APP "/%s/game/PS3_GAME", kDir[s_inst.game]);
            s_installed[s_inst.game] = file_exists(bin) && file_exists(data);
            logf_("install %s: done (%s)\n", kDir[s_inst.game], s_installed[s_inst.game] ? "playable" : "no program file");
            if (s_installed[s_inst.game]) cleanup_offer(s_inst.game);
        }
        inst_poll_remote(APP);
        if (s_updl.state == 2 && s_inst.state != 1) {   /* the updates are in install/: look again (not under an install: it reads the sources) */
            s_updl.state = 0; inst_scan(APP);
            if (s_inst.state == 3 && s_inst.game == INST_IF2) s_inst.state = 0;   /* (an old "Missing ..." from HOME's X) */
            logf_("updates: downloaded; inFAMOUS 2 %s\n", inst_if2_missing() ? "still misses some" : "can be installed");
        }
        { static int logged; if (s_updl.state == 3 && !logged) { logged = 1; logf_("updates: failed: %s\n", s_updl.err); } if (s_updl.state == 1) logged = 0; }
        if (s_inst.state == 3 && !s_inst_logged) { s_inst_logged = 1; logf_("install %s: failed: %s\n", kDir[s_inst.game], s_inst.err); }
        if (s_inst.state == 1) s_inst_logged = 0;
        if (leaving) leave_t += dt;
        animate((float)(dt > 0.1 ? 0.1 : dt));
        /* (in from black at the start, out to black when a game starts) */
        float fade = leaving ? (float)(leave_t / 0.7) : 1.0f - (float)((t - start_t) / 0.5);
        fade = fade < 0 ? 0 : fade > 1 ? 1 : fade;
        draw_frame(fade);
        if (V.dev) vk_present(); else usleep(16000);
        if (leaving && leave_t > 0.8) {
            settings_save();
            char path[64];
            snprintf(path, sizeof path, APP "/%s.bin", kDir[S.game]);
            logf_("starting %s (%s)\n", kName[S.game], path);
            s_audio_run = 0;
            pthread_join(s_audio_th, NULL);
            char* args[] = { NULL };
            const int rc = sceSystemServiceLoadExec(path, args);
            logf_("sceSystemServiceLoadExec(%s) failed: 0x%08X\n", path, (unsigned)rc);
            snprintf(M.error, sizeof M.error, T("Couldn't start %s (0x%08X).", "Não deu para iniciar %s (0x%08X)."), kName[S.game], (unsigned)rc);
            leaving = 0; s_volume = S.music / 100.0f; s_audio_run = 1;
            pthread_create(&s_audio_th, NULL, audio_main, NULL);
        }
    }
    return 0;
}
