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
 * PS3_QUICK_MENU=0: off. Included by rsx_vulkan_backend.c after vk_overlay.inc and vk_fsr.inc. */
#include "../font/stb_truetype.h"

extern volatile int      g_pad_overlay_open;
extern volatile uint32_t g_pad_overlay_toggle;
extern volatile uint32_t g_pad_overlay_nav;
extern volatile int      g_pad_ds_features;   /* cellPad.c: DualSense extras (light bar, rumble) */

typedef struct { stbtt_fontinfo info; uint8_t* data; int ok; float ascent; } qm_font;
enum { QM_ROWS = 4, QM_DIM_ROWS = 4 };
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
} s_qm = { .on = -1 };

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
    return v ? (qm_pt() ? "LIGADO" : "ON") : (qm_pt() ? "DESLIGADO" : "OFF");
}
static const char* const s_qm_label[QM_ROWS] = { "FPS Counter", "Look", "Anti-Aliasing", "DualSense Features" };
/* The menu in the game's language when it is Portuguese (PS3_LANG pt / br, as the launcher's own pt-BR text). */
static int qm_pt(void) { static int v = -1; if (v < 0) { const char* e = getenv("PS3_LANG"); v = e && (!strncmp(e, "pt", 2) || !strncmp(e, "br", 2)); } return v; }
static const char* const s_qm_label_pt[QM_ROWS] = { "Contador de FPS", "Visual", "Antisserrilhado", "Recursos do DualSense" };
static const char* const s_qm_section_pt[QM_ROWS] = { "TELA", NULL, NULL, "CONTROLE" };
static const char* const s_qm_section[QM_ROWS] = { "DISPLAY", NULL, NULL, "CONTROLLER" };
static const char* const s_qm_ini_key[QM_ROWS] = { "fps_counter", "look", "anti_aliasing", "dualsense" };

/* `key = value` set in each launcher ini (the other lines kept), as MGR's SetMenuValue */
static void qm_save(const char* key, int value)
{
    const char* list = getenv("PS3_QM_INI");
    if (!list || !*list) return;
    char paths[512]; snprintf(paths, sizeof paths, "%s", list);
    for (char* p = strtok(paths, ":"); p; p = strtok(NULL, ":")) {
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
            if (!strncmp(t, key, kl) && (t[kl] == ' ' || t[kl] == '=')) { fprintf(o, "%s = %d\n", key, value); found = 1; }
            else if (*line) fprintf(o, "%s\n", line);
        }
        if (!found) fprintf(o, "%s = %d\n", key, value);
        fclose(o); free(buf);
    }
}

static void qm_change(int row, int back)
{
    int v = qm_value(row);
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
        s_qm.open = !s_qm.open;
        if (s_qm.open) { g_pad_overlay_open = 1; s_qm.swallow = 0; VK_LOG("quick menu: open\n"); }
        else s_qm.swallow = 1;
    } else if (s_qm.open) {
        if (pressed & 0x2000u) { s_qm.open = 0; s_qm.swallow = 1; }                  /* O */
        else {
            if (pressed & 0x10u) s_qm.row = (s_qm.row + QM_ROWS - 1) % QM_ROWS;      /* up */
            if (pressed & 0x40u) s_qm.row = (s_qm.row + 1) % QM_ROWS;                /* down */
            if (pressed & 0x80u) qm_change(s_qm.row, 1);                            /* left */
            if (pressed & (0x20u | 0x4000u)) qm_change(s_qm.row, 0);                /* right, X */
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
    char key[160]; snprintf(key, sizeof key, "%d %d %d %d %d %d %.3f %.3f", s_qm.row, qm_value(0), qm_value(1), qm_value(2), qm_value(3),
                            s_qm.open, (double)a, (double)u);
    if (s_qm.px && !strcmp(key, s_qm.key)) return 1;   /* nothing changed */
    snprintf(s_qm.key, sizeof s_qm.key, "%s", key);
    int heads = 0; for (int i = 0; i < QM_ROWS; i++) heads += s_qm_section[i] ? 1 : 0;
    const float row_h = 40 * u, head_h = 44 * u, w = 760 * u;
    const float h = 110 * u + QM_ROWS * row_h + heads * head_h + 70 * u;
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
    for (int i = 0; i < QM_ROWS; i++) {
        if (s_qm_section[i]) {
            y += 10 * u;
            qm_text(&s_qm.body, 20 * u, 40 * u, y, qm_pt() ? s_qm_section_pt[i] : s_qm_section[i], red, 0);
            qm_fill(40 * u, y + 28 * u, w - 40 * u, y + 29 * u, line, 0, 0);
            y += head_h - 10 * u;
        }
        const int sel = i == s_qm.row;
        if (sel) qm_fill(24 * u, y + 2 * u, w - 24 * u, y + row_h - 2 * u, band, 4 * u, 0);
        qm_text(&s_qm.item, 28 * u, 40 * u, y + 5 * u, qm_pt() ? s_qm_label_pt[i] : s_qm_label[i], sel ? white : grey, 0);
        char v[64]; snprintf(v, sizeof v, sel ? "<  %s  >" : "%s", qm_value_text(i));
        const float vw = qm_text(&s_qm.item, 28 * u, 0, 0, v, grey, 1);
        qm_text(&s_qm.item, 28 * u, w - 40 * u - vw, y + 5 * u, v, sel ? red : grey, 0);
        y += row_h;
    }
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
