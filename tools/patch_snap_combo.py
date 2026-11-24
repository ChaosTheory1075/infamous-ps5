# snap combo: holding L3+R3 (both sticks clicked) for 3/4 s on the controller saves console screenshots
# without diagnostics: one full-size frame now, then a burst of 12 frames (every 3rd frame, ~1.8 s at
# 20 fps -- long enough to see a flicker) into $PS3_SNAP_DIR/snap_<n>_<k>.ppm. For the player to point
# at a picture problem the moment it shows. PS3_SNAP_DIR unset = off.
import sys
P = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/input/cellPad.c"
V = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_vulkan_backend.c"
p = open(P).read(); v = open(V).read()
if "snap combo" in p: print("already"); sys.exit(0)
def edit(s, old, new):
    if s.count(old) != 1: print("NOT FOUND/UNIQUE:", old[:80]); sys.exit(1)
    return s.replace(old, new)

p = edit(p, '''    {
        unsigned int ea = (unsigned int)(uintptr_t)data_guest;
        vm_write32((unsigned long long)ea + 0, (unsigned int)data->len);   /* len (s32) */''', '''    /* snap combo: L3+R3 held 3/4 s -> console screenshots (rsx_vulkan_backend.c) */
    if (port_no == 0) {
        static unsigned held; static unsigned long long t_down; static int fired;
        if (data->len) held = (unsigned)data->button[CELL_PAD_BTN_OFFSET_DIGITAL1] & 0x06u;
        if (held == 0x06u) {
            const unsigned long long now = GetTickCount64();
            if (!t_down) t_down = now;
            if (!fired && now - t_down >= 750) { fired = 1; ps3_snap_request(); }
        } else { t_down = 0; fired = 0; }
    }
    {
        unsigned int ea = (unsigned int)(uintptr_t)data_guest;
        vm_write32((unsigned long long)ea + 0, (unsigned int)data->len);   /* len (s32) */''')
# weak default so backends without the snap keep linking
p = edit(p, '''/* cellPadGetInfo (v1 API, NID 0x3AAAD464)''', '''/* snap combo: the Vulkan backend's ps3_snap_request; a no-op elsewhere. */
__attribute__((weak)) void ps3_snap_request(void) {}

/* cellPadGetInfo (v1 API, NID 0x3AAAD464)''')
# declaration near the top
p = p.replace('#include', 'void ps3_snap_request(void);   /* snap combo */\n#include', 1)

v = edit(v, '''int g_vk_dump_now;   /* a debugger's "shot": the next present writes one */''',
'''int g_vk_dump_now;   /* a debugger's "shot": the next present writes one */
/* snap combo: frames still to save (counts down on every present; every 3rd one is written). */
static volatile int s_snap_left;
static unsigned s_snap_n;
void ps3_snap_request(void)
{
    const char* d = getenv("PS3_SNAP_DIR");
    if (!d || !*d || __atomic_load_n(&s_snap_left, __ATOMIC_RELAXED) > 0) return;
    s_snap_n++;
    __atomic_store_n(&s_snap_left, 37, __ATOMIC_RELEASE);
    printf("[snap] L3+R3: saving screenshots snap_%u_*.ppm\\n", s_snap_n); fflush(stdout);
}
static void vk_snap_write(const unsigned char* rgba)
{
    const int left = __atomic_load_n(&s_snap_left, __ATOMIC_ACQUIRE);
    if (left <= 0) return;
    __atomic_store_n(&s_snap_left, left - 1, __ATOMIC_RELEASE);
    if ((37 - left) % 3u) return;
    char path[600];
    snprintf(path, sizeof path, "%s/snap_%u_%02d.ppm", getenv("PS3_SNAP_DIR"), s_snap_n, (37 - left) / 3);
    FILE* f = fopen(path, "wb");
    if (!f) return;
    unsigned char* row = (unsigned char*)malloc((size_t)s_vk.width * 3u);
    fprintf(f, "P6\\n%u %u\\n255\\n", s_vk.width, s_vk.height);
    for (u32 y = 0; y < s_vk.height && row; y++) {
        const unsigned char* s = rgba + (size_t)y * s_vk.width * 4u;
        for (u32 x = 0; x < s_vk.width; x++) { row[x * 3] = s[x * 4]; row[x * 3 + 1] = s[x * 4 + 1]; row[x * 3 + 2] = s[x * 4 + 2]; }
        fwrite(row, 1, (size_t)s_vk.width * 3u, f);
    }
    free(row); fclose(f);
}''')
v = edit(v, '''    if ((s_vk.presented & 63u) == 0 || g_vk_dump_now) return 1;''',
'''    if ((s_vk.presented & 63u) == 0 || g_vk_dump_now || s_snap_left > 0) return 1;   /* snap combo */''')
v = edit(v, '''    if (s_vk.dump_path) vk_dump_ppm(px);
    vk_present_window();''', '''    if (s_vk.dump_path) vk_dump_ppm(px);
    vk_snap_write(px);   /* snap combo */
    vk_present_window();''')
open(P, "w").write(p); open(V, "w").write(v); print("patched")
