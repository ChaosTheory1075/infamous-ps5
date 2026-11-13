/* vk overlay: the frame-rate counter as the other PS5 recomps draw it (GTA IV's src/ps5/game/ps5_overlay.cpp):
 * a panel at the left edge halfway down the picture. Simple = frames a second (coloured by frame time: green
 * at 60+, white at 30+, yellow, red) and the frame time. Detailed adds the 1% low and the worst frame of the
 * last 256, the picture (render size, output, refresh), the renderer's time a frame and a 120-bar frame-time
 * graph with the 60 and 30 marks. Rasterized on the CPU with DejaVu Sans (vk_overlay_font.h, glyphs made
 * for a 4K output) at the output's scale, uploaded as an RGBA8 texture and drawn alpha-blended into the
 * swapchain image after the frame's blit, so it is crisp at the output resolution.
 * PS3_FPS_COUNTER: 0/off, 1/simple, 2/true/detailed (launcher.ini: fps_counter). Included by
 * rsx_vulkan_backend.c before vk_present_window. */
#include "vk_overlay_font.h"
#include <time.h>
#include <math.h>
#include <strings.h>

enum { OVL_HIST = 256, OVL_BARS = 120, OVL_MAX_FB = 8 };
static struct {
    int mode;                                   /* -1 unread, 0 off, 1 simple, 2 detailed */
    uint32_t hist_us[OVL_HIST]; uint64_t presents, last_ns, win_t0, win_frames, cpu_last_ns;
    float fps, ms, low_fps, worst_ms, renderer_ms;
    uint64_t gen, win_gen; float shown_fps;   /* vk overlay fg: generated frames presented (frame generation) */
    uint8_t* px; u32 w, h, cap;                 /* the panel's RGBA8 raster */
    float s;                                    /* units -> output pixels (GTA IV: min(W/1920, H/1080)) */
    vk_image tex; u32 tex_w, tex_h;
    VkSampler samp; VkRenderPass rp; VkFramebuffer fb[OVL_MAX_FB]; VkFormat fb_fmt;
    VkPipelineLayout pl; VkPipeline pipe; VkDescriptorSetLayout dsl; VkDescriptorPool dpool; VkDescriptorSet ds;
    int failed, ds_tex_gen; u32 skip;
    vk_image old[4]; int old_n;                 /* textures of earlier sizes, destroyed once their frames are done */
} s_ovl = { .mode = -1 };

static int vk_overlay_mode(void)
{
    if (s_ovl.mode < 0) {
        const char* e = getenv("PS3_FPS_COUNTER");
        s_ovl.mode = !e || !*e ? 0 : !strcmp(e, "1") || !strcasecmp(e, "simple") ? 1 :
                     !strcmp(e, "2") || !strcasecmp(e, "true") || !strcasecmp(e, "detailed") || !strcasecmp(e, "on") ? 2 : 0;
        if (s_ovl.mode) VK_LOG("fps counter: %s\n", s_ovl.mode == 1 ? "simple" : "detailed");
    }
    return s_ovl.failed ? 0 : s_ovl.mode;
}

/* ---- statistics: one tick per present (GTA IV's Sample(): a 0.5 s window, p99 + max of the history) ---- */
static void vk_overlay_tick(void)
{
    const uint64_t now = ps3_ft_now();
    if (s_ovl.last_ns) {
        const uint64_t d = now - s_ovl.last_ns;
        s_ovl.hist_us[s_ovl.presents % OVL_HIST] = (uint32_t)(d / 1000u > 0xFFFFFFFFu ? 0xFFFFFFFFu : d / 1000u);
    }
    s_ovl.last_ns = now; s_ovl.presents++;
    if (!s_ovl.win_t0) { s_ovl.win_t0 = now; s_ovl.win_frames = s_ovl.presents; }
    {   struct timespec ts; uint64_t cpu = 0;
        if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &ts) == 0) cpu = (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
        if (s_ovl.cpu_last_ns && cpu > s_ovl.cpu_last_ns) {   /* the renderer's share: this thread's CPU time a frame, smoothed */
            const float r = (float)(cpu - s_ovl.cpu_last_ns) / 1e6f;
            s_ovl.renderer_ms = s_ovl.renderer_ms ? s_ovl.renderer_ms * 0.9f + r * 0.1f : r; }
        s_ovl.cpu_last_ns = cpu; }
    const uint64_t span = now - s_ovl.win_t0;
    if (span < 500000000ull) return;
    const uint64_t n = s_ovl.presents - s_ovl.win_frames;
    s_ovl.fps = (float)((double)n * 1e9 / (double)span);
    s_ovl.shown_fps = (float)((double)(n + (s_ovl.gen - s_ovl.win_gen)) * 1e9 / (double)span);   /* vk overlay fg */
    s_ovl.win_gen = s_ovl.gen;
    s_ovl.ms = n ? (float)((double)span / 1e6 / (double)n) : 0.0f;
    s_ovl.win_t0 = now; s_ovl.win_frames = s_ovl.presents;
    uint32_t t[OVL_HIST]; u32 c = 0;
    const u32 count = (u32)(s_ovl.presents > 1 ? (s_ovl.presents - 1 < OVL_HIST ? s_ovl.presents - 1 : OVL_HIST) : 0);
    for (u32 i = 0; i < count; i++) { const uint32_t us = s_ovl.hist_us[(s_ovl.presents - 1 - i) % OVL_HIST]; if (us) t[c++] = us; }
    if (!c) { s_ovl.low_fps = s_ovl.worst_ms = 0; return; }
    for (u32 i = 1; i < c; i++) { const uint32_t v = t[i]; u32 j = i; while (j && t[j - 1] > v) { t[j] = t[j - 1]; j--; } t[j] = v; }
    const uint32_t p99 = t[(u32)((double)(c - 1) * 0.99)];
    s_ovl.low_fps = p99 ? (float)(1e6 / (double)p99) : 0.0f;
    s_ovl.worst_ms = (float)t[c - 1] / 1000.0f;
}

/* ---- the raster ---------------------------------------------------------------------------------------- */
static void ovl_rate_color(float ms, uint8_t c[4])
{
    if (ms <= 17.5f)      { c[0] = 120; c[1] = 230; c[2] = 140; }
    else if (ms <= 34.5f) { c[0] = 244; c[1] = 245; c[2] = 247; }
    else if (ms <= 50.5f) { c[0] = 245; c[1] = 200; c[2] = 80; }
    else                  { c[0] = 240; c[1] = 90;  c[2] = 80; }
    c[3] = 255;
}
static inline void ovl_blend(uint8_t* d, const uint8_t c[4], u32 a)   /* straight alpha over */
{
    if (!a) return;
    const u32 sa = a * c[3] / 255u, da = d[3];
    const u32 oa = sa + da * (255u - sa) / 255u;
    if (!oa) return;
    for (int i = 0; i < 3; i++) d[i] = (uint8_t)((c[i] * sa + d[i] * da * (255u - sa) / 255u) / oa);
    d[3] = (uint8_t)oa;
}
static void ovl_rect(float x0, float y0, float x1, float y1, const uint8_t c[4], float radius)
{
    const int ix0 = x0 < 0 ? 0 : (int)x0, iy0 = y0 < 0 ? 0 : (int)y0;
    const int ix1 = x1 > (float)s_ovl.w ? (int)s_ovl.w : (int)(x1 + 0.999f), iy1 = y1 > (float)s_ovl.h ? (int)s_ovl.h : (int)(y1 + 0.999f);
    for (int y = iy0; y < iy1; y++)
        for (int x = ix0; x < ix1; x++) {
            u32 a = 255;
            if (radius > 0.0f) {   /* rounded corners: distance from the corner circle centre */
                const float cx = x + 0.5f < x0 + radius ? x0 + radius : x + 0.5f > x1 - radius ? x1 - radius : x + 0.5f;
                const float cy = y + 0.5f < y0 + radius ? y0 + radius : y + 0.5f > y1 - radius ? y1 - radius : y + 0.5f;
                const float dx = x + 0.5f - cx, dy = y + 0.5f - cy, d = sqrtf(dx * dx + dy * dy) - radius;
                a = d <= -0.5f ? 255u : d >= 0.5f ? 0u : (u32)((0.5f - d) * 255.0f);
            }
            ovl_blend(s_ovl.px + ((size_t)y * s_ovl.w + x) * 4u, c, a);
        }
}
static const vk_ovl_glyph* ovl_glyph(const vk_ovl_font* f, u32 cp)
{
    for (int i = 0; i < f->n; i++) if (f->g[i].cp == cp) return &f->g[i];
    return NULL;
}
/* Draw UTF-8 text with its baseline at (x, y) in output pixels; k = output scale / the glyphs' scale (2 = 4K).
 * Returns the advance in output pixels. */
static float ovl_text(const vk_ovl_font* f, float x, float y, const char* t, const uint8_t c[4], float k)
{
    float pen = x;
    while (*t) {
        u32 cp = (uint8_t)*t++;
        if (cp == 0xC2 && (uint8_t)*t == 0xB7) { cp = 0xB7; t++; }
        const vk_ovl_glyph* g = ovl_glyph(f, cp);
        if (!g) { if (cp == ' ' || cp > 127) pen += (float)f->px * 0.3f * k; continue; }
        const uint8_t* bits = f->bits + g->off;
        const float gx = pen + (float)g->bx * k, gy = y + (float)g->by * k;
        const int w = (int)((float)g->w * k + 0.999f), h = (int)((float)g->h * k + 0.999f);
        for (int yy = 0; yy < h; yy++) {
            const int py = (int)gy + yy; if (py < 0 || py >= (int)s_ovl.h) continue;
            const float sy = ((float)yy + 0.5f) / k - 0.5f;
            for (int xx = 0; xx < w; xx++) {
                const int px = (int)gx + xx; if (px < 0 || px >= (int)s_ovl.w) continue;
                const float sx = ((float)xx + 0.5f) / k - 0.5f;
                u32 a;
                if (k == 1.0f) a = bits[yy * g->w + xx];
                else {   /* bilinear in the glyph's alpha */
                    const int x0 = (int)floorf(sx), y0 = (int)floorf(sy); const float fx = sx - (float)x0, fy = sy - (float)y0;
                    float acc = 0.0f;
                    for (int j = 0; j < 2; j++) for (int i = 0; i < 2; i++) {
                        const int xs = x0 + i, ys = y0 + j;
                        const float wgt = (i ? fx : 1.0f - fx) * (j ? fy : 1.0f - fy);
                        if (xs >= 0 && xs < g->w && ys >= 0 && ys < g->h) acc += wgt * (float)bits[ys * g->w + xs]; }
                    a = (u32)(acc + 0.5f);
                }
                ovl_blend(s_ovl.px + ((size_t)py * s_ovl.w + px) * 4u, c, a);
            }
        }
        pen += (float)g->adv * k;
    }
    return pen - x;
}
static float ovl_text_w(const vk_ovl_font* f, const char* t, float k)
{
    float w = 0;
    while (*t) { u32 cp = (uint8_t)*t++; if (cp == 0xC2 && (uint8_t)*t == 0xB7) { cp = 0xB7; t++; }
        const vk_ovl_glyph* g = ovl_glyph(f, cp); w += g ? (float)g->adv * k : (float)f->px * 0.3f * k; }
    return w;
}

/* Rasterize the panel for this present. Returns 0 when there is nothing to draw. */
static int vk_overlay_raster(int mode)
{
    const float s = s_ovl.s, k = s * 0.5f;   /* the glyphs were made for s = 2 */
    const int simple = mode == 1;
    char info[3][96]; int ninfo = 0;
    if (!simple) {
        const u32 ow = s_vk.sc_extent.width, oh = s_vk.sc_extent.height;
        const char* out = oh >= 2100 ? "4K" : oh >= 1400 ? "1440p" : oh >= 1000 ? "1080p" : "720p";
        snprintf(info[ninfo++], 96, "%up render  \xC2\xB7  %s out  \xC2\xB7  60 Hz", s_vk.height, out); (void)ow;
        if (s_ovl.renderer_ms > 0.0f) snprintf(info[ninfo++], 96, "Renderer %.1f ms a frame", (double)s_ovl.renderer_ms);
    }
    float w = simple ? 196.0f : 264.0f; const float pad = 12.0f, line_h = 19.0f, graph_h = simple ? 0.0f : 48.0f;
    {   /* wide enough for "NN FPS" + the ms at this font (the panel grows, never the text over itself) */
        const float need = (pad + ovl_text_w(&s_ovl_big, "188", k) / s + 6.0f + ovl_text_w(&s_ovl_unit, "FPS", k) / s + 10.0f + ovl_text_w(&s_ovl_ms, "888.8 ms", k) / s + pad);
        if (need > w) w = need; }
    const float h = simple ? pad + 36.0f + pad - 4.0f : pad + 36.0f + 20.0f + (float)ninfo * line_h + 10.0f + graph_h + pad;
    const u32 pw = (u32)(w * s + 0.999f), ph = (u32)(h * s + 0.999f);
    if (pw * ph * 4u > s_ovl.cap) { free(s_ovl.px); s_ovl.cap = pw * ph * 4u + 4096u; s_ovl.px = (uint8_t*)malloc(s_ovl.cap); if (!s_ovl.px) { s_ovl.cap = 0; return 0; } }
    s_ovl.w = pw; s_ovl.h = ph;
    memset(s_ovl.px, 0, (size_t)pw * ph * 4u);
    const uint8_t bg[4] = { 0, 0, 0, 170 }, white[4] = { 244, 245, 247, 255 }, unitc[4] = { 255, 255, 255, 170 }, small[4] = { 255, 255, 255, 175 };
    ovl_rect(0, 0, w * s, h * s, bg, 8.0f * s);
    char big[16], ms[32], sm[96];
    uint8_t col[4];
    if (s_ovl.fps > 0.0f) {
        snprintf(big, sizeof big, "%.0f", (double)s_ovl.fps); snprintf(ms, sizeof ms, "%.1f ms", (double)s_ovl.ms);
        if (s_ovl.shown_fps > s_ovl.fps + 1.0f) {   /* vk overlay fg: what is on screen, and the game's own rate */
            snprintf(big, sizeof big, "%.0f", (double)s_ovl.shown_fps); snprintf(ms, sizeof ms, "game %.0f", (double)s_ovl.fps); }
        snprintf(sm, sizeof sm, "1%% low %.0f  \xC2\xB7  worst frame %.0f ms", (double)s_ovl.low_fps, (double)s_ovl.worst_ms);
        ovl_rate_color(s_ovl.ms, col);
    } else { snprintf(big, sizeof big, "--"); ms[0] = sm[0] = 0; memcpy(col, white, 4); }
    /* ImGui draws text from its top-left; the baseline is top + ascent. The big number: 36 units at pad - 5. */
    const float asc_big = (float)s_ovl_big.ascent, asc_ms = (float)s_ovl_ms.ascent, asc_unit = (float)s_ovl_unit.ascent;
    const float bw = ovl_text(&s_ovl_big, pad * s, (pad - 5.0f) * s + asc_big * k, big, col, k);
    ovl_text(&s_ovl_unit, pad * s + bw + 6.0f * s, (pad + 13.0f) * s + asc_unit * k, "FPS", unitc, k);
    if (ms[0]) {   /* right-aligned, but never into the "NN FPS" */
        const float unit_end = pad * s + bw + 6.0f * s + ovl_text_w(&s_ovl_unit, "FPS", k) + 10.0f * s;
        float mx = (w - pad) * s - ovl_text_w(&s_ovl_ms, ms, k);
        if (mx < unit_end) mx = unit_end;
        ovl_text(&s_ovl_ms, mx, (pad + 8.0f) * s + asc_ms * k, ms, white, k); }
    if (simple) return 1;
    const float asc_body = (float)s_ovl_body.ascent;
    if (sm[0]) ovl_text(&s_ovl_body, pad * s, (pad + 37.0f) * s + asc_body * k, sm, small, k);
    for (int i = 0; i < ninfo; i++)
        ovl_text(&s_ovl_body, pad * s, (pad + 37.0f + 20.0f + (float)i * line_h) * s + asc_body * k, info[i], small, k);
    /* the graph: one bar a frame, newest on the right, 0 to 66.7 ms tall */
    const float gx = pad, gy = pad + 36.0f + 20.0f + (float)ninfo * line_h + 10.0f, gw = w - pad * 2.0f;
    const uint8_t gbg[4] = { 255, 255, 255, 18 };
    ovl_rect(gx * s, gy * s, (gx + gw) * s, (gy + graph_h) * s, gbg, 4.0f * s);
    const float bar = gw / (float)OVL_BARS, top_ms = 66.7f;
    for (int i = 0; i < OVL_BARS && (uint64_t)i + 1 < s_ovl.presents; i++) {
        const uint32_t us = s_ovl.hist_us[(s_ovl.presents - 1 - (uint64_t)i) % OVL_HIST];
        if (!us) continue;
        const float f_ms = (float)us / 1000.0f, bh = graph_h * (f_ms < top_ms ? f_ms : top_ms) / top_ms;
        const float bx = gx + gw - bar * (float)(i + 1);
        uint8_t bc[4]; ovl_rate_color(f_ms, bc);
        ovl_rect(bx * s, (gy + graph_h - bh) * s, (bx + bar * 0.8f) * s, (gy + graph_h) * s, bc, 0.0f);
    }
    for (int m = 0; m < 2; m++) {   /* the 60 and 30 marks over the bars */
        const float line_ms = m ? 33.3f : 16.7f, ly = gy + graph_h - graph_h * line_ms / top_ms;
        const uint8_t dark[4] = { 0, 0, 0, 140 }, light[4] = { 255, 255, 255, 90 }, lt[4] = { 255, 255, 255, 200 }, dt[4] = { 0, 0, 0, 200 };
        ovl_rect(gx * s, ly * s - 1.0f * s, (gx + gw) * s, ly * s + 1.0f * s, dark, 0.0f);
        ovl_rect(gx * s, ly * s - 0.5f * s, (gx + gw) * s, ly * s + 0.5f * s, light, 0.0f);
        const char* label = m ? "30" : "60"; const float asc_mark = (float)s_ovl_mark.ascent;
        ovl_text(&s_ovl_mark, (gx + 4.0f) * s, (ly - 13.0f + 1.0f) * s + asc_mark * k, label, dt, k);
        ovl_text(&s_ovl_mark, (gx + 3.0f) * s, (ly - 13.0f) * s + asc_mark * k, label, lt, k);
    }
    return 1;
}

/* ---- Vulkan: a sampled RGBA8 texture, a render pass that loads the swapchain image, a blended quad ---- */
static const char* const s_ovl_vs =
    "struct VSInput { [[vk::location(0)]] float2 pos:ATTR0; [[vk::location(1)]] float2 uv:ATTR1; };\n"
    "struct VSOutput { float4 pos:SV_Position; float2 uv:TEXCOORD0; };\n"
    "VSOutput main(VSInput i) { VSOutput o; o.pos = float4(i.pos, 0.0, 1.0); o.uv = i.uv; return o; }\n";
static const char* const s_ovl_ps =
    "Texture2D    rsx_tex[16] : register(t0);\n"
    "SamplerState rsx_samp[16] : register(s0);\n"
    "struct PSInput { float4 pos:SV_Position; float2 uv:TEXCOORD0; };\n"
    "float4 main(PSInput i) : SV_TARGET0 { return rsx_tex[0].Sample(rsx_samp[0], i.uv); }\n";

static void vk_overlay_swapchain_reset(void)
{
    for (int i = 0; i < OVL_MAX_FB; i++)
        if (s_ovl.fb[i]) { pvkDestroyFramebuffer(s_vk.device, s_ovl.fb[i], NULL); s_ovl.fb[i] = VK_NULL_HANDLE; }
    if (s_ovl.pipe && s_ovl.fb_fmt != s_sc_fmt) {   /* the format changed: the pass and pipeline are for the old one */
        pvkDestroyPipeline(s_vk.device, s_ovl.pipe, NULL); s_ovl.pipe = VK_NULL_HANDLE;
        pvkDestroyRenderPass(s_vk.device, s_ovl.rp, NULL); s_ovl.rp = VK_NULL_HANDLE;
    }
}
static int vk_overlay_init(void)
{
    if (s_ovl.pipe) return 0;
    VkAttachmentDescription att = { .format = s_sc_fmt, .samples = VK_SAMPLE_COUNT_1_BIT,
        .loadOp = VK_ATTACHMENT_LOAD_OP_LOAD, .storeOp = VK_ATTACHMENT_STORE_OP_STORE,
        .stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE, .stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE,
        .initialLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, .finalLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR };
    VkAttachmentReference cref = { 0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL };
    VkSubpassDescription sub = { .pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS, .colorAttachmentCount = 1, .pColorAttachments = &cref };
    VkRenderPassCreateInfo rci = { .sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO, .attachmentCount = 1, .pAttachments = &att, .subpassCount = 1, .pSubpasses = &sub };
    if (pvkCreateRenderPass(s_vk.device, &rci, NULL, &s_ovl.rp) != VK_SUCCESS) { VK_LOG("fps counter: render pass failed\n"); return -1; }
    s_ovl.fb_fmt = s_sc_fmt;
    if (!s_ovl.dsl) {
        VkDescriptorSetLayoutBinding b[2] = {
            { RSX_SPIRV_TEXTURE_BINDING, VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, 1, VK_SHADER_STAGE_FRAGMENT_BIT, NULL },
            { RSX_SPIRV_SAMPLER_BINDING, VK_DESCRIPTOR_TYPE_SAMPLER, 1, VK_SHADER_STAGE_FRAGMENT_BIT, NULL } };
        VkDescriptorSetLayoutCreateInfo di = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 2, .pBindings = b };
        if (pvkCreateDescriptorSetLayout(s_vk.device, &di, NULL, &s_ovl.dsl) != VK_SUCCESS) return -1;
        VkPipelineLayoutCreateInfo pli = { .sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &s_ovl.dsl };
        if (pvkCreatePipelineLayout(s_vk.device, &pli, NULL, &s_ovl.pl) != VK_SUCCESS) return -1;
        VkDescriptorPoolSize ps[2] = { { VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, 1 }, { VK_DESCRIPTOR_TYPE_SAMPLER, 1 } };
        VkDescriptorPoolCreateInfo pci = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, .maxSets = 1, .poolSizeCount = 2, .pPoolSizes = ps };
        if (pvkCreateDescriptorPool(s_vk.device, &pci, NULL, &s_ovl.dpool) != VK_SUCCESS) return -1;
        VkDescriptorSetAllocateInfo ai = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, .descriptorPool = s_ovl.dpool, .descriptorSetCount = 1, .pSetLayouts = &s_ovl.dsl };
        if (pvkAllocateDescriptorSets(s_vk.device, &ai, &s_ovl.ds) != VK_SUCCESS) return -1;
        VkSamplerCreateInfo sci = { .sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO, .magFilter = VK_FILTER_LINEAR, .minFilter = VK_FILTER_LINEAR,
            .addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE };
        if (pvkCreateSampler(s_vk.device, &sci, NULL, &s_ovl.samp) != VK_SUCCESS) return -1;
    }
    snprintf(s_g.hlsl, VK_HLSL_BYTES, "%s", s_ovl_vs);
    VkShaderModule vs = vk_guest_module("fps counter vs", RSX_SHADER_STAGE_VERTEX);
    snprintf(s_g.hlsl, VK_HLSL_BYTES, "%s", s_ovl_ps);
    VkShaderModule fs = vk_guest_module("fps counter ps", RSX_SHADER_STAGE_FRAGMENT);
    if (!vs || !fs) return -1;
    VkPipelineShaderStageCreateInfo st[2] = {
        { .sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_VERTEX_BIT, .module = vs, .pName = "main" },
        { .sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_FRAGMENT_BIT, .module = fs, .pName = "main" } };
    VkVertexInputBindingDescription vb = { 0, 16, VK_VERTEX_INPUT_RATE_VERTEX };
    VkVertexInputAttributeDescription va[2] = { { 0, 0, VK_FORMAT_R32G32_SFLOAT, 0 }, { 1, 0, VK_FORMAT_R32G32_SFLOAT, 8 } };
    VkPipelineVertexInputStateCreateInfo vi = { .sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO,
        .vertexBindingDescriptionCount = 1, .pVertexBindingDescriptions = &vb, .vertexAttributeDescriptionCount = 2, .pVertexAttributeDescriptions = va };
    VkPipelineInputAssemblyStateCreateInfo ia = { .sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO, .topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST };
    VkPipelineViewportStateCreateInfo vp = { .sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO, .viewportCount = 1, .scissorCount = 1 };
    VkPipelineRasterizationStateCreateInfo rs = { .sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO, .polygonMode = VK_POLYGON_MODE_FILL, .cullMode = VK_CULL_MODE_NONE, .frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE, .lineWidth = 1.0f };
    VkPipelineMultisampleStateCreateInfo ms = { .sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO, .rasterizationSamples = VK_SAMPLE_COUNT_1_BIT };
    VkPipelineColorBlendAttachmentState ba = { .blendEnable = VK_TRUE, .srcColorBlendFactor = VK_BLEND_FACTOR_SRC_ALPHA, .dstColorBlendFactor = VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA,
        .colorBlendOp = VK_BLEND_OP_ADD, .srcAlphaBlendFactor = VK_BLEND_FACTOR_ONE, .dstAlphaBlendFactor = VK_BLEND_FACTOR_ZERO, .alphaBlendOp = VK_BLEND_OP_ADD, .colorWriteMask = 0xF };
    VkPipelineColorBlendStateCreateInfo cb = { .sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO, .attachmentCount = 1, .pAttachments = &ba };
    VkDynamicState dyn[2] = { VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR };
    VkPipelineDynamicStateCreateInfo ds = { .sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO, .dynamicStateCount = 2, .pDynamicStates = dyn };
    VkGraphicsPipelineCreateInfo gci = { .sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO, .stageCount = 2, .pStages = st, .pVertexInputState = &vi,
        .pInputAssemblyState = &ia, .pViewportState = &vp, .pRasterizationState = &rs, .pMultisampleState = &ms, .pColorBlendState = &cb, .pDynamicState = &ds,
        .layout = s_ovl.pl, .renderPass = s_ovl.rp, .subpass = 0 };
    const VkResult r = pvkCreateGraphicsPipelines(s_vk.device, VK_NULL_HANDLE, 1, &gci, NULL, &s_ovl.pipe);
    pvkDestroyShaderModule(s_vk.device, vs, NULL); pvkDestroyShaderModule(s_vk.device, fs, NULL);
    if (r != VK_SUCCESS) { VK_LOG("fps counter: pipeline failed (%d)\n", (int)r); s_ovl.pipe = VK_NULL_HANDLE; return -1; }
    VK_LOG("fps counter: ready (%ux%u output, scale %.2f)\n", s_vk.sc_extent.width, s_vk.sc_extent.height, (double)s_ovl.s);
    return 0;
}

/* Called inside vk_present_window after the blit, with the command buffer open and the swapchain image in
 * TRANSFER_DST_OPTIMAL. Returns 1 when it drew (the image is then in PRESENT_SRC_KHR), 0 when not. */
static int vk_qm_update(void); static int vk_qm_prepare(void); static void vk_qm_record(void);   /* vk quickmenu */
static int vk_overlay_draw(u32 idx)
{
    const int mode = vk_overlay_mode();
    const int qm = vk_qm_update();
    if (!mode && !qm) return 0;
    /* the other recomps draw it at 1080p scale even on a 4K output (the user: "way bigger than normal" at the
     * GTA IV formula's 2x), so one unit = one pixel at 4K */
    s_ovl.s = (float)s_vk.sc_extent.width / 3840.0f < (float)s_vk.sc_extent.height / 2160.0f ?
              (float)s_vk.sc_extent.width / 3840.0f : (float)s_vk.sc_extent.height / 2160.0f;
    if (!s_ovl.pipe && vk_overlay_init()) { s_ovl.failed = 1; VK_LOG("fps counter: off (setup failed)\n"); return 0; }
    if (idx >= OVL_MAX_FB) return 0;
    const int ctr = mode && vk_overlay_raster(mode);
    if (!ctr && !qm) return 0;
    if (ctr) {
    /* the texture: recreated when the panel's size changes */
    if (!s_ovl.tex.img || s_ovl.tex_w != s_ovl.w || s_ovl.tex_h != s_ovl.h) {
        if (s_ovl.tex.img) {   /* an earlier frame may still sample it: destroy it four size changes later */
            if (s_ovl.old_n == 4) { vk_destroy_image(&s_ovl.old[0]); memmove(&s_ovl.old[0], &s_ovl.old[1], sizeof s_ovl.old[0] * 3); s_ovl.old_n = 3; }
            s_ovl.old[s_ovl.old_n++] = s_ovl.tex; memset(&s_ovl.tex, 0, sizeof s_ovl.tex); }
        if (vk_create_image(&s_ovl.tex, VK_FORMAT_R8G8B8A8_UNORM, s_ovl.w, s_ovl.h,
                            VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, VK_IMAGE_ASPECT_COLOR_BIT)) { s_ovl.failed = 1; return 0; }
        s_ovl.tex_w = s_ovl.w; s_ovl.tex_h = s_ovl.h;
        VkDescriptorImageInfo ii = { .imageView = s_ovl.tex.view, .imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL };
        VkDescriptorImageInfo si = { .sampler = s_ovl.samp };
        VkWriteDescriptorSet wr[2] = {
            { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_ovl.ds, .dstBinding = RSX_SPIRV_TEXTURE_BINDING, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, .pImageInfo = &ii },
            { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_ovl.ds, .dstBinding = RSX_SPIRV_SAMPLER_BINDING, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_SAMPLER, .pImageInfo = &si } };
        pvkUpdateDescriptorSets(s_vk.device, 2, wr, 0, NULL);
        /* the image starts UNDEFINED: the first upload barrier below takes it from there */
        s_ovl.ds_tex_gen = 0;
    }
    /* upload this frame's raster (staging from the frame's ring) */
    vk_buffer own; VkBuffer sb; VkDeviceSize so;
    const VkDeviceSize bytes = (VkDeviceSize)s_ovl.w * s_ovl.h * 4u;
    uint8_t* p = (uint8_t*)vk_stage_alloc(bytes, &own, &sb, &so);
    if (!p) return 0;
    if (own.buf) { vk_destroy_buffer(&own); return 0; }   /* the ring was full: skip this frame */
    memcpy(p, s_ovl.px, (size_t)bytes);
    VkImageMemoryBarrier tb = { .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
        .srcAccessMask = VK_ACCESS_SHADER_READ_BIT, .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
        .oldLayout = s_ovl.ds_tex_gen ? VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL : VK_IMAGE_LAYOUT_UNDEFINED, .newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .image = s_ovl.tex.img, .subresourceRange = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 } };
    pvkCmdPipelineBarrier(s_vk.cmd, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, NULL, 0, NULL, 1, &tb);
    VkBufferImageCopy rg = { .bufferOffset = so, .imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 }, .imageExtent = { s_ovl.w, s_ovl.h, 1 } };
    pvkCmdCopyBufferToImage(s_vk.cmd, sb, s_ovl.tex.img, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &rg);
    tb.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT; tb.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
    tb.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL; tb.newLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    pvkCmdPipelineBarrier(s_vk.cmd, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT, 0, 0, NULL, 0, NULL, 1, &tb);
    s_ovl.ds_tex_gen = 1;
    }   /* ctr */
    const int qm_ok = qm && vk_qm_prepare();
    if (!ctr && !qm_ok) return 0;
    /* the swapchain image: transfer destination -> colour attachment */
    VkImageMemoryBarrier b = { .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
        .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_READ_BIT | VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT,
        .oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, .newLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .image = s_vk.sc_images[idx], .subresourceRange = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 } };
    pvkCmdPipelineBarrier(s_vk.cmd, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, 0, 0, NULL, 0, NULL, 1, &b);
    if (!s_ovl.fb[idx]) {
        VkImageViewCreateInfo vci = { .sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = s_vk.sc_images[idx], .viewType = VK_IMAGE_VIEW_TYPE_2D,
            .format = s_sc_fmt, .subresourceRange = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 } };
        VkImageView view; if (pvkCreateImageView(s_vk.device, &vci, NULL, &view) != VK_SUCCESS) return 0;
        VkFramebufferCreateInfo fci = { .sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO, .renderPass = s_ovl.rp, .attachmentCount = 1, .pAttachments = &view,
            .width = s_vk.sc_extent.width, .height = s_vk.sc_extent.height, .layers = 1 };
        if (pvkCreateFramebuffer(s_vk.device, &fci, NULL, &s_ovl.fb[idx]) != VK_SUCCESS) { s_ovl.fb[idx] = VK_NULL_HANDLE; return 0; }
        /* (the view lives as long as the framebuffer; a swapchain reset drops both with the framebuffer leaked view: small, rare) */
    }
    /* the quad, in the frame's ring: x = 12 units, y = centred */
    const float W = (float)s_vk.sc_extent.width, H = (float)s_vk.sc_extent.height;
    const float x0 = 12.0f * s_ovl.s, y0 = 12.0f * s_ovl.s, x1 = x0 + (float)s_ovl.w, y1 = y0 + (float)s_ovl.h;   /* top left, as the other recomps */
    /* (the HLSL front end flips Y for Vulkan: top of the screen = +1 here) */
    const float nx0 = x0 / W * 2.0f - 1.0f, nx1 = x1 / W * 2.0f - 1.0f, ny0 = 1.0f - y0 / H * 2.0f, ny1 = 1.0f - y1 / H * 2.0f;
    const float quad[24] = { nx0, ny0, 0, 0,  nx1, ny0, 1, 0,  nx1, ny1, 1, 1,  nx0, ny0, 0, 0,  nx1, ny1, 1, 1,  nx0, ny1, 0, 1 };
    VkDeviceSize voff = 0; void* vp = ctr ? vk_ring_alloc(sizeof quad, 16u, &voff) : NULL;
    if (ctr && !vp) return 0;
    if (vp) memcpy(vp, quad, sizeof quad);
    VkRenderPassBeginInfo rbi = { .sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO, .renderPass = s_ovl.rp, .framebuffer = s_ovl.fb[idx],
        .renderArea = { { 0, 0 }, s_vk.sc_extent } };
    pvkCmdBeginRenderPass(s_vk.cmd, &rbi, VK_SUBPASS_CONTENTS_INLINE);
    VkViewport vpt = { 0, 0, W, H, 0.0f, 1.0f }; VkRect2D scr = { { 0, 0 }, s_vk.sc_extent };
    pvkCmdSetViewport(s_vk.cmd, 0, 1, &vpt); pvkCmdSetScissor(s_vk.cmd, 0, 1, &scr);
    if (ctr) {
        pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_ovl.pipe);
        pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_ovl.pl, 0, 1, &s_ovl.ds, 0, NULL);
        VkBuffer rb = s_ring.buf; pvkCmdBindVertexBuffers(s_vk.cmd, 0, 1, &rb, &voff);
        pvkCmdDraw(s_vk.cmd, 6, 1, 0, 0);
    }
    if (qm_ok) vk_qm_record();   /* vk quickmenu: over everything */
    pvkCmdEndRenderPass(s_vk.cmd);
    return 1;
}
