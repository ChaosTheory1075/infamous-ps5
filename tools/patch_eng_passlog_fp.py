# eng passlog fp: DIAGNOSTIC -- each pass line of PS3RECOMP_ENG_PASSLOG also lists the fragment programs drawn
# in it (structural hash = the manifest's fp= of PS3RECOMP_ENG_SHADER_DUMP, up to 16 per pass, with counts),
# so the shader behind a bad pass can be read (if1 blue shadows, 2026-11-05).
import sys
F = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_draw_engine.c"
s = open(F).read()
if "eng passlog fp" in s: print("already"); sys.exit(0)
def edit(old, new):
    global s
    if s.count(old) != 1: print("NOT FOUND/UNIQUE:", old[:70]); sys.exit(1)
    s = s.replace(old, new)
edit('''static u32 s_pl_handle;   /* eng passlog dump */''',
     '''static u32 s_pl_handle;   /* eng passlog dump */
static u64 s_pl_fp[16]; static u32 s_pl_fpn[16], s_pl_nfp;   /* eng passlog fp */''')
edit('''    s_pl_n++; s_pl_issued = s_pl_drawn = s_pl_clear = 0;''',
     '''    for (u32 i = 0; i < s_pl_nfp && s_pl_len + 64 < (1u << 20); i++)
        s_pl_len += (size_t)snprintf(s_pl_buf + s_pl_len, 64, "   fp %016llx x%u\\n", (unsigned long long)s_pl_fp[i], s_pl_fpn[i]);
    s_pl_nfp = 0;
    s_pl_n++; s_pl_issued = s_pl_drawn = s_pl_clear = 0;''')
edit('''    if (ev == 0) s_pl_issued++; else if (ev == 1) s_pl_drawn++; else s_pl_clear |= mask;''',
     '''    if (ev == 0) s_pl_issued++; else if (ev == 1) s_pl_drawn++; else s_pl_clear |= mask;
    if (ev == 1) { const u64 h = eng_current_fp_structural(); u32 i = 0;
        while (i < s_pl_nfp && s_pl_fp[i] != h) i++;
        if (i < s_pl_nfp) s_pl_fpn[i]++; else if (s_pl_nfp < 16) { s_pl_fp[s_pl_nfp] = h; s_pl_fpn[s_pl_nfp++] = 1; } }''')
open(F, "w").write(s); print("patched")
