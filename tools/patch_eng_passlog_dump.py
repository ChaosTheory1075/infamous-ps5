# eng passlog dump: PS3RECOMP_ENG_PASSLOG_DIR=<dir> (with PS3RECOMP_ENG_PASSLOG) -- each pass's colour target A
# as it ends, read back to <dir>/p<NN>_<offset>_<w>x<h>.rgba (clip size, 4 bytes/pixel as the backend stores it),
# to compare with the same target in a real PS3 RSX local-memory dump. Every readback waits for the GPU: one frame.
edit("libs/video/rsx_draw_engine.c",
     '''static void eng_pl_flush_pass(void)
{
    if (!s_pl_key[3] && !s_pl_issued && !s_pl_clear) return;''',
     '''static u32 s_pl_handle;   /* eng passlog dump */
static void eng_pl_dump(void)
{
    static const char* dir = (const char*)-1;
    if (dir == (const char*)-1) dir = getenv("PS3RECOMP_ENG_PASSLOG_DIR");
    const u32 w = s_pl_key[2] >> 16, h = s_pl_key[2] & 0xFFFF;
    if (!dir || !s_pl_handle || !w || !h || !g.be->readback || !g.be->submit_and_wait) return;
    u8* px = (u8*)calloc((size_t)w * h, 4);
    if (!px) return;
    g.be->submit_and_wait(g.be->user, RSX_BE_FLUSH_GUEST_REFERENCE);
    g.be->readback(g.be->user, s_pl_handle, 0, 0, w, h, px, w * 4);
    char path[512]; snprintf(path, sizeof path, "%s/p%02u_%07x_%ux%u.rgba", dir, s_pl_n, s_pl_key[0], w, h);
    FILE* f = fopen(path, "wb"); if (f) { fwrite(px, 1, (size_t)w * h * 4, f); fclose(f); }
    free(px);
}
static void eng_pl_flush_pass(void)
{
    if (!s_pl_key[3] && !s_pl_issued && !s_pl_clear) return;
    eng_pl_dump();''',
     "eng passlog dump")
edit("libs/video/rsx_draw_engine.c",
     '''    if (memcmp(key, s_pl_key, sizeof key) || (ev == 2 && s_pl_issued)) { eng_pl_flush_pass(); memcpy(s_pl_key, key, sizeof key); }''',
     '''    if (memcmp(key, s_pl_key, sizeof key) || (ev == 2 && s_pl_issued)) { eng_pl_flush_pass(); memcpy(s_pl_key, key, sizeof key);
        const u32 slot = eng_current_surface(); s_pl_handle = slot == ENG_INVALID ? 0 : g.surfaces[slot].handle; }''',
     "eng passlog dump handle")
