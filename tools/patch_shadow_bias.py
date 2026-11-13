# shadow bias: PS3RECOMP_ENG_SHADOW_BIAS=<depth> moves a comparing program's shadow reference that far
# (in normalised map depth) towards passing before the compare. inFAMOUS 1 draws its sun-shadow cascades
# with polygon offset off and front faces culled, so a wall facing away from the sun meets its own depth
# in the map; this engine's float compare then flips pixel by pixel along the map's texel steps -- acne --
# and the light pass multiplies the sky ambient by that shadow term: the blue dot grids / swirls on every
# shaded wall (2026-11-05; console shot 112649 vs the real PS3, BC-250 route with FP_PATCH bias 0.002:
# gone). Part of rsx_fp_shadow_desc, so it is in the program key. Default 0 = old.
import sys
H = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_fp_decompiler.h"
C = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_fp_decompiler.c"
h = open(H).read(); c = open(C).read()
if "shadow bias" in c: print("already"); sys.exit(0)
def edit(s, old, new):
    if s.count(old) != 1: print("NOT FOUND/UNIQUE:", old[:80]); sys.exit(1)
    return s.replace(old, new)
h = edit(h, '''    u8 grid, mode;
} rsx_fp_shadow_desc;''', '''    u8 grid, mode;
    /* bias: PS3RECOMP_ENG_SHADOW_BIAS in 1/1048576 of the map's depth, the
     * reference moved that far towards passing (shadow bias). */
    u16 bias;
} rsx_fp_shadow_desc;''')
c = edit(c, '''void rsx_fp_shadow_desc_from_texture(rsx_fp_shadow_desc* out, u32 format,''',
'''static int fp_shadow_bias(void)   /* shadow bias: 1/1048576 units */
{
    static int v = -1;
    if (v < 0) { const char* e = getenv("PS3RECOMP_ENG_SHADOW_BIAS"); const double d = e && *e ? atof(e) : 0.0;
                 v = d > 0.0 && d < 0.06 ? (int)(d * 1048576.0 + 0.5) : 0; }
    return v;
}

void rsx_fp_shadow_desc_from_texture(rsx_fp_shadow_desc* out, u32 format,''')
c = edit(c, '''    const int d24 = fp_shadow_d24();
    if (d24 >= 1 && d24 <= 4) {''', '''    out->bias = (u16)fp_shadow_bias();   /* shadow bias */
    const int d24 = fp_shadow_d24();
    if (d24 >= 1 && d24 <= 4) {''')
c = edit(c, '''        "    float reference = saturate(coordinate.z);\\n",
        unit, cmp[d->func], unit);
    out_puts(p, text);''', '''        "    float reference = saturate(coordinate.z);\\n",
        unit, cmp[d->func], unit);
    out_puts(p, text);
    /* shadow bias: towards passing -- down for < and <=, up for > and >= */
    if (d->bias && d->func != 2 && d->func != 5 && d->func != 0 && d->func != 7) {
        snprintf(text, sizeof text, "    reference = saturate(reference %c %.9g);\\n",
                 (d->func == 1 || d->func == 3) ? '-' : '+', (double)d->bias / 1048576.0);
        out_puts(p, text);
    }''')
open(H, "w").write(h); open(C, "w").write(c); print("patched")
