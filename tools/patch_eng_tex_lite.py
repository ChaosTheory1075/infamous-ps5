# eng tex lite: fewer texture-unit decodes per draw. eng_pipeline_get decoded all sixteen units
# (rsx_dsp_get_texture: 11 register reads + a memset each) for its cube/volume masks, and
# sink_bind_textures decoded all sixteen again before skipping the ones the program does not sample.
# inFAMOUS 1's sun-shadow casters (~5,300 of ~8,000 draws in a heavy frame) sample none. Now the masks
# read the 3-4 registers they test and only the gamma/expand candidate units get a full decode; the bind
# loop tests the program's read mask first. rsx_dsp_get_texture was ~4% self / ~8% with its callees of
# the RSX thread on the BC-250 route (2026-11-05). PS3RECOMP_ENG_TEX_LITE=0 = old.
# Part 2 (eng sparse lanes): the per-frame sparse texture hash ran one serial FNV chain (8 dependent
# multiplies per sampled 64-byte block); eight independent lanes, as eng_texture_content_hash has. The
# value is only compared with another sparse hash from the same run.
import sys
C = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_draw_engine.c"
c = open(C).read()
def edit(s, old, new):
    if s.count(old) != 1: print("NOT FOUND/UNIQUE:", old[:80]); sys.exit(1)
    return s.replace(old, new)

if "eng tex lite" not in c:
    c = edit(c, '''static u32 eng_cube_mask(const rsx_dsp_texture tex[RSX_DSP_NUM_TEXTURES])''',
'''/* eng tex lite: on unless PS3RECOMP_ENG_TEX_LITE=0. */
static int eng_tex_lite(void)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3RECOMP_ENG_TEX_LITE"); on = !(e && *e == '0'); }
    return on;
}

static u32 eng_cube_mask(const rsx_dsp_texture tex[RSX_DSP_NUM_TEXTURES])''')
    c = edit(c, '''    rsx_dsp_texture tex[RSX_DSP_NUM_TEXTURES];
    for (u32 u = 0; u < RSX_DSP_NUM_TEXTURES; ++u) rsx_dsp_get_texture(&g.rsx, u, &tex[u]);
    const u32 cube_mask = eng_cube_mask(tex);
    const u32 vol_mask = eng_volume_mask(tex);
    const u32 vtex_mask = eng_vtex_mask();''',
'''    rsx_dsp_texture tex[RSX_DSP_NUM_TEXTURES];
    u32 cube_mask, vol_mask;
    if (eng_tex_lite()) {   /* eng tex lite: the masks' own registers; full decodes for the candidates */
        const int have3d = g.be->texture_create_3d && g.be->texture_upload_3d;
        const u32 want = fixed ? 0u : (fp->gamma_cand | fp->expand_cand);
        cube_mask = vol_mask = 0;
        for (u32 u = 0; u < RSX_DSP_NUM_TEXTURES; ++u) {
            if (want >> u & 1u) rsx_dsp_get_texture(&g.rsx, u, &tex[u]);
            if (!(rsx_dsp_reg(&g.rsx, 0x1A0Cu + u * 0x20u) >> 31)) continue;   /* CONTROL0 enable */
            const u32 fmt = rsx_dsp_reg(&g.rsx, 0x1A04u + u * 0x20u);
            const u32 rect = rsx_dsp_reg(&g.rsx, 0x1A18u + u * 0x20u);
            const u32 w = rect >> 16, h = rect & 0xFFFFu, cube = (fmt >> 2) & 1u;
            if (cube && w && w == h) cube_mask |= 1u << u;
            if (have3d && !cube && ((fmt >> 4) & 0xFu) == 3u && w && h &&
                (rsx_dsp_reg(&g.rsx, 0x1840u + u * 4u) >> 20) > 1u) vol_mask |= 1u << u;
        }
    } else {
        for (u32 u = 0; u < RSX_DSP_NUM_TEXTURES; ++u) rsx_dsp_get_texture(&g.rsx, u, &tex[u]);
        cube_mask = eng_cube_mask(tex);
        vol_mask = eng_volume_mask(tex);
    }
    const u32 vtex_mask = eng_vtex_mask();''')
    c = edit(c, '''    for (u32 u = 0; u < RSX_BE_MAX_TEXTURES; u++) {
        rsx_dsp_texture t;
        rsx_dsp_get_texture(&g.rsx, u, &t);''', '''    const int lite = eng_tex_lite();   /* eng tex lite */
    for (u32 u = 0; u < RSX_BE_MAX_TEXTURES; u++) {
        if (lite && !(fp_reads >> u & 1u)) continue;
        rsx_dsp_texture t;
        rsx_dsp_get_texture(&g.rsx, u, &t);''')
    print("patched tex lite")

if "eng sparse lanes" not in c:
    c = edit(c, '''    for (u32 i = 0; i + 64 <= span; i += 2048) {
        u64 w[8]; memcpy(w, src + i, sizeof w);
        for (int k = 0; k < 8; k++) h = (h ^ w[k]) * 1099511628211ull;
    }
    { u64 w[8]; memcpy(w, src + span - 64, sizeof w);
      for (int k = 0; k < 8; k++) h = (h ^ w[k]) * 1099511628211ull; }''',
'''    u64 l[8];   /* eng sparse lanes */
    for (int k = 0; k < 8; k++) l[k] = h ^ (0x9E3779B97F4A7C15ull * (u64)(k + 1));
    for (u32 i = 0; i + 64 <= span; i += 2048) {
        u64 w[8]; memcpy(w, src + i, sizeof w);
        for (int k = 0; k < 8; k++) l[k] = (l[k] ^ w[k]) * 1099511628211ull;
    }
    { u64 w[8]; memcpy(w, src + span - 64, sizeof w);
      for (int k = 0; k < 8; k++) l[k] = (l[k] ^ w[k]) * 1099511628211ull; }
    for (int k = 0; k < 8; k++) h ^= l[k] * (u64)(2 * k + 1);''')
    print("patched sparse lanes")

open(C, "w").write(c)
