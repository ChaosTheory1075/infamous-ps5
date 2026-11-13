# eng passlog: PS3RECOMP_ENG_PASSLOG=<sec> -- DIAGNOSTIC: one world frame (> 2500 draws) after <sec> s, every
# render-target pass in order: colour A offset / format / clip size, zeta offset, clears, draws issued and
# draws drawn -- the same columns as work/ps3tools/frame.py prints for a real PS3 frame, to diff the two
# (inFAMOUS 1 glow/blur chain, 2026-11-03). Lines are buffered per frame; only a world frame is printed.
edit("libs/video/rsx_draw_engine.c",
     '''static void sink_end(void* user, const rsx_dispatch* r)
{
    (void)user; (void)r;
    if (!g.ready) return;
    if (++s_draw_serial == 0) s_draw_serial = 1;''',
     '''/* eng passlog */
static int s_pl_on = -1, s_pl_done, s_pl_rec; static long s_pl_sec; static unsigned long long s_pl_t0;
static char* s_pl_buf; static size_t s_pl_len; static u32 s_pl_key[4], s_pl_issued, s_pl_drawn, s_pl_clear, s_pl_n;
static int eng_pl_active(void)
{
    if (s_pl_on < 0) { const char* e = getenv("PS3RECOMP_ENG_PASSLOG"); s_pl_on = e ? 1 : 0; s_pl_sec = e ? atol(e) : 0;
        if (s_pl_on) s_pl_buf = (char*)malloc(1 << 20); if (!s_pl_buf) s_pl_on = 0; }
    return s_pl_on && s_pl_rec && !s_pl_done;   /* recording: armed at a frame end, so the frame is whole */
}
static void eng_pl_flush_pass(void)
{
    if (!s_pl_key[3] && !s_pl_issued && !s_pl_clear) return;
    if (s_pl_len + 256 < (1u << 20))
        s_pl_len += (size_t)snprintf(s_pl_buf + s_pl_len, 256, "== colorA 0x%x fmt 0x%x %ux%u zeta 0x%x%s%s draws %u (drawn %u)\\n",
            s_pl_key[0], s_pl_key[1], s_pl_key[2] >> 16, s_pl_key[2] & 0xFFFF, s_pl_key[3],
            s_pl_clear ? " CLEAR" : "", (s_pl_clear & 0xF0u) ? (s_pl_clear & 1u ? " color+z" : " color") : (s_pl_clear ? " z" : ""),
            s_pl_issued, s_pl_drawn);
    s_pl_n++; s_pl_issued = s_pl_drawn = s_pl_clear = 0;
}
static void eng_pl_note(int ev, u32 mask)   /* ev 0 draw issued, 1 drawn, 2 clear */
{
    if (!eng_pl_active()) return;
    rsx_dsp_surface sf; rsx_dsp_get_surface(&g.rsx, &sf);
    const u32 key[4] = { sf.color_offset[0], sf.color_format | (sf.depth_format << 8) | (sf.color_target << 16),
                         (sf.clip_w << 16) | (sf.clip_h & 0xFFFF), sf.zeta_offset };
    if (memcmp(key, s_pl_key, sizeof key) || (ev == 2 && s_pl_issued)) { eng_pl_flush_pass(); memcpy(s_pl_key, key, sizeof key); }
    if (ev == 0) s_pl_issued++; else if (ev == 1) s_pl_drawn++; else s_pl_clear |= mask;
}
static void eng_pl_frame_end(u32 frame_draws)
{
    if (s_pl_on < 0) (void)eng_pl_active();
    if (!s_pl_on || s_pl_done) return;
    if (!s_pl_rec) {
        extern unsigned long long ps3_ms_now(void);
        if (!s_pl_t0) s_pl_t0 = ps3_ms_now();
        if (ps3_ms_now() - s_pl_t0 >= (unsigned long long)s_pl_sec * 1000ull) s_pl_rec = 1;
        return;
    }
    eng_pl_flush_pass();
    if (frame_draws > 2500) {
        fprintf(stderr, "[passlog] frame %u: %u draws, %u passes\\n%.*s[passlog] end\\n", g.frames, frame_draws, s_pl_n, (int)s_pl_len, s_pl_buf);
        s_pl_done = 1;
    }
    s_pl_len = 0; s_pl_n = 0; memset(s_pl_key, 0, sizeof s_pl_key);
}

static void sink_end(void* user, const rsx_dispatch* r)
{
    (void)user; (void)r;
    if (!g.ready) return;
    if (s_pl_on) eng_pl_note(0, 0);
    if (++s_draw_serial == 0) s_draw_serial = 1;''',
     "eng passlog")
edit("libs/video/rsx_draw_engine.c",
     '''    if (!pipeline_is_fixed) g.guest_draws++;
    if (ds_t0) {''',
     '''    if (!pipeline_is_fixed) g.guest_draws++;
    if (s_pl_on) eng_pl_note(1, 0);   /* eng passlog */
    if (ds_t0) {''',
     "eng passlog drawn")
edit("libs/video/rsx_draw_engine.c",
     '''    u32 targets[RSX_BE_MAX_COLOR_TARGETS];
    const u32 n_targets = eng_current_target_set(targets);
    { static int cl = -1;''',
     '''    u32 targets[RSX_BE_MAX_COLOR_TARGETS];
    const u32 n_targets = eng_current_target_set(targets);
    if (s_pl_on) eng_pl_note(2, mask);   /* eng passlog */
    { static int cl = -1;''',
     "eng passlog clear")
edit("libs/video/rsx_draw_engine.c",
     '''    s_icon_gen = rsx_button_icons_frame();
    eng_ds_frame_end(g.guest_draws);''',
     '''    s_icon_gen = rsx_button_icons_frame();
    eng_pl_frame_end(g.guest_draws);   /* eng passlog */
    eng_ds_frame_end(g.guest_draws);''',
     "eng passlog frame")
