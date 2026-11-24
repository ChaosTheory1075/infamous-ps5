/* vk quickmenu: the in-game QUICK MENU, as the other PS5 recomps draw it (Metal Gear Rising's mgr_quick_menu.cpp,
 * the template for every port: same panel, colours, fonts, fade and controls).
 *   L3 + R3 opens it over the game (cellPad's pad_overlay_gate counts the combo: g_pad_overlay_toggle), O or
 *   L3 + R3 closes it. Up/Down move, Left/Right/X change. While it is open the game reads an idle controller
 *   (g_pad_overlay_open), and after it closes the pad stays idle until every button is let go.
 *   Rows: DISPLAY (FPS counter, look, anti-aliasing) and CONTROLLER (DualSense features). Each change applies at
 *   once and is written to the launcher's ini files (PS3_QM_INI, ':'-separated), so the launcher shows it and the
 *   next start keeps it.
 * Drawn with the launcher's own fonts (/app0/launcher/font_item.ttf, font_body.ttf, stb_truetype) into a CPU
 * raster uploaded as a texture; the full-screen dim is a second quad reading the raster's last rows.
 * PS3_QUICK_MENU=0: off. Included by rsx_vulkan_backend.c after vk_overlay.inc and vk_fsr.inc.
 * rsx lightning (PS3_LIGHTNING_LIVE=1 only; rsx_lightning.inc): a LIGHTNING row under DISPLAY opens a colour wheel at
 * the right of the screen (no dim, the game stays visible): the right stick points at a hue, LEFT / RIGHT step 15
 * degrees, TRIANGLE = the game's own colour (DEFAULT), SQUARE = WHITE; the lightning follows live (at most every
 * 120 ms), X keeps (saved as lightning_hue in the game's own launcher ini, the first PS3_QM_INI file), O restores
 * the colour it had. PS3_LT_TEST_STICK=<deg>,<deg>,..: TEST ONLY, the right stick held at each angle for a second
 * after the wheel opens (the pad script's menu mode carries no stick). */
#include "../font/stb_truetype.h"

extern volatile int      g_pad_overlay_open;
extern volatile uint32_t g_pad_overlay_toggle;
extern volatile uint32_t g_pad_overlay_nav;
extern volatile int      g_pad_ds_features;   /* cellPad.c: DualSense extras (light bar, rumble) */
extern volatile uint32_t g_pad_overlay_nav2;  /* cellPad.c: rx | ry << 8 (rsx lightning: the colour wheel) */
extern volatile int      g_ps3_lt_hue;        /* rsx_lightning.inc: 0..359, -1 DEFAULT, -2 WHITE */
extern volatile unsigned g_ps3_lt_gen;
int ps3_lightning_live(void);

/* CHEATS page (2026-11-14): the game's own list of cheats, switched in game. The game registers it once
 * (game_patches.cpp, qm_cheats_runtime.inc); no list = no CHEATS row. press() runs on the present thread. */
typedef struct {
    int n;
    const char* (*name)(int i);
    int (*state)(int i);            /* 0 off, 1 on, 2 an action (done once when pressed) */
    const char* (*press)(int i);    /* switches it / does it; a short note for the page, or NULL */
    const char* (*saved)(void);     /* "id,id,...": what is on, kept as qm_cheats in the game's own launcher ini */
} ps3_qm_cheats_t;
static const ps3_qm_cheats_t* s_qm_ch;
void ps3_qm_cheats_register(const ps3_qm_cheats_t* t) { s_qm_ch = t && t->n > 0 ? t : NULL; }

typedef struct { stbtt_fontinfo info; uint8_t* data; int ok; float ascent; } qm_font;
enum { QM_ROWS = 6, QM_DIM_ROWS = 4, QM_LT = 4, QM_CH = 5, QM_CH_VIS = 10 };   /* row ids; QM_LT (lightning): PS3_LIGHTNING_LIVE=1 or a colour pack on; QM_CH: a game with cheats */
static struct {
    int on;                        /* -1 unread */
    int open, swallow, row;
    float shown;                   /* 0..1 fade */
    uint32_t toggle_seen, prev_btn; int prev_ly;
    uint64_t last_ns;
    qm_font item, body; int fonts;
    uint8_t* px; u32 w, h, cap, panel_h; float u;
    int dirty; char key[160];      /* what was rastered last: redraw only when this changes */
    vk_image tex; u32 tex_w, tex_h; int tex_ready;
    VkDescriptorPool dpool; VkDescriptorSet ds;
    vk_image old[4]; int old_n;
    int wheel, wh_prev, wh_pend; uint64_t wh_t0, wh_last;   /* rsx lightning: the colour wheel */
    int chpage, ch_row, ch_top; char ch_note[96]; uint64_t hint_until;   /* the CHEATS page; the colour-pack hint */
} s_qm = { .on = -1 };
/* PS3_LIGHTNING_PACK=1 (ps5_app.c: the launcher says a lightning colour pack is on, so the wheel is off): the
 * LIGHTNING row is still shown and says so, instead of being missing without a word (console test 2026-11-14). */
static int qm_lt_pack(void) { static int v = -1; if (v < 0) { const char* e = getenv("PS3_LIGHTNING_PACK"); v = e && *e == '1' && !ps3_lightning_live(); } return v; }
/* The rows on screen and the id of the one at position i: DISPLAY (.. LIGHTNING), CONTROLLER, CHEATS. */
static int qm_rows(int ids[QM_ROWS])
{
    int n = 0;
    ids[n++] = 0; ids[n++] = 1; ids[n++] = 2;
    if (ps3_lightning_live() || qm_lt_pack()) ids[n++] = QM_LT;
    ids[n++] = 3;
    if (s_qm_ch) ids[n++] = QM_CH;
    return n;
}
static int qm_nrows(void) { int ids[QM_ROWS]; return qm_rows(ids); }
static int qm_id(int i) { int ids[QM_ROWS]; const int n = qm_rows(ids); return ids[i >= 0 && i < n ? i : 0]; }
static int qm_ch_on(void) { int c = 0; for (int i = 0; s_qm_ch && i < s_qm_ch->n; i++) c += s_qm_ch->state(i) == 1; return c; }

static void qm_font_load(qm_font* f, const char* path)
{
    FILE* fp = fopen(path, "rb");
    if (!fp) { VK_LOG("quick menu: font %s missing\n", path); return; }
    fseek(fp, 0, SEEK_END); const long n = ftell(fp); fseek(fp, 0, SEEK_SET);
    f->data = (uint8_t*)malloc((size_t)n);
    if (!f->data || fread(f->data, 1, (size_t)n, fp) != (size_t)n) { fclose(fp); free(f->data); f->data = NULL; return; }
    fclose(fp);
    f->ok = stbtt_InitFont(&f->info, f->data, stbtt_GetFontOffsetForIndex(f->data, 0));
    if (f->ok) { int a, d, g; stbtt_GetFontVMetrics(&f->info, &a, &d, &g); f->ascent = (float)a / (float)(a - d); }
}

/* ---- the rows ---- */
static int qm_value(int row)
{
    switch (row) {
    case 0: return s_ovl.mode < 0 ? 0 : s_ovl.mode;
    case 1: return s_fsr.look_mode;
    case 2: return s_fsr.aa;
    case QM_LT: return g_ps3_lt_hue;
    case QM_CH: return qm_ch_on();
    default: return g_pad_ds_features;
    }
}
static int qm_pt(void);   /* (defined below) */
static const char* qm_value_text(int row)
{
    const int v = qm_value(row);
    if (row == 0) return v == 2 ? (qm_pt() ? "DETALHADO" : "DETAILED") : v == 1 ? (qm_pt() ? "SIMPLES" : "SIMPLE") : (qm_pt() ? "DESLIGADO" : "OFF");
    if (row == 1) { static const char* const n[12] = { "ORIGINAL", "REMASTER", "COMIC", "CEL", "BORDERLANDS", "INK NOIR", "SOFT INK",
                                                           "TOON LIGHT", "PAINTERLY", "VINTAGE PRINT", "SKETCH", "HDR POP" };
                    return n[v >= 0 && v < 12 ? v : 0]; }
    if (row == 2) return v == 2 ? "SMAA" : v ? "FXAA" : (qm_pt() ? "DESLIGADO" : "OFF");   /* vk smaa */
    if (row == QM_CH) { static char b[24];
                        if (!v) return qm_pt() ? "ABRIR" : "OPEN";
                        if (qm_pt()) snprintf(b, sizeof b, "%d ATIVA%s", v, v != 1 ? "S" : ""); else snprintf(b, sizeof b, "%d ON", v);
                        return b; }
    if (row == QM_LT && qm_lt_pack()) return qm_pt() ? "PACOTE DE COR" : "COLOUR PACK";
    if (row == QM_LT) { static char b[16];
                        if (v == -2) return qm_pt() ? "BRANCO" : "WHITE";
                        if (v < 0 || v > 359) return qm_pt() ? "PADRÃO" : "DEFAULT";
                        snprintf(b, sizeof b, "%d\xC2\xB0", v); return b; }
    return v ? (qm_pt() ? "LIGADO" : "ON") : (qm_pt() ? "DESLIGADO" : "OFF");
}
static const char* const s_qm_label[QM_ROWS] = { "FPS Counter", "Look", "Anti-Aliasing", "DualSense Features", "Lightning", "Cheats" };
/* The menu in the game's language when it is Portuguese (PS3_LANG pt / br, as the launcher's own pt-BR text). */
static int qm_pt(void) { static int v = -1; if (v < 0) { const char* e = getenv("PS3_LANG"); v = e && (!strncmp(e, "pt", 2) || !strncmp(e, "br", 2)); } return v; }
static const char* const s_qm_label_pt[QM_ROWS] = { "Contador de FPS", "Visual", "Antisserrilhado", "Recursos do DualSense", "Raio", "Trapaças" };
static const char* const s_qm_section_pt[QM_ROWS] = { "TELA", NULL, NULL, "CONTROLE", NULL, "TRAPAÇAS" };
static const char* const s_qm_section[QM_ROWS] = { "DISPLAY", NULL, NULL, "CONTROLLER", NULL, "CHEATS" };
static const char* const s_qm_ini_key[QM_ROWS] = { "fps_counter", "look", "anti_aliasing", "dualsense", "lightning_hue", "qm_cheats" };

/* `key = value` set in each launcher ini (the other lines kept), as MGR's SetMenuValue; first_only: the game's own
 * ini alone (the first PS3_QM_INI file: a per-game value such as the lightning colour) */
static void qm_save_str(const char* key, const char* value, int first_only)
{
    const char* list = getenv("PS3_QM_INI");
    if (!list || !*list) return;
    char paths[512]; snprintf(paths, sizeof paths, "%s", list);
    for (char* p = strtok(paths, ":"); p; p = first_only ? NULL : strtok(NULL, ":")) {
        char* buf = NULL; size_t n = 0;
        FILE* f = fopen(p, "rb");
        if (f) { fseek(f, 0, SEEK_END); const long sz = ftell(f); fseek(f, 0, SEEK_SET);
                 if (sz > 0 && sz < 65536) { buf = (char*)malloc((size_t)sz + 1); n = fread(buf, 1, (size_t)sz, f); buf[n] = 0; }
                 fclose(f); }
        FILE* o = fopen(p, "wb");
        if (!o) { free(buf); continue; }
        int found = 0; const size_t kl = strlen(key);
        for (char* line = buf, *next; line && *line; line = next) {
            next = strchr(line, '\n'); if (next) *next++ = 0;
            const char* t = line; while (*t == ' ') t++;
            if (!strncmp(t, key, kl) && (t[kl] == ' ' || t[kl] == '=')) { fprintf(o, "%s = %s\n", key, value); found = 1; }
            else if (*line) fprintf(o, "%s\n", line);
        }
        if (!found) fprintf(o, "%s = %s\n", key, value);
        fclose(o); free(buf);
    }
}
static void qm_save_to(const char* key, int value, int first_only) { char v[16]; snprintf(v, sizeof v, "%d", value); qm_save_str(key, v, first_only); }
static void qm_save(const char* key, int value) { qm_save_to(key, value, 0); }

/* ---- rsx lightning: the colour wheel ---- */
static float qm_sin_deg(float d)
{
    while (d >= 180.0f) d -= 360.0f;
    while (d < -180.0f) d += 360.0f;
    if (d > 90.0f) d = 180.0f - d;
    if (d < -90.0f) d = -180.0f - d;
    const float x = d * 0.0174532925f, x2 = x * x;
    return x * (1.0f - x2 / 6.0f * (1.0f - x2 / 20.0f * (1.0f - x2 / 42.0f * (1.0f - x2 / 72.0f))));
}
/* The wheel's angle of a direction (dx right, dy down): degrees clockwise from straight up, 0..360 (red at the top). */
static float qm_wheel_deg(float dx, float dy)
{
    const float y = dx, x = -dy, ax = x < 0 ? -x : x, ay = y < 0 ? -y : y;
    if (ax < 1e-9f && ay < 1e-9f) return 0.0f;
    const float a = ax > ay ? ay / ax : ax / ay, s2 = a * a;
    float r = ((-0.0464964749f * s2 + 0.15931422f) * s2 - 0.327622764f) * s2 * a + a;
    if (ay > ax) r = 1.57079637f - r;
    if (x < 0) r = 3.14159274f - r;
    if (y < 0) r = -r;
    float d = r * 57.2957795f;
    if (d < 0.0f) d += 360.0f;
    return d >= 360.0f ? 0.0f : d;
}
static void qm_hsv(float h, float s, float v, uint8_t o[3])
{
    const float hh = h / 60.0f; const int i = (int)hh % 6;
    const float fm2 = hh - 2.0f * (float)(int)(hh * 0.5f), d1 = fm2 - 1.0f;
    const float c = v * s, x = c * (1.0f - (d1 < 0.0f ? -d1 : d1)), m = v - c;
    float r, g, b;
    switch (i) { case 0: r = c; g = x; b = 0; break; case 1: r = x; g = c; b = 0; break; case 2: r = 0; g = c; b = x; break;
                 case 3: r = 0; g = x; b = c; break; case 4: r = x; g = 0; b = c; break; default: r = c; g = 0; b = x; break; }
    o[0] = (uint8_t)((r + m) * 255.0f + 0.5f); o[1] = (uint8_t)((g + m) * 255.0f + 0.5f); o[2] = (uint8_t)((b + m) * 255.0f + 0.5f);
}
/* The colour shown for a wheel value: the hue, white, or (DEFAULT) the game's own lightning blue. */
static void qm_lt_swatch(int v, uint8_t o[3])
{
    if (v >= 0 && v < 360) qm_hsv((float)v, 0.85f, 1.0f, o);
    else if (v == -2) { o[0] = 242; o[1] = 242; o[2] = 242; }
    else { o[0] = 0x38; o[1] = 0xBD; o[2] = 0xFF; }
}
static void qm_lt_set(int v)
{
    if (__atomic_load_n(&g_ps3_lt_hue, __ATOMIC_ACQUIRE) == v) return;
    __atomic_store_n(&g_ps3_lt_hue, v, __ATOMIC_RELEASE);
    __atomic_add_fetch(&g_ps3_lt_gen, 1u, __ATOMIC_ACQ_REL);
    VK_LOG("quick menu: lightning -> %d\n", v);
}
/* One present of the open wheel: `pressed` = the buttons that went down. Returns 1 when it closed. */
static int qm_wheel_step(uint32_t pressed, uint64_t now)
{
    if (pressed & 0x2000u) { qm_lt_set(s_qm.wh_prev); VK_LOG("quick menu: lightning wheel cancelled\n"); return 1; }   /* O */
    if (pressed & 0x4000u) {                                                                                    /* X */
        qm_lt_set(s_qm.wh_pend); qm_save_to(s_qm_ini_key[QM_LT], s_qm.wh_pend, 1);
        VK_LOG("quick menu: lightning kept %d\n", s_qm.wh_pend); return 1; }
    if (pressed & 0x1000u) s_qm.wh_pend = -1;                                                                   /* TRIANGLE: DEFAULT */
    if (pressed & 0x8000u) s_qm.wh_pend = -2;                                                                   /* SQUARE: WHITE */
    const int base = s_qm.wh_pend >= 0 ? s_qm.wh_pend : 0;
    if (pressed & 0x80u) s_qm.wh_pend = (base / 15 * 15 + 345) % 360;                                          /* LEFT */
    if (pressed & 0x20u) s_qm.wh_pend = (base / 15 * 15 + 15) % 360;                                           /* RIGHT */
    const uint32_t n2 = g_pad_overlay_nav2;
    float dx = (float)(int)(n2 & 0xFFu) - 128.0f, dy = (float)(int)((n2 >> 8) & 0xFFu) - 128.0f;
    {   static int tn = -1; static float ta[32];   /* PS3_LT_TEST_STICK (test only) */
        if (tn < 0) { tn = 0; const char* e = getenv("PS3_LT_TEST_STICK");
                      for (const char* q = e; q && *q && tn < 32; ) { ta[tn++] = (float)atof(q); q = strchr(q, ','); if (q) q++; } }
        const uint64_t k = (now - s_qm.wh_t0) / 1000000000ull;
        if (tn && k < (uint64_t)tn) { dx = 127.0f * qm_sin_deg(ta[k]); dy = -127.0f * qm_sin_deg(ta[k] + 90.0f); } }
    if (dx * dx + dy * dy > 70.0f * 70.0f) { int d = (int)(qm_wheel_deg(dx, dy) + 0.5f); s_qm.wh_pend = d >= 360 ? 0 : d; }
    if (s_qm.wh_pend != g_ps3_lt_hue && now - s_qm.wh_last >= 120000000ull) { qm_lt_set(s_qm.wh_pend); s_qm.wh_last = now; }
    return 0;
}

/* One present of the open CHEATS page. Returns 1 when it went back to the menu. */
static int qm_cheats_step(uint32_t pressed)
{
    const int n = s_qm_ch ? s_qm_ch->n : 0;
    if (!n || (pressed & 0x2000u)) return 1;                                         /* O: back */
    if (pressed & 0x10u) s_qm.ch_row = (s_qm.ch_row + n - 1) % n;                    /* up */
    if (pressed & 0x40u) s_qm.ch_row = (s_qm.ch_row + 1) % n;                        /* down */
    if (s_qm.ch_row < s_qm.ch_top) s_qm.ch_top = s_qm.ch_row;
    if (s_qm.ch_row >= s_qm.ch_top + QM_CH_VIS) s_qm.ch_top = s_qm.ch_row - QM_CH_VIS + 1;
    if (pressed & (0x20u | 0x80u | 0x4000u)) {                                       /* left, right, X */
        const char* note = s_qm_ch->press(s_qm.ch_row);
        snprintf(s_qm.ch_note, sizeof s_qm.ch_note, "%s", note ? note : "");
        qm_save_str(s_qm_ini_key[QM_CH], s_qm_ch->saved(), 1);
        VK_LOG("quick menu: cheat %s -> %d%s%s\n", s_qm_ch->name(s_qm.ch_row), s_qm_ch->state(s_qm.ch_row), note ? ": " : "", note ? note : "");
    }
    return 0;
}

static void qm_change(int row, int back)
{
    int v = qm_value(row);
    if (row == QM_CH) {   /* the CHEATS page */
        if (!s_qm_ch) return;
        s_qm.chpage = 1; s_qm.ch_note[0] = 0;
        if (s_qm.ch_row >= s_qm_ch->n) s_qm.ch_row = 0;
        VK_LOG("quick menu: cheats page open (%d listed, %d on)\n", s_qm_ch->n, v); return; }
    if (row == QM_LT && qm_lt_pack()) {   /* a colour pack is on: say where to turn it off */
        s_qm.hint_until = ps3_ft_now() + 8000000000ull;
        VK_LOG("quick menu: lightning: a colour pack is on (hint shown)\n"); return; }
    if (row == QM_LT) {   /* rsx lightning: the wheel opens on the colour in use */
        s_qm.wheel = 1; s_qm.wh_prev = s_qm.wh_pend = v; s_qm.wh_t0 = s_qm.wh_last = ps3_ft_now();
        VK_LOG("quick menu: lightning wheel open (%d)\n", v); return; }
    switch (row) {
    case 0: v = (v + (back ? 2 : 1)) % 3; s_ovl.mode = v; break;
    case 1: v = (v + (back ? 11 : 1)) % 12; s_fsr.look_mode = v; break;   /* vk looks: 12 */
    case 2: v = (v + (back ? 2 : 1)) % 3; s_fsr.aa = v; break;   /* vk smaa: OFF / FXAA / SMAA */
    default: v = !v; g_pad_ds_features = v; break;
    }
    qm_save(s_qm_ini_key[row], v);
    VK_LOG("quick menu: %s -> %s\n", s_qm_label[row], qm_value_text(row));
}

/* One step a present: the combo, the navigation and the fade. Returns whether anything is to be drawn. */
/* Notices (2026-11-09): "TROPHY UNLOCKED <name>" (sceNpTrophy calls ps3_overlay_notice), a small panel at the top right
 * for 5 s, drawn with the quick menu's texture when the menu is closed. */
static char s_qmn_text[200]; static volatile uint64_t s_qmn_until; static int s_qm_mode;   /* 0 the menu, 1 a notice */
void ps3_overlay_notice(const char* text)
{
    if (!text) return;
    snprintf(s_qmn_text, sizeof s_qmn_text, "%s", text);
    __atomic_store_n(&s_qmn_until, ps3_ft_now() + 5000000000ull, __ATOMIC_RELEASE);
    VK_LOG("notice: %s\n", text);
}
static int vk_qm_update_menu(void);
static int vk_qm_update(void)
{
    { static int t = -1; static uint64_t t0;   /* PS3_TEST_NOTICE=1: one sample notice ~20 s in (BC-250 check) */
      if (t < 0) { const char* e = getenv("PS3_TEST_NOTICE"); t = e && *e == '1'; t0 = ps3_ft_now(); }
      if (t == 1 && ps3_ft_now() - t0 > 20000000000ull) { t = 2; ps3_overlay_notice("Trophy unlocked: Fight the Good Fight"); } }
    const int menu = vk_qm_update_menu();
    if (menu) { s_qm_mode = 0; return 1; }
    if (ps3_ft_now() < __atomic_load_n(&s_qmn_until, __ATOMIC_ACQUIRE)) { s_qm_mode = 1; return 1; }
    s_qm_mode = 0; return 0;
}
static int vk_qm_update_menu(void)
{
    if (s_qm.on < 0) {
        const char* e = getenv("PS3_QUICK_MENU"); s_qm.on = !(e && *e == '0');
        s_qm.toggle_seen = __atomic_load_n(&g_pad_overlay_toggle, __ATOMIC_ACQUIRE);
    }
    if (!s_qm.on) return 0;
    const uint64_t now = ps3_ft_now();
    float dt = s_qm.last_ns ? (float)((double)(now - s_qm.last_ns) / 1e9) : 0.0f;
    if (dt > 0.1f) dt = 0.1f;
    s_qm.last_ns = now;
    const uint32_t tg = __atomic_load_n(&g_pad_overlay_toggle, __ATOMIC_ACQUIRE);
    const uint32_t nav = g_pad_overlay_nav;
    uint32_t btn = nav & 0xFFFFu;
    const int ly = (int)((nav >> 24) & 0xFFu);
    if (ly < 64) btn |= 0x10u;          /* the left stick as the d-pad */
    if (ly > 192) btn |= 0x40u;
    const uint32_t pressed = btn & ~s_qm.prev_btn;
    s_qm.prev_btn = btn;
    if (tg != s_qm.toggle_seen) {
        s_qm.toggle_seen = tg;
        if (s_qm.open && s_qm.wheel) { qm_lt_set(s_qm.wh_pend); qm_save_to(s_qm_ini_key[QM_LT], s_qm.wh_pend, 1); s_qm.wheel = 0; }   /* rsx lightning: closed = kept */
        s_qm.chpage = 0; s_qm.hint_until = 0;
        s_qm.open = !s_qm.open;
        if (s_qm.open) { g_pad_overlay_open = 1; s_qm.swallow = 0; VK_LOG("quick menu: open\n"); }
        else s_qm.swallow = 1;
    } else if (s_qm.open && s_qm.wheel) {                                            /* rsx lightning: the colour wheel */
        if (qm_wheel_step(pressed, now)) s_qm.wheel = 0;
    } else if (s_qm.open && s_qm.chpage) {                                           /* the CHEATS page */
        if (qm_cheats_step(pressed)) s_qm.chpage = 0;
    } else if (s_qm.open) {
        const int nr = qm_nrows();
        if (s_qm.row >= nr) s_qm.row = 0;
        if (pressed & 0x2000u) { s_qm.open = 0; s_qm.swallow = 1; }                  /* O */
        else {
            if (pressed & 0x10u) s_qm.row = (s_qm.row + nr - 1) % nr;                /* up */
            if (pressed & 0x40u) s_qm.row = (s_qm.row + 1) % nr;                     /* down */
            if (pressed & 0x80u) qm_change(qm_id(s_qm.row), 1);                     /* left */
            if (pressed & (0x20u | 0x4000u)) qm_change(qm_id(s_qm.row), 0);         /* right, X */
        }
    }
    if (!s_qm.open && s_qm.swallow && !(btn & ~0x6u)) { s_qm.swallow = 0; }
    g_pad_overlay_open = s_qm.open || s_qm.swallow;
    const float target = s_qm.open ? 1.0f : 0.0f;
    if (s_qm.shown < target) { s_qm.shown += dt * 8.0f; if (s_qm.shown > 1.0f) s_qm.shown = 1.0f; }
    if (s_qm.shown > target) { s_qm.shown -= dt * 8.0f; if (s_qm.shown < 0.0f) s_qm.shown = 0.0f; }
    return s_qm.shown > 0.0f;
}

/* ---- the raster (output pixels) ---- */
static void qm_fill(float x0, float y0, float x1, float y1, const uint8_t c[4], float r, int left_only)
{
    uint8_t* save = s_ovl.px; const u32 sw = s_ovl.w, sh = s_ovl.h;
    s_ovl.px = s_qm.px; s_ovl.w = s_qm.w; s_ovl.h = s_qm.h;
    if (!left_only) ovl_rect(x0, y0, x1, y1, c, r);
    else { ovl_rect(x0, y0, x1 + r, y1, c, r); }   /* (the bar: rounded on the left, the panel covers its right) */
    s_ovl.px = save; s_ovl.w = sw; s_ovl.h = sh;
}
static float qm_text(qm_font* f, float px_h, float x, float top, const char* t, const uint8_t c[4], int measure_only)
{
    if (!f->ok) return 0.0f;
    const float sc = stbtt_ScaleForPixelHeight(&f->info, px_h);
    const float base = top + f->ascent * px_h;
    float pen = x;
    for (const char* s = t; *s; s++) {
        int adv, lsb; int cp = (uint8_t)*s;
        if (cp >= 0xC0 && cp < 0xE0 && (s[1] & 0xC0) == 0x80) { cp = ((cp & 0x1F) << 6) | (s[1] & 0x3F); s++; }   /* UTF-8 (pt-BR accents) */
        else if (cp >= 0xE0 && cp < 0xF0 && (s[1] & 0xC0) == 0x80 && (s[2] & 0xC0) == 0x80) { cp = ((cp & 0x0F) << 12) | ((s[1] & 0x3F) << 6) | (s[2] & 0x3F); s += 2; }
        stbtt_GetCodepointHMetrics(&f->info, cp, &adv, &lsb);
        if (!measure_only) {
            int gw, gh, xo, yo;
            uint8_t* bm = stbtt_GetCodepointBitmap(&f->info, sc, sc, cp, &gw, &gh, &xo, &yo);
            if (bm) {
                const int gx = (int)(pen + 0.5f) + xo, gy = (int)(base + 0.5f) + yo;
                for (int yy = 0; yy < gh; yy++) {
                    const int py = gy + yy; if (py < 0 || py >= (int)s_qm.h) continue;
                    for (int xx = 0; xx < gw; xx++) {
                        const int px = gx + xx; if (px < 0 || px >= (int)s_qm.w) continue;
                        ovl_blend(s_qm.px + ((size_t)py * s_qm.w + px) * 4u, c, bm[yy * gw + xx]);
                    }
                }
                stbtt_FreeBitmap(bm, NULL);
            }
        }
        pen += (float)adv * sc;
        if (s[1]) pen += (float)stbtt_GetCodepointKernAdvance(&f->info, cp, (uint8_t)s[1]) * sc;
    }
    return pen - x;
}
/* rsx lightning: the colour wheel's panel (drawn at the right of the screen, no dim). The ring is rastered once a size. */
static uint8_t* s_qmw_ring; static u32 s_qmw_ring_d; static float s_qmw_ring_u;
static int qm_wheel_raster(float a, float u)
{
    const int pend = s_qm.wh_pend;
    char key[160]; snprintf(key, sizeof key, "W %d %.3f %.3f", pend, (double)a, (double)u);
    if (s_qm.px && !strcmp(key, s_qm.key)) return 1;
    snprintf(s_qm.key, sizeof s_qm.key, "%s", key);
    const float w = 560 * u, h = 690 * u, rout = 200 * u, rin = 146 * u, cx = w * 0.5f + 4 * u, cy = 112 * u + rout;
    s_qm.w = (u32)(w + 0.999f); s_qm.panel_h = (u32)(h + 0.999f); s_qm.h = s_qm.panel_h + QM_DIM_ROWS; s_qm.u = u;
    const u32 need = s_qm.w * s_qm.h * 4u;
    if (need > s_qm.cap) { free(s_qm.px); s_qm.cap = need + 4096u; s_qm.px = (uint8_t*)malloc(s_qm.cap); if (!s_qm.px) { s_qm.cap = 0; return 0; } }
    memset(s_qm.px, 0, (size_t)need);   /* (the dim rows stay clear: no dim under the wheel) */
#define QMC(r, g, b, al) { r, g, b, (uint8_t)((float)(al) * a) }
    const uint8_t panel[4] = QMC(8, 8, 10, 225), acc[4] = QMC(0x38, 0xBD, 0xFF, 255), white[4] = QMC(236, 232, 226, 255),
                  grey[4] = QMC(150, 146, 140, 255);
#undef QMC
    qm_fill(0, 0, w, h, panel, 10 * u, 0);
    {   const u32 bw = (u32)(8 * u + 0.5f);   /* the accent bar, as the menu's */
        for (u32 yy = 0; yy < s_qm.panel_h; yy++)
            for (u32 xx = 0; xx < bw && xx < s_qm.w; xx++) {
                uint8_t* d = s_qm.px + ((size_t)yy * s_qm.w + xx) * 4u;
                if (d[3]) { d[0] = acc[0]; d[1] = acc[1]; d[2] = acc[2]; } } }
    qm_text(&s_qm.item, 40 * u, 40 * u, 26 * u, qm_pt() ? "COR DO RAIO" : "LIGHTNING", white, 0);
    /* the ring: hue clockwise from the top, as the right stick points */
    const u32 d = (u32)(2.0f * rout + 4.0f);
    if (!s_qmw_ring || s_qmw_ring_d != d || s_qmw_ring_u != u) {
        free(s_qmw_ring); s_qmw_ring = (uint8_t*)malloc((size_t)d * d * 4u); s_qmw_ring_d = d; s_qmw_ring_u = u;
        if (s_qmw_ring) {
            const float c = (float)d * 0.5f;
            for (u32 yy = 0; yy < d; yy++)
                for (u32 xx = 0; xx < d; xx++) {
                    uint8_t* q = s_qmw_ring + ((size_t)yy * d + xx) * 4u;
                    const float dx = (float)xx + 0.5f - c, dy = (float)yy + 0.5f - c, r = sqrtf(dx * dx + dy * dy);
                    float cov = (r - rin < rout - r ? r - rin : rout - r) + 0.5f;
                    cov = cov < 0.0f ? 0.0f : cov > 1.0f ? 1.0f : cov;
                    if (cov <= 0.0f) { q[3] = 0; continue; }
                    qm_hsv(qm_wheel_deg(dx, dy), 0.85f, 1.0f, q); q[3] = (uint8_t)(cov * 255.0f);
                } } }
    if (s_qmw_ring) {
        const int ox = (int)(cx - (float)d * 0.5f), oy = (int)(cy - (float)d * 0.5f);
        for (u32 yy = 0; yy < d; yy++) {
            const int py = oy + (int)yy; if (py < 0 || py >= (int)s_qm.panel_h) continue;
            for (u32 xx = 0; xx < d; xx++) {
                const int px = ox + (int)xx; if (px < 0 || px >= (int)s_qm.w) continue;
                const uint8_t* q = s_qmw_ring + ((size_t)yy * d + xx) * 4u;
                if (!q[3]) continue;
                const uint8_t c4[4] = { q[0], q[1], q[2], (uint8_t)(255.0f * a) };
                ovl_blend(s_qm.px + ((size_t)py * s_qm.w + px) * 4u, c4, q[3]);
            } } }
    /* the centre: the colour chosen (DEFAULT: the game's own blue) */
    uint8_t sw[4]; qm_lt_swatch(pend, sw); sw[3] = (uint8_t)(255.0f * a);
    const float rc = 96 * u;
    qm_fill(cx - rc, cy - rc, cx + rc, cy + rc, sw, rc, 0);
    if (pend >= 0 && pend < 360) {   /* the marker on the ring */
        const float rm = (rin + rout) * 0.5f, mx = cx + rm * qm_sin_deg((float)pend), my = cy - rm * qm_sin_deg((float)pend + 90.0f);
        const uint8_t ring_w[4] = { 255, 255, 255, (uint8_t)(255.0f * a) }, ring_k[4] = { 0, 0, 0, (uint8_t)(200.0f * a) };
        qm_fill(mx - 32 * u, my - 32 * u, mx + 32 * u, my + 32 * u, ring_k, 32 * u, 0);
        qm_fill(mx - 29 * u, my - 29 * u, mx + 29 * u, my + 29 * u, ring_w, 29 * u, 0);
        qm_fill(mx - 23 * u, my - 23 * u, mx + 23 * u, my + 23 * u, sw, 23 * u, 0);
    }
    char v[32];
    if (pend == -2) snprintf(v, sizeof v, "%s", qm_pt() ? "BRANCO" : "WHITE");
    else if (pend < 0 || pend > 359) snprintf(v, sizeof v, "%s", qm_pt() ? "PADRÃO" : "DEFAULT");
    else snprintf(v, sizeof v, "%d\xC2\xB0", pend);
    const float vw = qm_text(&s_qm.item, 34 * u, 0, 0, v, white, 1);
    qm_text(&s_qm.item, 34 * u, cx - vw * 0.5f, cy + rout + 22 * u, v, white, 0);
    const char* l1 = qm_pt() ? "ANALÓGICO DIR. / ESQ. DIR.  COR" : "RIGHT STICK / LEFT RIGHT  COLOUR";
    const char* l2 = qm_pt() ? "X MANTER    O CANCELAR" : "X KEEP    O CANCEL";
    const char* l3 = qm_pt() ? "TRIÂNGULO PADRÃO    QUADRADO BRANCO" : "TRIANGLE DEFAULT    SQUARE WHITE";
    qm_text(&s_qm.body, 19 * u, 40 * u, h - 112 * u, l1, grey, 0);
    qm_text(&s_qm.body, 19 * u, 40 * u, h - 82 * u, l2, grey, 0);
    qm_text(&s_qm.body, 19 * u, 40 * u, h - 52 * u, l3, grey, 0);
    s_qm.dirty = 1;
    {   const char* dp = getenv("PS3_QM_DUMP"); static unsigned wn;   /* (debug, as the menu's) */
        if (dp && *dp && wn < 64) { char path[512]; snprintf(path, sizeof path, "%s.wheel%02u.ppm", dp, wn++);
            FILE* f = fopen(path, "wb");
            if (f) { fprintf(f, "P6\n%u %u\n255\n", s_qm.w, s_qm.panel_h);
                     for (u32 i = 0; i < s_qm.w * s_qm.panel_h; i++) { const uint8_t* q = s_qm.px + i * 4u; const uint8_t c[3] = {
                         (uint8_t)(q[0] * q[3] / 255u + 40u * (255u - q[3]) / 255u), (uint8_t)(q[1] * q[3] / 255u + 90u * (255u - q[3]) / 255u),
                         (uint8_t)(q[2] * q[3] / 255u + 60u * (255u - q[3]) / 255u) }; fwrite(c, 1, 3, f); }
                     fclose(f); } } }
    return 1;
}
/* The CHEATS page: the menu's panel with the game's list (QM_CH_VIS rows in view), ON / OFF / APPLY at the right. */
static int qm_cheats_raster(float a, float u)
{
    const int n = s_qm_ch ? s_qm_ch->n : 0;
    char key[160]; unsigned st = 0;
    for (int i = 0; i < n; i++) st = st * 3u + (unsigned)s_qm_ch->state(i);
    snprintf(key, sizeof key, "C %d %d %u %.3f %.3f %.60s", s_qm.ch_row, s_qm.ch_top, st, (double)a, (double)u, s_qm.ch_note);
    if (s_qm.px && !strcmp(key, s_qm.key)) return 1;
    snprintf(s_qm.key, sizeof s_qm.key, "%s", key);
    const int vis = n < QM_CH_VIS ? n : QM_CH_VIS;
    const float row_h = 40 * u, w = 760 * u, h = 142 * u + vis * row_h + 104 * u;
    s_qm.w = (u32)(w + 0.999f); s_qm.panel_h = (u32)(h + 0.999f); s_qm.h = s_qm.panel_h + QM_DIM_ROWS; s_qm.u = u;
    const u32 need = s_qm.w * s_qm.h * 4u;
    if (need > s_qm.cap) { free(s_qm.px); s_qm.cap = need + 4096u; s_qm.px = (uint8_t*)malloc(s_qm.cap); if (!s_qm.px) { s_qm.cap = 0; return 0; } }
    memset(s_qm.px, 0, (size_t)need);
#define QMC(r, g, b, al) { r, g, b, (uint8_t)((float)(al) * a) }
    const uint8_t panel[4] = QMC(8, 8, 10, 235), acc[4] = QMC(0x38, 0xBD, 0xFF, 255), white[4] = QMC(236, 232, 226, 255),
                  grey[4] = QMC(150, 146, 140, 255), band[4] = QMC(0x38, 0xBD, 0xFF, 50), line[4] = QMC(255, 255, 255, 40),
                  dim[4] = QMC(0, 0, 0, 110);
#undef QMC
    qm_fill(0, 0, w, h, panel, 10 * u, 0);
    {   const u32 bw = (u32)(8 * u + 0.5f);   /* the accent bar, as the menu's */
        for (u32 yy = 0; yy < s_qm.panel_h; yy++)
            for (u32 xx = 0; xx < bw && xx < s_qm.w; xx++) {
                uint8_t* d = s_qm.px + ((size_t)yy * s_qm.w + xx) * 4u;
                if (d[3]) { d[0] = acc[0]; d[1] = acc[1]; d[2] = acc[2]; } } }
    qm_text(&s_qm.item, 46 * u, 40 * u, 26 * u, qm_pt() ? "TRAPAÇAS" : "CHEATS", white, 0);
    {   char c[24]; snprintf(c, sizeof c, "%d / %d", s_qm.ch_row + 1, n);
        const float cw = qm_text(&s_qm.body, 20 * u, 0, 0, c, grey, 1);
        qm_text(&s_qm.body, 20 * u, w - 40 * u - cw, 44 * u, c, grey, 0); }
    qm_text(&s_qm.body, 18 * u, 40 * u, 88 * u, qm_pt() ? "Podem estragar o progresso: use um save reserva." : "These can break progress: use a spare save.", grey, 0);
    qm_fill(40 * u, 122 * u, w - 40 * u, 123 * u, line, 0, 0);
    float y = 134 * u;
    for (int r = 0; r < vis; r++) {
        const int i = s_qm.ch_top + r; if (i >= n) break;
        const int sel = i == s_qm.ch_row, stt = s_qm_ch->state(i);
        if (sel) qm_fill(24 * u, y + 2 * u, w - 24 * u, y + row_h - 2 * u, band, 4 * u, 0);
        qm_text(&s_qm.item, 28 * u, 40 * u, y + 5 * u, s_qm_ch->name(i), sel || stt == 1 ? white : grey, 0);
        const char* v = stt == 2 ? (qm_pt() ? "APLICAR" : "APPLY") : stt ? (qm_pt() ? "LIGADO" : "ON") : (qm_pt() ? "DESLIGADO" : "OFF");
        const float vw = qm_text(&s_qm.item, 28 * u, 0, 0, v, grey, 1);
        qm_text(&s_qm.item, 28 * u, w - 40 * u - vw, y + 5 * u, v, stt == 1 ? acc : sel ? white : grey, 0);
        y += row_h;
    }
    if (s_qm.ch_top > 0) qm_text(&s_qm.body, 18 * u, w * 0.5f - 8 * u, 124 * u - 2 * u, "^", grey, 0);
    if (s_qm.ch_top + vis < n) qm_text(&s_qm.body, 18 * u, w * 0.5f - 8 * u, y - 2 * u, "v", grey, 0);
    if (s_qm.ch_note[0]) qm_text(&s_qm.body, 20 * u, 40 * u, h - 80 * u, s_qm.ch_note, acc, 0);
    qm_text(&s_qm.body, 20 * u, 40 * u, h - 46 * u, qm_pt() ? "CIMA BAIXO  MOVER      X  LIGAR / DESLIGAR      O  VOLTAR" : "UP DOWN  MOVE      X  ON / OFF      O  BACK", grey, 0);
    for (u32 yy = s_qm.panel_h; yy < s_qm.h; yy++)
        for (u32 xx = 0; xx < s_qm.w; xx++) memcpy(s_qm.px + ((size_t)yy * s_qm.w + xx) * 4u, dim, 4);
    s_qm.dirty = 1;
    {   const char* dp = getenv("PS3_QM_DUMP"); static unsigned cn;   /* (debug, as the menu's) */
        if (dp && *dp && cn < 64) { char path[512]; snprintf(path, sizeof path, "%s.cheats%02u.ppm", dp, cn++);
            FILE* f = fopen(path, "wb");
            if (f) { fprintf(f, "P6\n%u %u\n255\n", s_qm.w, s_qm.panel_h);
                     for (u32 i = 0; i < s_qm.w * s_qm.panel_h; i++) { const uint8_t* q = s_qm.px + i * 4u; const uint8_t c[3] = {
                         (uint8_t)(q[0] * q[3] / 255u + 40u * (255u - q[3]) / 255u), (uint8_t)(q[1] * q[3] / 255u + 90u * (255u - q[3]) / 255u),
                         (uint8_t)(q[2] * q[3] / 255u + 60u * (255u - q[3]) / 255u) }; fwrite(c, 1, 3, f); }
                     fclose(f); } } }
    return 1;
}
static int vk_qm_raster(void)
{
    if (!s_qm.fonts) {   /* PS3_QM_FONTS: another folder with font_item.ttf / font_body.ttf (BC-250 tests) */
        const char* d = getenv("PS3_QM_FONTS"); if (!d || !*d) d = "/app0/launcher";
        char p[512]; snprintf(p, sizeof p, "%s/font_item.ttf", d); qm_font_load(&s_qm.item, p);
        snprintf(p, sizeof p, "%s/font_body.ttf", d); qm_font_load(&s_qm.body, p);
        s_qm.fonts = 1; }
    const float W = (float)s_vk.sc_extent.width, H = (float)s_vk.sc_extent.height;
    const float u = W / 1920.0f < H / 1080.0f ? W / 1920.0f : H / 1080.0f;
    if (s_qm_mode == 1) {   /* a notice */
        { static int lg; if (!lg++) VK_LOG("notice: raster %ux%u\n", (unsigned)W, (unsigned)H); }
        const uint64_t left = __atomic_load_n(&s_qmn_until, __ATOMIC_ACQUIRE) - ps3_ft_now();
        const float a = left > 4600000000ull ? (float)(5000000000ull - left) / 4e8f : left < 400000000ull ? (float)left / 4e8f : 1.0f;
        char key[260]; snprintf(key, sizeof key, "N %s %.2f %.3f", s_qmn_text, (double)a, (double)u);
        if (s_qm.px && !strcmp(key, s_qm.key)) return 1;
        snprintf(s_qm.key, sizeof s_qm.key, "%s", key);
        const float w = 680 * u, h = 112 * u;
        s_qm.w = (u32)(w + 0.999f); s_qm.panel_h = (u32)(h + 0.999f); s_qm.h = s_qm.panel_h + QM_DIM_ROWS; s_qm.u = u;
        const u32 need = s_qm.w * s_qm.h * 4u;
        if (need > s_qm.cap) { free(s_qm.px); s_qm.cap = need + 4096u; s_qm.px = (uint8_t*)malloc(s_qm.cap); if (!s_qm.px) { s_qm.cap = 0; return 0; } }
        memset(s_qm.px, 0, (size_t)need);
        const uint8_t panel[4] = { 8, 8, 10, (uint8_t)(235 * a) }, acc[4] = { 0x38, 0xBD, 0xFF, (uint8_t)(255 * a) }, white[4] = { 236, 232, 226, (uint8_t)(255 * a) };
        qm_fill(0, 0, w, h, panel, 10 * u, 0);
        qm_fill(0, 0, 8 * u, h, acc, 0, 1);
        qm_text(&s_qm.body, 20 * u, 30 * u, 18 * u, qm_pt() ? "TROFÉU DESBLOQUEADO" : "TROPHY UNLOCKED", acc, 0);
        const char* t = s_qmn_text; if (!strncmp(t, "Trophy unlocked: ", 17)) t += 17;
        qm_text(&s_qm.item, 32 * u, 30 * u, 52 * u, t, white, 0);
        s_qm.dirty = 1;
        { const char* dp = getenv("PS3_QM_DUMP"); static unsigned nn;   /* (debug, as below) */
          if (dp && *dp && nn < 8) { char path[512]; snprintf(path, sizeof path, "%s.notice%u.ppm", dp, nn++);
              FILE* f = fopen(path, "wb");
              if (f) { fprintf(f, "P6\n%u %u\n255\n", s_qm.w, s_qm.panel_h);
                       for (u32 i = 0; i < s_qm.w * s_qm.panel_h; i++) { const uint8_t* q = s_qm.px + i * 4u; fputc(q[0] * q[3] / 255, f); fputc(q[1] * q[3] / 255, f); fputc(q[2] * q[3] / 255, f); }
                       fclose(f); } } }
        return 1;
    }
    const float a = s_qm.shown;
    if (s_qm.wheel) return qm_wheel_raster(a, u);   /* rsx lightning */
    if (s_qm.chpage) return qm_cheats_raster(a, u);
    const int hint = ps3_ft_now() < s_qm.hint_until;   /* the colour-pack hint, in the footer's place */
    char key[160]; snprintf(key, sizeof key, "%d %d %d %d %d %d %.3f %.3f %d %d %d %d", s_qm.row, qm_value(0), qm_value(1), qm_value(2), qm_value(3),
                            s_qm.open, (double)a, (double)u, ps3_lightning_live() ? qm_value(QM_LT) : 0, qm_nrows(), s_qm_ch ? qm_value(QM_CH) : 0, hint);
    if (s_qm.px && !strcmp(key, s_qm.key)) return 1;   /* nothing changed */
    snprintf(s_qm.key, sizeof s_qm.key, "%s", key);
    const int nrows = qm_nrows();
    int heads = 0; for (int i = 0; i < nrows; i++) heads += s_qm_section[qm_id(i)] ? 1 : 0;
    const float row_h = 40 * u, head_h = 44 * u, w = 760 * u;
    const float h = 110 * u + nrows * row_h + heads * head_h + 70 * u;
    s_qm.w = (u32)(w + 0.999f); s_qm.panel_h = (u32)(h + 0.999f); s_qm.h = s_qm.panel_h + QM_DIM_ROWS; s_qm.u = u;
    const u32 need = s_qm.w * s_qm.h * 4u;
    if (need > s_qm.cap) { free(s_qm.px); s_qm.cap = need + 4096u; s_qm.px = (uint8_t*)malloc(s_qm.cap); if (!s_qm.px) { s_qm.cap = 0; return 0; } }
    memset(s_qm.px, 0, (size_t)need);
#define QMC(r, g, b, al) { r, g, b, (uint8_t)((float)(al) * a) }
    const uint8_t panel[4] = QMC(8, 8, 10, 235), red[4] = QMC(0x38, 0xBD, 0xFF, 255)   /* inFAMOUS: Cole's lightning blue (launcher C_ACCENT), was MGR's red */, white[4] = QMC(236, 232, 226, 255),
                  grey[4] = QMC(150, 146, 140, 255), band[4] = QMC(0x38, 0xBD, 0xFF, 50), line[4] = QMC(255, 255, 255, 40),
                  dim[4] = QMC(0, 0, 0, 110);
    qm_fill(0, 0, w, h, panel, 10 * u, 0);
    {   /* the red bar: the panel's own left 8 units recoloured, so it keeps the panel's rounded corners */
        const u32 bw = (u32)(8 * u + 0.5f);
        for (u32 yy = 0; yy < s_qm.panel_h && yy < s_qm.h; yy++)
            for (u32 xx = 0; xx < bw && xx < s_qm.w; xx++) {
                uint8_t* d = s_qm.px + ((size_t)yy * s_qm.w + xx) * 4u;
                if (d[3]) { d[0] = red[0]; d[1] = red[1]; d[2] = red[2]; d[3] = (uint8_t)((u32)d[3] * 255u / 235u > 255u ? 255u : (u32)d[3] * 255u / 235u); }
            }
    }
    qm_text(&s_qm.item, 46 * u, 40 * u, 26 * u, qm_pt() ? "MENU RÁPIDO" : "QUICK MENU", white, 0);
    float y = 100 * u;
    for (int ri = 0; ri < nrows; ri++) {
        const int i = qm_id(ri);
        if (s_qm_section[i]) {
            y += 10 * u;
            qm_text(&s_qm.body, 20 * u, 40 * u, y, qm_pt() ? s_qm_section_pt[i] : s_qm_section[i], red, 0);
            qm_fill(40 * u, y + 28 * u, w - 40 * u, y + 29 * u, line, 0, 0);
            y += head_h - 10 * u;
        }
        const int sel = ri == s_qm.row;
        if (sel) qm_fill(24 * u, y + 2 * u, w - 24 * u, y + row_h - 2 * u, band, 4 * u, 0);
        qm_text(&s_qm.item, 28 * u, 40 * u, y + 5 * u, qm_pt() ? s_qm_label_pt[i] : s_qm_label[i], sel ? white : grey, 0);
        char v[64]; snprintf(v, sizeof v, sel ? "<  %s  >" : "%s", qm_value_text(i));
        const float vw = qm_text(&s_qm.item, 28 * u, 0, 0, v, grey, 1);
        qm_text(&s_qm.item, 28 * u, w - 40 * u - vw, y + 5 * u, v, sel ? red : grey, 0);
        if (i == QM_LT && !qm_lt_pack()) {   /* rsx lightning: a swatch of the colour left of its value */
            uint8_t sw[4]; qm_lt_swatch(qm_value(QM_LT), sw); sw[3] = (uint8_t)(255.0f * a);
            qm_fill(w - 40 * u - vw - 36 * u, y + 10 * u, w - 40 * u - vw - 14 * u, y + row_h - 10 * u, sw, 4 * u, 0); }
        y += row_h;
    }
    if (hint) {
        qm_text(&s_qm.body, 19 * u, 40 * u, h - 62 * u, qm_pt() ? "Um mod de textura do raio está ligado: a roda fica desligada." : "A lightning texture mod is on, so the wheel is off.", red, 0);
        qm_text(&s_qm.body, 19 * u, 40 * u, h - 36 * u, qm_pt() ? "No launcher: MODS > COR DOS RAIOS, escolha PADRÃO ou uma cor simples." : "In the launcher: MODS > LIGHTNING COLOUR, pick DEFAULT or a plain colour.", grey, 0);
    } else
    qm_text(&s_qm.body, 20 * u, 40 * u, h - 46 * u, qm_pt() ? "CIMA BAIXO  MOVER      ESQ DIR / X  MUDAR      O / L3+R3  FECHAR" : "UP DOWN  MOVE      LEFT RIGHT / X  CHANGE      O / L3+R3  CLOSE", grey, 0);
    for (u32 yy = s_qm.panel_h; yy < s_qm.h; yy++)   /* the dim: its own rows, sampled by the full-screen quad */
        for (u32 xx = 0; xx < s_qm.w; xx++) memcpy(s_qm.px + ((size_t)yy * s_qm.w + xx) * 4u, dim, 4);
#undef QMC
    s_qm.dirty = 1;
    {   /* PS3_QM_DUMP=<prefix>: the raster as <prefix>.<n>.ppm each time it changes (debug) */
        const char* dp = getenv("PS3_QM_DUMP");
        static unsigned dn;
        if (dp && *dp && dn < 64) {
            char path[512]; snprintf(path, sizeof path, "%s.%02u.ppm", dp, dn++);
            FILE* f = fopen(path, "wb");
            if (f) { fprintf(f, "P6\n%u %u\n255\n", s_qm.w, s_qm.h);
                     for (u32 i = 0; i < s_qm.w * s_qm.h; i++) { const uint8_t* q = s_qm.px + i * 4u; const uint8_t c[3] = {
                         (uint8_t)(q[0] * q[3] / 255u + 40u * (255u - q[3]) / 255u), (uint8_t)(q[1] * q[3] / 255u + 90u * (255u - q[3]) / 255u),
                         (uint8_t)(q[2] * q[3] / 255u + 60u * (255u - q[3]) / 255u) }; fwrite(c, 1, 3, f); }
                     fclose(f); } } }
    return 1;
}

/* Upload the raster (when it changed) and its descriptor; returns 0 when it cannot draw this frame. */
static int vk_qm_prepare(void)
{
    if (!vk_qm_raster()) return 0;
    if (!s_qm.dpool) {
        VkDescriptorPoolSize ps[2] = { { VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, 1 }, { VK_DESCRIPTOR_TYPE_SAMPLER, 1 } };
        VkDescriptorPoolCreateInfo pci = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, .maxSets = 1, .poolSizeCount = 2, .pPoolSizes = ps };
        if (pvkCreateDescriptorPool(s_vk.device, &pci, NULL, &s_qm.dpool) != VK_SUCCESS) { s_qm.on = 0; return 0; }
        VkDescriptorSetAllocateInfo ai = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, .descriptorPool = s_qm.dpool, .descriptorSetCount = 1, .pSetLayouts = &s_ovl.dsl };
        if (pvkAllocateDescriptorSets(s_vk.device, &ai, &s_qm.ds) != VK_SUCCESS) { s_qm.on = 0; return 0; }
    }
    if (!s_qm.tex.img || s_qm.tex_w != s_qm.w || s_qm.tex_h != s_qm.h) {
        if (s_qm.tex.img) {
            if (s_qm.old_n == 4) { vk_destroy_image(&s_qm.old[0]); memmove(&s_qm.old[0], &s_qm.old[1], sizeof s_qm.old[0] * 3); s_qm.old_n = 3; }
            s_qm.old[s_qm.old_n++] = s_qm.tex; memset(&s_qm.tex, 0, sizeof s_qm.tex); }
        if (vk_create_image(&s_qm.tex, VK_FORMAT_R8G8B8A8_UNORM, s_qm.w, s_qm.h, VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, VK_IMAGE_ASPECT_COLOR_BIT)) { s_qm.on = 0; return 0; }
        s_qm.tex_w = s_qm.w; s_qm.tex_h = s_qm.h; s_qm.tex_ready = 0; s_qm.dirty = 1;
        VkDescriptorImageInfo ii = { .imageView = s_qm.tex.view, .imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL };
        VkDescriptorImageInfo si = { .sampler = s_ovl.samp };
        VkWriteDescriptorSet wr[2] = {
            { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_qm.ds, .dstBinding = RSX_SPIRV_TEXTURE_BINDING, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, .pImageInfo = &ii },
            { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_qm.ds, .dstBinding = RSX_SPIRV_SAMPLER_BINDING, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_SAMPLER, .pImageInfo = &si } };
        pvkUpdateDescriptorSets(s_vk.device, 2, wr, 0, NULL);
    }
    if (!s_qm.dirty) return 1;
    vk_buffer own; VkBuffer sb; VkDeviceSize so;
    const VkDeviceSize bytes = (VkDeviceSize)s_qm.w * s_qm.h * 4u;
    uint8_t* p = (uint8_t*)vk_stage_alloc(bytes, &own, &sb, &so);
    if (!p) return s_qm.tex_ready;
    if (own.buf) { vk_destroy_buffer(&own); return s_qm.tex_ready; }
    memcpy(p, s_qm.px, (size_t)bytes);
    VkImageMemoryBarrier tb = { .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
        .srcAccessMask = VK_ACCESS_SHADER_READ_BIT, .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
        .oldLayout = s_qm.tex_ready ? VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL : VK_IMAGE_LAYOUT_UNDEFINED, .newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .image = s_qm.tex.img, .subresourceRange = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 } };
    pvkCmdPipelineBarrier(s_vk.cmd, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, NULL, 0, NULL, 1, &tb);
    VkBufferImageCopy rg = { .bufferOffset = so, .imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 }, .imageExtent = { s_qm.w, s_qm.h, 1 } };
    pvkCmdCopyBufferToImage(s_vk.cmd, sb, s_qm.tex.img, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &rg);
    tb.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT; tb.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
    tb.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL; tb.newLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    pvkCmdPipelineBarrier(s_vk.cmd, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT, 0, 0, NULL, 0, NULL, 1, &tb);
    s_qm.tex_ready = 1; s_qm.dirty = 0;
    return 1;
}

/* Inside the overlay's render pass: the dim over the whole picture, then the panel, centred. */
static void vk_qm_record(void)
{
    const float W = (float)s_vk.sc_extent.width, H = (float)s_vk.sc_extent.height;
    if (s_qm_mode == 1) {   /* a notice: the panel alone, top right */
        const float x1 = W - 60 * s_qm.u, x0 = x1 - (float)s_qm.w, y0 = 60 * s_qm.u, y1 = y0 + (float)s_qm.panel_h;
        const float nx0 = x0 / W * 2.0f - 1.0f, nx1 = x1 / W * 2.0f - 1.0f, ny0 = 1.0f - y0 / H * 2.0f, ny1 = 1.0f - y1 / H * 2.0f;
        const float pv = (float)s_qm.panel_h / (float)s_qm.h;
        const float q[24] = { nx0, ny0, 0, 0,  nx1, ny0, 1, 0,  nx1, ny1, 1, pv,  nx0, ny0, 0, 0,  nx1, ny1, 1, pv,  nx0, ny1, 0, pv };
        VkDeviceSize voff = 0; void* vp = vk_ring_alloc(sizeof q, 16u, &voff);
        if (!vp) return;
        memcpy(vp, q, sizeof q);
        pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_ovl.pipe);
        pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_ovl.pl, 0, 1, &s_qm.ds, 0, NULL);
        VkBuffer rb = s_ring.buf; pvkCmdBindVertexBuffers(s_vk.cmd, 0, 1, &rb, &voff);
        pvkCmdDraw(s_vk.cmd, 6, 1, 0, 0);
        return;
    }
    if (s_qm.wheel) {   /* rsx lightning: the colour wheel at the right, no dim (the lightning stays in view) */
        const float x1 = W - 60 * s_qm.u, x0 = x1 - (float)s_qm.w, y0 = (H - (float)s_qm.panel_h) * 0.5f, y1 = y0 + (float)s_qm.panel_h;
        const float nx0 = x0 / W * 2.0f - 1.0f, nx1 = x1 / W * 2.0f - 1.0f, ny0 = 1.0f - y0 / H * 2.0f, ny1 = 1.0f - y1 / H * 2.0f;
        const float pv = (float)s_qm.panel_h / (float)s_qm.h;
        const float q[24] = { nx0, ny0, 0, 0,  nx1, ny0, 1, 0,  nx1, ny1, 1, pv,  nx0, ny0, 0, 0,  nx1, ny1, 1, pv,  nx0, ny1, 0, pv };
        VkDeviceSize voff = 0; void* vp = vk_ring_alloc(sizeof q, 16u, &voff);
        if (!vp) return;
        memcpy(vp, q, sizeof q);
        pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_ovl.pipe);
        pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_ovl.pl, 0, 1, &s_qm.ds, 0, NULL);
        VkBuffer rb = s_ring.buf; pvkCmdBindVertexBuffers(s_vk.cmd, 0, 1, &rb, &voff);
        pvkCmdDraw(s_vk.cmd, 6, 1, 0, 0);
        return;
    }
    const float x0 = (W - (float)s_qm.w) * 0.5f, y0 = (H - (float)s_qm.panel_h) * 0.5f;
    const float x1 = x0 + (float)s_qm.w, y1 = y0 + (float)s_qm.panel_h;
    const float nx0 = x0 / W * 2.0f - 1.0f, nx1 = x1 / W * 2.0f - 1.0f, ny0 = 1.0f - y0 / H * 2.0f, ny1 = 1.0f - y1 / H * 2.0f;
    const float pv = (float)s_qm.panel_h / (float)s_qm.h, dv = ((float)s_qm.panel_h + (float)QM_DIM_ROWS * 0.5f) / (float)s_qm.h;
    const float q[48] = {
        -1, 1, 0.5f, dv,  1, 1, 0.5f, dv,  1, -1, 0.5f, dv,  -1, 1, 0.5f, dv,  1, -1, 0.5f, dv,  -1, -1, 0.5f, dv,   /* dim */
        nx0, ny0, 0, 0,  nx1, ny0, 1, 0,  nx1, ny1, 1, pv,  nx0, ny0, 0, 0,  nx1, ny1, 1, pv,  nx0, ny1, 0, pv };      /* panel */
    VkDeviceSize voff = 0; void* vp = vk_ring_alloc(sizeof q, 16u, &voff);
    if (!vp) return;
    memcpy(vp, q, sizeof q);
    pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_ovl.pipe);
    pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_ovl.pl, 0, 1, &s_qm.ds, 0, NULL);
    VkBuffer rb = s_ring.buf; pvkCmdBindVertexBuffers(s_vk.cmd, 0, 1, &rb, &voff);
    pvkCmdDraw(s_vk.cmd, 12, 1, 0, 0);
}
