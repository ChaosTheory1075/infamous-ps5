/* rsx lightning rules (lt2, 2026-11-14): the LIVE lightning colour for what the game colours at RUN TIME rather than
 * with a texture -- the scene lights a bolt casts and the HUD energy bar's tint. Included by rsx_draw_engine.c
 * before the draw-fast replays (it needs eng_vp_memo / eng_fp_memo); rsx_lightning.inc holds the texture side.
 *
 * A rule names a program (fragment program structural hash and/or vertex program hash), a constant row (fragment
 * constant buffer row, or vertex constant bank row) and the game's colour for Cole's electricity there, as a ratio
 * r/b, g/b (b the largest channel). A draw through that program whose row holds that ratio (within LT_RULE_TOL)
 * gets the row replaced, for that draw only, by the chosen colour:
 *   mode LIGHT  a light's colour x intensity: hue := H, saturation and value kept, then scaled to the original's
 *               luminance (the bolt lights the scene as brightly as before); WHITE = that luminance in grey
 *   mode TINT   an LDR material tint (HUD): hue := H, S + 0.25, value kept; WHITE = grey of that value
 * Every other colour in those rows (street lamps, police lights, the karma meter, ...) is left alone, so is every
 * other program. Measured on the test box (lt2_if1 notes): inFAMOUS 1's deferred point lights carry
 * the bolt light (0.30, 0.708, 1) x I and the impact light (0.30, 0.533, 1) x I; the HUD energy bar's dots, links
 * and core are white textures tinted by vertex constant c[462] = (0.4706, 0.5961, 1).
 * The rules are per game (title id): inFAMOUS 1 only; inFAMOUS 2 / Festival of Blood have none yet (gate-per-game).
 * Off (PS3_LIGHTNING_LIVE unset), DEFAULT (-1) or no rules for the title: eng_lt_rules_live() is 0 and nothing
 * below runs. */
enum { LT_RULE_LIGHT = 0, LT_RULE_TINT = 1, LT_RULE_TINT_W = 2 };   /* TINT_W: TINT, only on a draw that binds a class W texture */
typedef struct { u64 fp, vp; u16 row; u8 vpbank, mode; float r, g, b; } rsx_lt_rule;   /* r g b: the colour / its largest channel */
#define LT_RULE_TOL 0.012f
static const rsx_lt_rule s_lt_rules_if1[] = {
    /* deferred point light (light colour = fragment constant 11): the bolt's own light and its impact light */
    { 0xa8b75b132504a7b5ull, 0, 11, 0, LT_RULE_LIGHT, 0.29997f, 0.70768f, 1.0f },
    { 0xa8b75b132504a7b5ull, 0, 11, 0, LT_RULE_LIGHT, 0.29980f, 0.53320f, 1.0f },
    { 0x160009ac3f1b6158ull, 0, 11, 0, LT_RULE_LIGHT, 0.29997f, 0.70768f, 1.0f },
    { 0x160009ac3f1b6158ull, 0, 11, 0, LT_RULE_LIGHT, 0.29980f, 0.53320f, 1.0f },
    /* the other light pass shapes: colour in fragment constant 15, and in vertex constant 465 */
    { 0xc60a358316bf88f1ull, 0, 15, 0, LT_RULE_LIGHT, 0.29997f, 0.70768f, 1.0f },
    { 0xc60a358316bf88f1ull, 0, 15, 0, LT_RULE_LIGHT, 0.29980f, 0.53320f, 1.0f },
    { 0xf745375bcda733a4ull, 0, 465, 1, LT_RULE_LIGHT, 0.29997f, 0.70768f, 1.0f },
    { 0xf745375bcda733a4ull, 0, 465, 1, LT_RULE_LIGHT, 0.29980f, 0.53320f, 1.0f },
    /* HUD energy bar (dots, links, core): the HUD sprite vertex program's tint c[462] */
    { 0, 0xb985dee109aa5964ull, 462, 1, LT_RULE_TINT, 0.470588f, 0.596078f, 1.0f },
    /* the screen-space fx sprites of the bolt (class W glow textures through the same fragment program): same tint row */
    { 0, 0x879e9fa01eba6f69ull, 462, 1, LT_RULE_TINT_W, 0.470588f, 0.596078f, 1.0f },   /* (not the minimap ring: same program and tint) */
};
/* inFAMOUS 2: the white palm-core / bolt sprites (class W glow dots through the HUD-style sprite program) take the
 * energy tint from vertex constant 465 (test box lt2d_if2 light log); the scene lights are computed by the GPU light
 * pass from a light list (PS3RECOMP_ENG_GPU_LIGHT), not by constants: no light rule. */
static const rsx_lt_rule s_lt_rules_if2[] = {
    { 0, 0xd7086dd0518c01a5ull, 465, 1, LT_RULE_TINT_W, 0.470588f, 0.596078f, 1.0f },
};
/* Festival of Blood: the same sprite program's tint row holds the orange-red energy colour */
static const rsx_lt_rule s_lt_rules_fob[] = {
    { 0, 0xd7086dd0518c01a5ull, 465, 1, LT_RULE_TINT_W, 1.0f, 0.271552f, 0.030172f },   /* (0.909804, 0.247059, 0.027451) */
};
/* The player's electric TINT per game: the per-vertex colour the particle programs multiply the colourless (class W)
 * fx textures by (test box capture, PS3_LT_CAPX). A draw that binds a class W texture and carries this colour gets the
 * chosen colour instead (eng_lt_tint_draw); a draw of the same texture with another tint (chimney smoke, roll dust:
 * grey/brown) keeps the game's colours, because class W textures are no longer recoloured themselves. */
typedef struct { float hmin, hmax, smin, vmin; } rsx_lt_tint;   /* HSV window of the vertex colour (attribute 3) */
/* if1: (64,128,255) on every bolt / glide particle (hue 220); if2: (125,169,255) (102,144,255) (197,213,255) seen on
 * the bolt, blast and glide particles (hue 215-223); white (1,1,1) / (1,1,0.86) hand cores are left white. FoB: see
 * s_lt_tints_fob. Chimney smoke / roll dust are grey or brown (saturation < 0.15 or another hue): left alone. */
static const rsx_lt_tint s_lt_tints_if1[] = { { 195.0f, 240.0f, 0.15f, 0.25f } };
static const rsx_lt_tint s_lt_tints_if2[] = { { 195.0f, 240.0f, 0.15f, 0.25f } };
/* FoB: Cole's (orange-red) bolts, halo and blast particles: (1,.314,.078) (1,.176,0) (1,.314,.212) (1,.498,.361)
 * (1,.561,.561) (1,.588,.588) (.608,.098,.059) -- hue 0-13, saturation .41-1 (test box lt2d_fob); the blue tints seen
 * on W draws there ((.275,.38,.722), (.627,.745,1)) are not Cole's and stay. A window that wraps at 0 (hmin > hmax). */
static const rsx_lt_tint s_lt_tints_fob[] = { { 345.0f, 25.0f, 0.30f, 0.25f } };
static const rsx_lt_rule* s_lt_rules; static u32 s_lt_rules_n;
static const rsx_lt_tint* s_lt_tints; static u32 s_lt_tints_n;
static int s_lt_rules_game = -1;   /* -1 not decided yet, 0 not one of ours, 1 if1, 2 if2, 3 fob */
static struct { u32 hits, frame, calls, refused, win_frame; u64 ns, ns_frame, ns_max; u8 logged[16]; } s_ltr;   /* logged: lines so far per rule (3 each) */
extern const char* cellGame_get_title_id(void) __attribute__((weak));

/* Feature on, a colour chosen and one of our titles? (a load and two compares a draw; the title is decided once) */
static inline int eng_lt_rules_live(void)
{
    if (__builtin_expect(s_lt_on <= 0, 1)) return 0;
    const int hue = __atomic_load_n(&g_ps3_lt_hue, __ATOMIC_RELAXED);
    if (hue == LT_HUE_DEFAULT || hue == LT_HUE_UNSET || hue == LT_HUE_IDENTITY) return 0;
    if (__builtin_expect(s_lt_rules_game < 0, 0)) {
        const char* t = cellGame_get_title_id ? cellGame_get_title_id() : NULL;
        /* inFAMOUS 1: EU BCES00220 (the port's own PARAM.SFO, whatever edition's data), US BCUS98119;
         * inFAMOUS 2 NPUA80638 / BCUS98125; Festival of Blood NPUA80657 */
#define LT_T(id) (t && !strncmp(t, id, 9))
        s_lt_rules_game = (LT_T("BCES00220") || LT_T("BCUS98119")) ? 1 : (LT_T("NPUA80638") || LT_T("BCUS98125")) ? 2 : LT_T("NPUA80657") ? 3 : 0;
#undef LT_T
#define LT_SET(R, T) do { s_lt_rules = R; s_lt_rules_n = (u32)(sizeof R / sizeof R[0]); s_lt_tints = T; s_lt_tints_n = (u32)(sizeof T / sizeof T[0]); } while (0)
        if (s_lt_rules_game == 1) LT_SET(s_lt_rules_if1, s_lt_tints_if1);
        else if (s_lt_rules_game == 2) LT_SET(s_lt_rules_if2, s_lt_tints_if2);
        else if (s_lt_rules_game == 3) LT_SET(s_lt_rules_fob, s_lt_tints_fob);
#undef LT_SET
        if (s_lt_rules_n == 1 && !s_lt_rules[0].fp && !s_lt_rules[0].vp) s_lt_rules_n = 0;   /* the placeholder of a game without rules */
        fprintf(stderr, "[lightning] run-time colours for title %s: %u rule(s), %u electric tint(s)\n", t ? t : "?", s_lt_rules_n, s_lt_tints_n);
    }
    return s_lt_rules_game > 0;
}

static int eng_lt_rule_match(const rsx_lt_rule* r, const float v[4])
{
    if (v[0] < 0.0f || v[1] < 0.0f || v[2] < 0.0f) return 0;
    const float mx = v[0] > v[1] ? (v[0] > v[2] ? v[0] : v[2]) : (v[1] > v[2] ? v[1] : v[2]);
    if (!(mx > 1e-6f && mx < 1e6f)) return 0;
    const float d0 = v[0] / mx - r->r, d1 = v[1] / mx - r->g, d2 = v[2] / mx - r->b;
    return d0 < LT_RULE_TOL && d0 > -LT_RULE_TOL && d1 < LT_RULE_TOL && d1 > -LT_RULE_TOL && d2 < LT_RULE_TOL && d2 > -LT_RULE_TOL;
}

/* The chosen colour for a row value v (rgb; w kept by the caller). */
static void eng_lt_rule_colour(const rsx_lt_rule* r, const float v[4], int hue, float out[3])
{
    const float mx = v[0] > v[1] ? (v[0] > v[2] ? v[0] : v[2]) : (v[1] > v[2] ? v[1] : v[2]);
    const float mn = v[0] < v[1] ? (v[0] < v[2] ? v[0] : v[2]) : (v[1] < v[2] ? v[1] : v[2]);
    const float lum = 0.2126f * v[0] + 0.7152f * v[1] + 0.0722f * v[2];
    if (hue == LT_HUE_WHITE) {
        const float gl = r->mode == LT_RULE_LIGHT ? lum : mx;
        out[0] = out[1] = out[2] = gl; return;
    }
    float s = (mx - mn) / mx;
    if (r->mode != LT_RULE_LIGHT) { s += 0.25f; if (s > 1.0f) s = 1.0f; }
    const float hh = (float)hue / 60.0f; const int i = (int)hh % 6;
    const float f = hh - (float)(int)hh;
    const float p = mx * (1.0f - s), q = mx * (1.0f - s * f), t = mx * (1.0f - s * (1.0f - f));
    switch (i) {
    case 0: out[0] = mx; out[1] = t;  out[2] = p;  break;
    case 1: out[0] = q;  out[1] = mx; out[2] = p;  break;
    case 2: out[0] = p;  out[1] = mx; out[2] = t;  break;
    case 3: out[0] = p;  out[1] = q;  out[2] = mx; break;
    case 4: out[0] = t;  out[1] = p;  out[2] = mx; break;
    default: out[0] = mx; out[1] = p; out[2] = q;  break;
    }
    if (r->mode == LT_RULE_LIGHT) {   /* as bright as the original light */
        const float l2 = 0.2126f * out[0] + 0.7152f * out[1] + 0.0722f * out[2];
        float k = l2 > 1e-9f ? lum / l2 : 1.0f;
        if (k > 2.5f) k = 2.5f; if (k < 0.4f) k = 0.4f;
        out[0] *= k; out[1] *= k; out[2] *= k;
    }
}

/* Draw-fast / caster-fast replays: would this draw (current programs, current constants) take a rule? Then the
 * replay is refused and the full path patches it. Only called when eng_lt_rules_live(). */
static int eng_lt_rule_replay_hit(const eng_vp_memo* vm, const eng_fp_memo* fm)
{
    if (!vm || !fm) return 0;
    for (u32 i = 0; i < s_lt_rules_n; i++) {
        const rsx_lt_rule* r = &s_lt_rules[i];
        if ((r->fp && r->fp != fm->structural) || (r->vp && r->vp != vm->hash) || r->mode == LT_RULE_TINT_W) continue;   /* TINT_W: a W draw is refused anyway */
        float v[4];
        if (r->vpbank) { if (r->row >= RSX_DSP_NUM_CONSTANTS) continue; memcpy(v, g.rsx.constants[r->row], sizeof v); }
        else { if (r->row >= fm->constants.count) continue; memcpy(v, fm->constants.values[r->row], sizeof v); }
        if (eng_lt_rule_match(r, v)) { s_ltr.refused++; return 1; }
    }
    return 0;
}

/* The full path, after g.fp_cb is filled and before the binds: patch matching fragment rows in g.fp_cb (this
 * draw's copy) and matching vertex rows in g.rsx.constants (and g.vp_cb when that copy is what gets bound), the
 * latter saved in sv[] for eng_lt_rules_restore right after the vertex constants are bound. Returns the number of
 * saved vertex rows. */
typedef struct { u16 row; u32 w[4]; } eng_lt_vsave;
static int eng_lt_binds_w(const u32* tex, u32 mask);
static u32 eng_lt_rules_apply(u32 fp_rows, int vp_copy, eng_lt_vsave* sv, u32 sv_max, const u32* tex, u32 tex_mask)
{
    const eng_vp_memo* vm = NULL; const eng_fp_memo* fm = NULL;
    eng_guest_programs(&vm, &fm);
    if (!vm || !fm) return 0;
    {   /* most draws: no rule names their programs -- out before any timing */
        int any = 0;
        for (u32 i = 0; i < s_lt_rules_n && !any; i++)
            any = (!s_lt_rules[i].fp || s_lt_rules[i].fp == fm->structural) && (!s_lt_rules[i].vp || s_lt_rules[i].vp == vm->hash);
        if (!any) return 0;
    }
    const u64 t0 = ps3_ft_now();
    const int hue = __atomic_load_n(&g_ps3_lt_hue, __ATOMIC_RELAXED);
    u32 nsv = 0, hit = 0; int wb = -1;
    for (u32 i = 0; i < s_lt_rules_n; i++) {
        const rsx_lt_rule* r = &s_lt_rules[i];
        if ((r->fp && r->fp != fm->structural) || (r->vp && r->vp != vm->hash)) continue;
        if (r->mode == LT_RULE_TINT_W) { if (wb < 0) wb = eng_lt_binds_w(tex, tex_mask); if (!wb) continue; }
        float v[4], c[3];
        if (r->vpbank) {
            if (r->row >= RSX_DSP_NUM_CONSTANTS || nsv >= sv_max) continue;
            int done = 0; for (u32 k = 0; k < nsv; k++) done |= sv[k].row == r->row;
            if (done) continue;
            memcpy(v, g.rsx.constants[r->row], sizeof v);
            if (!eng_lt_rule_match(r, v)) continue;
            eng_lt_rule_colour(r, v, hue, c);
            sv[nsv].row = r->row; memcpy(sv[nsv].w, g.rsx.constants[r->row], sizeof sv[nsv].w); nsv++;
            memcpy(g.rsx.constants[r->row], c, sizeof c);
            if (vp_copy) memcpy(g.vp_cb + (size_t)r->row * 16u, c, sizeof c);
            if (g_rsx_vsd_track) vsd_mark(g_rsx_vsd_stale, r->row);   /* ba vs delta: the patched row travels */
        } else {
            if (r->row >= fp_rows) continue;
            memcpy(v, g.fp_cb + (size_t)r->row * 16u, sizeof v);
            if (!eng_lt_rule_match(r, v)) continue;
            eng_lt_rule_colour(r, v, hue, c);
            memcpy(g.fp_cb + (size_t)r->row * 16u, c, sizeof c);
        }
        hit++;
        if (i < 16u && s_ltr.logged[i] < 3u) { s_ltr.logged[i]++;
            fprintf(stderr, "[lightning] rule %u (%s %016llx %s[%u]) frame %u: (%g %g %g) -> (%g %g %g) hue %d\n", i,
                    r->fp ? "fp" : "vp", (unsigned long long)(r->fp ? r->fp : r->vp), r->vpbank ? "vpc" : "fpk", r->row,
                    g.frames, v[0], v[1], v[2], c[0], c[1], c[2], hue); }
    }
    /* cost: one line every 900 frames (calls, rows patched, replays refused, rule time a frame: average / worst) */
    const u64 dt = ps3_ft_now() - t0;
    if (s_ltr.frame != g.frames) {
        if (s_ltr.ns_frame > s_ltr.ns_max) s_ltr.ns_max = s_ltr.ns_frame;
        s_ltr.frame = g.frames; s_ltr.ns_frame = 0;
        if (g.frames - s_ltr.win_frame >= 900u) {
            if (s_ltr.calls) fprintf(stderr, "[lightning] rules: %u draws through a rule program, %u rows patched, %u fast replays refused in %u frames;"
                                             " %.1f us a frame on average, worst frame %.1f us\n", s_ltr.calls, s_ltr.hits, s_ltr.refused,
                                     g.frames - s_ltr.win_frame, (double)s_ltr.ns / 1e3 / (double)(g.frames - s_ltr.win_frame),
                                     (double)s_ltr.ns_max / 1e3);
            s_ltr.win_frame = g.frames; s_ltr.calls = s_ltr.hits = s_ltr.refused = 0; s_ltr.ns = s_ltr.ns_max = 0;
        }
    }
    s_ltr.calls++; s_ltr.hits += hit; s_ltr.ns += dt; s_ltr.ns_frame += dt;
    return nsv;
}
static void eng_lt_rules_restore(const eng_lt_vsave* sv, u32 nsv)
{
    for (u32 k = 0; k < nsv; k++) {
        memcpy(g.rsx.constants[sv[k].row], sv[k].w, sizeof sv[k].w);
        if (g_rsx_vsd_track) vsd_mark(g_rsx_vsd_stale, sv[k].row);   /* the next draw that reads it gets the game's value */
    }
}

/* ---- the electric tint (class W textures) ---------------------------------------------------------------------- */
/* Does a bound unit hold a class W lightning texture (the colourless fx the game tints per draw)? */
static int eng_lt_binds_w(const u32* tex, u32 mask)
{
    for (u32 u = 0; u < RSX_BE_MAX_TEXTURES; u++) {
        if (!(mask & (1u << u))) continue;
        const u32 h = tex[u];
        if (!h || h >= ENG_OWNER_N || !s_tex_owner[h]) continue;
        const eng_texture* e = &g.textures[s_tex_owner[h] - 1u];
        if (e->handle == h && e->lt_idx && eng_lt_entry((int)e->lt_idx - 1)->cls == 'W') return 1;
    }
    return 0;
}

static struct { u32 draws, patched, untinted, frame, win_frame; u64 ns; u32 logged; u64 seen[64]; } s_ltt;

/* The full path, after the binds, before the draw: a draw that binds a class W texture has its vertex colours that
 * fall in the game's electric tint window (attribute 3, s_lt_tints_*) replaced by the chosen colour (hue H at the
 * vertex colour's own saturation and value; WHITE: grey of that value). The vertices are fetched again into dc.verts
 * first (the vertex cache keeps the game's bytes; the replays refuse these draws while a colour is chosen). */
static void eng_lt_tint_draw(const rsx_vertex_layout_plan* layout, int indexed, u32 n_draw, u64 fp_struct, u64 vp_hash, const u32* tex, u32 tex_mask)
{
    const u64 t0 = ps3_ft_now();
    {   /* always fetched afresh: a vertex-cache buffer holds the game's bytes, and dc.verts may still hold a previous
         * draw's (draw-fast fetch skip) -- patched with the colour of its time */
        if (!dc_im_fill() || !dc_reserve_verts((u64)dc.n_refs * dc.layout.stride) ||
            !rsx_vertex_fetch_all(&dc.fetch_plan, dc.refs, dc.n_refs, dc.verts)) return;   /* drawn as the game made it */
        dc.vbuf = 0; dc.vbuf_hit = 0; dc.n_verts = dc.n_refs;
    }
    const int hue = __atomic_load_n(&g_ps3_lt_hue, __ATOMIC_RELAXED);
    const u32 n = indexed ? dc.n_verts : n_draw, stride = layout->stride;
    u32 hits = 0;
    const s8 sl = layout->slot_by_attr[3];   /* RSX attribute 3 = the diffuse colour (the fx programs' tint) */
    if (sl >= 0) for (u32 v = 0; v < n; v++) {
        float* x = (float*)(dc.verts + (size_t)v * stride + (size_t)sl * 16u);
        const float r = x[0], gg = x[1], b = x[2];
        if (!(r >= 0.0f && gg >= 0.0f && b >= 0.0f && r <= 1.001f && gg <= 1.001f && b <= 1.001f)) continue;
        const float mx = r > gg ? (r > b ? r : b) : (gg > b ? gg : b), mn = r < gg ? (r < b ? r : b) : (gg < b ? gg : b);
        if (mx <= 1e-6f) continue;
        const float sat = (mx - mn) / mx, d = mx - mn;
        float h = 0.0f;
        if (d > 1e-6f) { h = mx == r ? 60.0f * ((gg - b) / d) : mx == gg ? 60.0f * ((b - r) / d) + 120.0f : 60.0f * ((r - gg) / d) + 240.0f;
                         if (h < 0.0f) h += 360.0f; }
        int hit = 0;
        for (u32 k = 0; k < s_lt_tints_n && !hit; k++) {
            const rsx_lt_tint* t = &s_lt_tints[k];
            hit = sat >= t->smin && mx >= t->vmin && (t->hmin <= t->hmax ? (h >= t->hmin && h <= t->hmax) : (h >= t->hmin || h <= t->hmax));
        }
        if (!hit) continue;
        if (hue == LT_HUE_WHITE) { x[0] = x[1] = x[2] = mx; hits++; continue; }
        const float hh = (float)hue / 60.0f; const int i = (int)hh % 6; const float f = hh - (float)(int)hh;
        const float p = mx * (1.0f - sat), q = mx * (1.0f - sat * f), w = mx * (1.0f - sat * (1.0f - f));
        switch (i) { case 0: x[0] = mx; x[1] = w; x[2] = p; break; case 1: x[0] = q; x[1] = mx; x[2] = p; break;
                     case 2: x[0] = p; x[1] = mx; x[2] = w; break; case 3: x[0] = p; x[1] = q; x[2] = mx; break;
                     case 4: x[0] = w; x[1] = p; x[2] = mx; break; default: x[0] = mx; x[1] = p; x[2] = q; break; }
        hits++;
    }
    s_ltt.draws++;
    if (hits) s_ltt.patched++;
    else {   /* a W draw without the electric tint: what it carries, once per (programs, texture) -- smoke, dust, or a tint to add */
        s_ltt.untinted++;
        u64 key = fp_struct * 31u ^ vp_hash;
        for (u32 u = 0; u < RSX_BE_MAX_TEXTURES; u++) if (tex_mask & (1u << u)) key = key * 1099511628211ull ^ (u64)tex[u];
        u32 k = 0; while (k < s_ltt.logged && k < 64u && s_ltt.seen[k] != key) k++;
        if (k == s_ltt.logged && k < 64u) {
            s_ltt.seen[s_ltt.logged++] = key;
            char b[512]; int o = 0; b[0] = 0;
            for (u32 sl = 0; sl < layout->count && o < 400; sl++) {
                if (layout->attrs[sl] == 0 || !n) continue;
                const float* x = (const float*)(dc.verts + (size_t)sl * 16u);
                o += snprintf(b + o, sizeof b - (size_t)o, " a%u=(%.3f %.3f %.3f %.3f)", layout->attrs[sl], x[0], x[1], x[2], x[3]);
            }
            fprintf(stderr, "[lightning] tint: W draw without the electric tint, fp %016llx vp %016llx, %u verts, frame %u:%s\n",
                    (unsigned long long)fp_struct, (unsigned long long)vp_hash, n, g.frames, b);
        }
    }
    s_ltt.ns += ps3_ft_now() - t0;
    if (g.frames - s_ltt.win_frame >= 900u) {
        fprintf(stderr, "[lightning] tint: %u W draws (%u with the electric tint, %u without) in %u frames, %.1f us a frame\n",
                s_ltt.draws, s_ltt.patched, s_ltt.untinted, g.frames - s_ltt.win_frame, (double)s_ltt.ns / 1e3 / (double)(g.frames - s_ltt.win_frame));
        s_ltt.win_frame = g.frames; s_ltt.draws = s_ltt.patched = s_ltt.untinted = 0; s_ltt.ns = 0;
    }
}
