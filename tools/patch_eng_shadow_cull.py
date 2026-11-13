# eng shadow cull: PS3RECOMP_ENG_SHADOW_CULL=<zeta hex>:<texels> drops a shadow-map caster whose bounding
# box covers fewer than <texels> map texels (its larger side), before render state, textures, pipeline
# and binds. Only the plain caster pair: the fragment program bc1263280d2ff70f (writes a constant) with a
# 4-instruction vertex program that reads attribute 0 only and constants 256..259 (o0 = x*c256 + y*c257
# + z*c258 + c259) -- a skinned or otherwise transformed caster is never judged. The box is the position
# attribute (float/half) over the index memo's vertex range, kept with the memo entry and re-read every
# 64 frames or when the attribute changes. inFAMOUS 1's far sun cascade: 17.7% of its draws are under 2
# texels (route histogram, tools/patch_eng_caster_log.py, 2026-11-05) -- specks nobody sees, ~8% of all
# draws in a heavy frame on the RSX thread. Default off (0); the PS5 app sets 0F340000:2 for inFAMOUS 1.
import sys
C = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_draw_engine.c"
c = open(C).read()
if "eng shadow cull" in c: print("already"); sys.exit(0)
def edit(s, old, new):
    if s.count(old) != 1: print("NOT FOUND/UNIQUE:", old[:80]); sys.exit(1)
    return s.replace(old, new)
c = edit(c, '''    u64 sparse;     /* idx memo sparse: sampled hash at the last full check */
    u32* idx;
} eng_im_entry;''', '''    u64 sparse;     /* idx memo sparse: sampled hash at the last full check */
    u32* idx;
    float bb[6]; u32 bb_tag, bb_frame; u8 bb_ok;   /* eng shadow cull: position box, its attribute */
} eng_im_entry;''')
c = edit(c, '''    if (!dc.n_verts || !dc.fetch_ok) { eng_drop("fetch", prim); return; }

    int indexed = 0;''', '''    if (!dc.n_verts || !dc.fetch_ok) { eng_drop("fetch", prim); return; }
    if (eng_shadow_cull_skip()) return;   /* eng shadow cull */

    int indexed = 0;''')
c = edit(c, '''static void dc_fetch(const rsx_vertex_layout_plan* layout, int allow_remap)
{''', '''/* eng shadow cull */
static int eng_shadow_cull_skip(void)
{
    static int on = -1; static u32 zt; static float tmin; static u32 n_seen, n_skip, since;
    if (__builtin_expect(on < 0, 0)) {
        const char* e = getenv("PS3RECOMP_ENG_SHADOW_CULL");
        char* x = NULL; zt = e && *e ? (u32)strtoul(e, &x, 16) : 0;
        tmin = x && *x == ':' ? (float)atof(x + 1) : 0.0f;
        on = zt && tmin > 0.0f;
        if (on) fprintf(stderr, "[shadow cull] casters into 0x%08X under %.2f texels are skipped\\n", zt, (double)tmin);
    }
    if (!on || rsx_dsp_reg(&g.rsx, 0x0214u) != zt) return 0;
    eng_im_entry* e = dc.im_hit;
    if (!e || !e->span) return 0;
    const eng_vp_memo* vp = NULL; const eng_fp_memo* fp = NULL;
    if (!eng_guest_programs(&vp, &fp) || !vp || !fp) return 0;
    if (fp->structural != 0xBC1263280D2FF70Full || vp->instrs != 4 || vp->input_mask != 1u ||
        vp->vpc_full || vp->vpc_lo != 256 || vp->vpc_n != 4) return 0;
    rsx_dsp_vertex_attr a; rsx_dsp_get_vertex_attr(&g.rsx, 0, &a);
    const u32 esz = a.type == RSX_VTX_TYPE_FLOAT ? 4u : a.type == RSX_VTX_TYPE_HALF ? 2u : 0u;
    if (!esz || a.size < 3 || !a.stride || a.frequency > 1) return 0;
    n_seen++;
    const u32 tag = a.offset ^ (a.stride * 2654435761u) ^ (a.location << 30) ^ (a.type << 24) ^ (e->base * 40503u);
    if (!e->bb_ok || e->bb_tag != tag || g.frames - e->bb_frame >= 64u) {
        e->bb_ok = 0;
        float mn[3] = { 1e30f, 1e30f, 1e30f }, mx[3] = { -1e30f, -1e30f, -1e30f };
        const u64 last = (u64)a.offset + (u64)((e->lo + e->span - 1u + e->base) & 0x000FFFFFu) * a.stride + esz * 3u;
        if (last > 0x100000000ull) return 0;
        for (u32 i = 0; i < e->span; i++) {
            const u32 vi = (e->lo + i + e->base) & 0x000FFFFFu;
            const u8* p = eng_guest_ptr(NULL, a.location, a.offset + vi * a.stride, esz * 3u);
            if (!p) return 0;
            for (u32 j = 0; j < 3; j++) {
                float f; u32 w;
                if (esz == 4) w = ((u32)p[j * 4] << 24) | ((u32)p[j * 4 + 1] << 16) | ((u32)p[j * 4 + 2] << 8) | p[j * 4 + 3];
                else { const u32 hb = ((u32)p[j * 2] << 8) | p[j * 2 + 1];
                       const u32 s = (hb >> 15) << 31, ex = (hb >> 10) & 31u, m = hb & 1023u;
                       w = ex == 0 ? s : ex == 31 ? (s | 0x7F800000u | (m << 13)) : (s | ((ex + 112u) << 23) | (m << 13)); }
                memcpy(&f, &w, 4);
                if (!(f == f) || f > 1e20f || f < -1e20f) return 0;   /* NaN/inf: no judgement */
                if (f < mn[j]) mn[j] = f;
                if (f > mx[j]) mx[j] = f;
            }
        }
        for (u32 j = 0; j < 3; j++) { e->bb[j] = mn[j]; e->bb[3 + j] = mx[j]; }
        e->bb_tag = tag; e->bb_frame = g.frames; e->bb_ok = 1;
    }
    float m4[4][4]; memcpy(m4, g.rsx.constants[256], sizeof m4);
    float lo[2] = { 1e30f, 1e30f }, hi[2] = { -1e30f, -1e30f };
    for (u32 q = 0; q < 8; q++) {
        const float x = e->bb[(q & 1) ? 3 : 0], y = e->bb[(q & 2) ? 4 : 1], z = e->bb[(q & 4) ? 5 : 2];
        float o[4];
        for (u32 r = 0; r < 4; r++) o[r] = x * m4[0][r] + y * m4[1][r] + z * m4[2][r] + m4[3][r];
        if (!(o[3] > 1e-6f)) return 0;   /* behind or degenerate: no judgement */
        for (u32 r = 0; r < 2; r++) { const float v = o[r] / o[3]; if (v < lo[r]) lo[r] = v; if (v > hi[r]) hi[r] = v; }
    }
    const u32 ch = rsx_dsp_reg(&g.rsx, 0x0200u) >> 16, cv = rsx_dsp_reg(&g.rsx, 0x0204u) >> 16;
    const float sx = (hi[0] - lo[0]) * 0.5f * (float)(ch ? ch : 1024u);
    const float sy = (hi[1] - lo[1]) * 0.5f * (float)(cv ? cv : 1024u);
    static u32 n_out;   /* eng shadow cull: wholly off the map (draws nothing) */
    if (++since >= 200000u) { fprintf(stderr, "[shadow cull] skipped %u of %u judged casters (%u off the map)\\n", n_skip, n_seen, n_out); since = 0; n_skip = n_seen = n_out = 0; }
    if (hi[0] < -1.0f || lo[0] > 1.0f || hi[1] < -1.0f || lo[1] > 1.0f) { n_out++; n_skip++; return 1; }
    if ((sx > sy ? sx : sy) >= tmin) return 0;
    n_skip++;
    return 1;
}

static void dc_fetch(const rsx_vertex_layout_plan* layout, int allow_remap)
{''')
open(C, "w").write(c); print("patched")
