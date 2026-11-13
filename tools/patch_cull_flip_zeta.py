# cull flip zeta: PS3RECOMP_ENG_CULL_FLIP_ZETA=<hex offset> gives every draw into that depth target the
# opposite winding, so the other faces of each caster land in the map. inFAMOUS 1's sun-shadow map is
# 0F340000: without it the faces turned away from the sun fail their own shadow test, and the light pass
# scales the sky light by that term -> black walls with blue arcs/stripes, Cole a black silhouette from
# behind; the real PS3 video (ps3match pair p0700) has them lit, and so does this flip (BC-250 route A/B,
# 2026-11-05). PS3RECOMP_ENG_CULL_FLIP_ZETA_LIVE=1: the PS3RECOMP_ENG_CLAMP_CULL_FLIP toggle line switches
# it live (0 off, >0 on). The old CLAMP_CULL_FLIP only ran where the backend has a
# depth-clamp hook, which the Vulkan one does not (2026-11-05: black / blue-arc shaded walls on the PS5).
import sys
C = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_draw_engine.c"
c = open(C).read()
if "cull flip zeta" in c: print("already"); sys.exit(0)
def edit(s, old, new):
    if s.count(old) != 1: print("NOT FOUND/UNIQUE:", old[:80]); sys.exit(1)
    return s.replace(old, new)
c = edit(c, '''static void eng_clamp_cull_flip_set(int id, int v) { (void)id; __atomic_store_n(&s_clamp_cull_flip, v > 0, __ATOMIC_RELAXED); }''',
'''static void eng_clamp_cull_flip_set(int id, int v) { (void)id; __atomic_store_n(&s_clamp_cull_flip, v > 0, __ATOMIC_RELAXED); }
/* cull flip zeta: the target (0 = off) and the live switch (-1 = not read yet). */
static u32 s_zflip_zeta; static int s_zflip_on = -1;
static void eng_zflip_set(int id, int v) { (void)id; __atomic_store_n(&s_zflip_on, v != 0, __ATOMIC_RELAXED); }''')
c = edit(c, '''    if (__atomic_load_n(&s_clamp_cull_flip, __ATOMIC_RELAXED) > 0 && (rsx_dsp_reg(rsx, 0x1D78) & 0xF0u))
        rs->front_face = rs->front_face == 0x0901u ? 0x0900u : 0x0901u;''',
'''    if (__atomic_load_n(&s_clamp_cull_flip, __ATOMIC_RELAXED) > 0 && (rsx_dsp_reg(rsx, 0x1D78) & 0xF0u))
        rs->front_face = rs->front_face == 0x0901u ? 0x0900u : 0x0901u;
    if (__builtin_expect(__atomic_load_n(&s_zflip_on, __ATOMIC_RELAXED) < 0, 0)) {   /* cull flip zeta */
        const char* e = getenv("PS3RECOMP_ENG_CULL_FLIP_ZETA");
        s_zflip_zeta = e && *e ? (u32)strtoul(e, NULL, 16) : 0;
        __atomic_store_n(&s_zflip_on, 1, __ATOMIC_RELAXED);
        if (getenv("PS3RECOMP_ENG_CULL_FLIP_ZETA_LIVE")) ps3_toggle_watch(PS3T_ENG_CLAMP_CULL_FLIP, eng_zflip_set);
    }
    if (s_zflip_zeta && sf.zeta_offset == s_zflip_zeta && __atomic_load_n(&s_zflip_on, __ATOMIC_RELAXED) > 0)
        rs->front_face = rs->front_face == 0x0901u ? 0x0900u : 0x0901u;''')
open(C, "w").write(c); print("patched")
