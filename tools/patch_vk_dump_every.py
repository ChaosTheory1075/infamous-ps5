
# vk dump every: PS3RECOMP_VK_DUMP_EVERY=<s> keeps a half-size screenshot every <s> seconds
# as <PS3RECOMP_VK_DUMP>.<n>.ppm (n = 0..199, then reused) instead of overwriting one full-size file
# each frame: the console's picture, fetched over FTP. One buffer, one fwrite.
edit("libs/video/rsx_vulkan_backend.c",
     '''static void vk_dump_ppm(const unsigned char* rgba)
{
    FILE* f = fopen(s_vk.dump_path, "wb");''',
     '''static void vk_dump_ppm(const unsigned char* rgba)
{
    static double every = -1;
    static unsigned long long last_ns;
    static unsigned seq;
    if (every < 0) { const char* e = getenv("PS3RECOMP_VK_DUMP_EVERY"); every = e ? atof(e) : 0; }
    if (every > 0) {
        struct timespec ts;
        clock_gettime(CLOCK_MONOTONIC, &ts);
        const unsigned long long now = (unsigned long long)ts.tv_sec * 1000000000ull + (unsigned long long)ts.tv_nsec;
        if (last_ns && now - last_ns < (unsigned long long)(every * 1e9)) return;
        last_ns = now;
        char path[600];
        snprintf(path, sizeof path, "%s.%03u.ppm", s_vk.dump_path, seq++ % 200u);
        const u32 w = s_vk.width / 2, h = s_vk.height / 2;
        unsigned char* buf = (unsigned char*)malloc((size_t)w * h * 3 + 32);
        if (!buf) return;
        int len = snprintf((char*)buf, 32, "P6\\n%u %u\\n255\\n", w, h);
        unsigned char* o = buf + len;
        for (u32 y = 0; y < h; y++)
            for (u32 x = 0; x < w; x++) {
                const unsigned char* s = rgba + ((size_t)(y * 2) * s_vk.width + x * 2) * 4;
                *o++ = s[0]; *o++ = s[1]; *o++ = s[2];
            }
        FILE* f = fopen(path, "wb");
        if (f) { fwrite(buf, 1, (size_t)(o - buf), f); fclose(f); }
        free(buf);
        return;
    }
    FILE* f = fopen(s_vk.dump_path, "wb");''',
     "vk dump every")
