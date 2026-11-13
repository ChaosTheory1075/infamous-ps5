# eng caster fast: a plain shadow caster (eng shadow cull's pair: fp bc1263280d2ff70f, the 4-instruction
# position-only vp) whose cheap inputs -- decoded render state, surface, viewport, scissor/stencil/polygon
# offset/depth-clamp registers, program memos, vertex stride, topology -- are exactly those of the previous
# full-path caster in the same frame is replayed: the same binds (targets, pipeline, fragment constants,
# textures, hud, viewport, scissor, stencil) with its own vertex constants, vertex buffer and indices.
# Skipped: target set, depth lookup, texture binding, the pipeline lookup with its program/key work, fragment
# constant assembly and the diagnostics. ~2/3 of inFAMOUS 1's draws are such casters (2026-11-05).
# Only cached-vertex-buffer draws with the index memo's remembered indices; anything else, or a mismatch,
# takes the full path (which records the next template). PS3RECOMP_ENG_CASTER_FAST=1 (also live).
import sys
C = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_draw_engine.c"
c = open(C).read()
if "eng caster fast" in c: print("already"); sys.exit(0)
def edit(s, old, new):
    if s.count(old) != 1: print("NOT FOUND/UNIQUE:", old[:80]); sys.exit(1)
    return s.replace(old, new)

# the template and its switch, before sink_end
c = edit(c, '''static void dc_fetch(const rsx_vertex_layout_plan* layout, int allow_remap)
{''', '''/* eng caster fast: the previous full-path plain caster's inputs and binds */
#define ENG_CT_FP_MAX 1024u
static struct {
    int valid; u32 frame;
    rsx_be_render_state rs; rsx_dsp_surface sf; rsx_dsp_viewport vp;
    u32 regs[8];
    const eng_vp_memo* vpm; const eng_fp_memo* fpm;
    u64 vph, fps_; u32 vstart, vinstrs, floc, foff, fsize;   /* the memo slots' contents (slots are recycled) */
    rsx_topology topology; u32 stride, prim;
    u32 pipeline, handles[RSX_BE_MAX_COLOR_TARGETS], n_targets, depth_handle, zslot, surf[RSX_BE_MAX_COLOR_TARGETS];
    float xf[8]; u32 vpc_lo, vpc_n;
    u8 fp_cb[ENG_CT_FP_MAX]; u32 fp_bytes;
    u32 textures[RSX_BE_MAX_TEXTURES]; rsx_be_sampler_desc samplers[RSX_BE_MAX_TEXTURES]; u32 tex_mask;
    u32 vtextures[RSX_BE_MAX_VERTEX_TEXTURES]; rsx_be_sampler_desc vsamplers[RSX_BE_MAX_VERTEX_TEXTURES]; u32 vtex_mask;
    int hud; u32 hud_w; float W, H; u32 sc[4]; u32 sref;
} s_ct;
static int s_ct_hud; static u32 s_ct_sc[4];   /* this draw's hud and scissor arguments (full path) */
static volatile int s_ct_on = -1; static unsigned s_ct_fast, s_ct_full;
static void eng_ct_set(int id, int v) { (void)id; __atomic_store_n(&s_ct_on, v > 0, __ATOMIC_RELAXED); s_ct.valid = 0; }
static int eng_ct_on(void)
{
    if (__builtin_expect(s_ct_on < 0, 0)) {
        const char* e = getenv("PS3RECOMP_ENG_CASTER_FAST");
        __atomic_store_n(&s_ct_on, e && *e == '1', __ATOMIC_RELAXED);
        ps3_toggle_watch(PS3T_ENG_CASTER_FAST, eng_ct_set);
        if (e && *e == '1') __atomic_store_n(&s_ct_on, 1, __ATOMIC_RELAXED);   /* the env wins over an absent toggle line */
    }
    return __atomic_load_n(&s_ct_on, __ATOMIC_RELAXED);
}
static void eng_ct_regs(u32 r[8])
{
    r[0] = rsx_dsp_reg(&g.rsx, M_SCISSOR_HORIZONTAL); r[1] = rsx_dsp_reg(&g.rsx, M_SCISSOR_VERTICAL);
    r[2] = rsx_dsp_reg(&g.rsx, M_STENCIL_FUNC_REF);   r[3] = rsx_dsp_reg(&g.rsx, M_POLY_OFFSET_FILL);
    r[4] = rsx_dsp_reg(&g.rsx, M_POLY_OFFSET_SCALE);  r[5] = rsx_dsp_reg(&g.rsx, M_POLY_OFFSET_BIAS);
    r[6] = rsx_dsp_reg(&g.rsx, 0x1D78u);              r[7] = rsx_dsp_reg(&g.rsx, 0x1D88u);
}

static void dc_fetch(const rsx_vertex_layout_plan* layout, int allow_remap)
{''')

# the fast path, after indexed/n_draw are known and before the render state decode
c = edit(c, '''    rsx_be_render_state rs;
    rsx_draw_engine_decode_render_state(&g.rsx, &rs);

    u32 targets[RSX_BE_MAX_COLOR_TARGETS];''', '''    /* eng caster fast */
    if (s_plain_caster && s_ct.valid && s_ct.frame == g.frames && eng_ct_on() && dc.vbuf && indexed &&
        dc.im_hit && dc.im_hit->n_draw == n_draw && topology == s_ct.topology && layout.stride == s_ct.stride &&
        prim == s_ct.prim) {
        rsx_be_render_state frs; rsx_dsp_surface fsf; rsx_dsp_viewport fvp; u32 fr[8];
        memset(&fsf, 0, sizeof fsf); memset(&fvp, 0, sizeof fvp);
        rsx_draw_engine_decode_render_state(&g.rsx, &frs);
        rsx_dsp_get_surface(&g.rsx, &fsf);
        rsx_dsp_get_viewport(&g.rsx, &fvp);
        eng_ct_regs(fr);
        const eng_vp_memo* fvm = NULL; const eng_fp_memo* ffm = NULL;
        eng_guest_programs(&fvm, &ffm);
        int same = fvm == s_ct.vpm && ffm == s_ct.fpm && fvm && ffm &&
                   fvm->hash == s_ct.vph && fvm->start == s_ct.vstart && fvm->instrs == s_ct.vinstrs &&
                   ffm->structural == s_ct.fps_ && ffm->loc == s_ct.floc && ffm->off == s_ct.foff && ffm->size == s_ct.fsize &&
                   !memcmp(&frs, &s_ct.rs, sizeof frs) &&
                   !memcmp(&fsf, &s_ct.sf, sizeof fsf) && !memcmp(&fvp, &s_ct.vp, sizeof fvp) && !memcmp(fr, s_ct.regs, sizeof fr) &&
                   s_ct.zslot < g.n_zdepths && g.zdepths[s_ct.zslot].handle == s_ct.depth_handle && g.zdepths[s_ct.zslot].cleared;
        for (u32 i = 0; same && i < s_ct.n_targets; i++) same = g.surfaces[s_ct.surf[i]].handle == s_ct.handles[i];
        if (same) {
            g.be->bind_targets(g.be->user, s_ct.handles, s_ct.n_targets, s_ct.depth_handle);
            g.be->bind_pipeline(g.be->user, s_ct.pipeline);
            g.be->bind_vs_constants_range(g.be->user, g.rsx.constants, s_ct.vpc_lo, s_ct.vpc_n,
                                          s_ct.xf, sizeof s_ct.xf, ENG_VP_CB_BYTES);
            g.be->bind_ps_constants(g.be->user, s_ct.fp_cb, s_ct.fp_bytes);
            g.be->bind_textures(g.be->user, s_ct.textures, s_ct.samplers, s_ct.tex_mask);
            g.be->bind_vertex_textures(g.be->user, s_ct.vtextures, s_ct.vsamplers, s_ct.vtex_mask);
            if (g.be->set_hud) g.be->set_hud(g.be->user, s_ct.hud, s_ct.hud_w);
            g.be->set_viewport(g.be->user, 0.0f, 0.0f, s_ct.W, s_ct.H);
            g.be->set_scissor(g.be->user, s_ct.sc[0], s_ct.sc[1], s_ct.sc[2], s_ct.sc[3]);
            g.be->set_stencil_ref(g.be->user, s_ct.sref);
            eng_apply_depth_bias(fsf.zeta_offset, &frs);
            eng_apply_depth_clip(fsf.zeta_offset, &frs, fvp.scale[1]);
            g.be->draw_vbuf(g.be->user, topology, dc.vbuf, dc.n_verts, layout.stride, dc.im_hit->idx, n_draw);
            g.guest_draws++;
            if (s_pl_on) eng_pl_note(1, 0);   /* eng passlog */
            if (frs.depth_test && frs.depth_write) {
                eng_zdepth* z = &g.zdepths[s_ct.zslot];
                z->had_write = 1; z->stamp = ++s_surf_clock;
                z->snapshot_valid = 0; z->crop_z_valid = 0; z->snapshot_rgba_valid = 0; z->crop_valid = 0;
            }
            s_ct_fast++;
            return;
        }
    }

    rsx_be_render_state rs;
    rsx_draw_engine_decode_render_state(&g.rsx, &rs);

    u32 targets[RSX_BE_MAX_COLOR_TARGETS];''')

# capture hud and scissor arguments on the full path
c = edit(c, '''        g.be->set_hud(g.be->user, hud ? 1 : (s_hud_n && display ? 2 : 0), g.surfaces[target].w);''',
'''        s_ct_hud = hud ? 1 : (s_hud_n && display ? 2 : 0);   /* eng caster fast */
        g.be->set_hud(g.be->user, s_ct_hud, g.surfaces[target].w);''')
c = edit(c, '''        g.be->set_scissor(g.be->user, sx, sy, sw, sh);''', '''        s_ct_sc[0] = sx; s_ct_sc[1] = sy; s_ct_sc[2] = sw; s_ct_sc[3] = sh;   /* eng caster fast */
        g.be->set_scissor(g.be->user, sx, sy, sw, sh);''')

# record the template after a full-path caster draw
c = edit(c, '''    if (zslot != ENG_INVALID && rs.depth_test && rs.depth_write) {
        g.zdepths[zslot].had_write = 1;''', '''    /* eng caster fast: this full-path caster is the next ones' template */
    if (s_plain_caster && eng_ct_on() && dc.vbuf && indexed && dc.im_hit && draw_idx == dc.im_hit->idx && !rie &&
        vpc_range && zslot != ENG_INVALID && n_targets <= RSX_BE_MAX_COLOR_TARGETS && fp_bytes <= ENG_CT_FP_MAX) {
        s_ct.valid = 1; s_ct.frame = g.frames;
        s_ct.rs = rs;
        memset(&s_ct.sf, 0, sizeof s_ct.sf); memset(&s_ct.vp, 0, sizeof s_ct.vp);
        rsx_dsp_get_surface(&g.rsx, &s_ct.sf); rsx_dsp_get_viewport(&g.rsx, &s_ct.vp);
        eng_ct_regs(s_ct.regs);
        s_ct.vpm = NULL; s_ct.fpm = NULL; eng_guest_programs(&s_ct.vpm, &s_ct.fpm);
        if (!s_ct.vpm || !s_ct.fpm) s_ct.valid = 0;
        else { s_ct.vph = s_ct.vpm->hash; s_ct.vstart = s_ct.vpm->start; s_ct.vinstrs = s_ct.vpm->instrs;
               s_ct.fps_ = s_ct.fpm->structural; s_ct.floc = s_ct.fpm->loc; s_ct.foff = s_ct.fpm->off; s_ct.fsize = s_ct.fpm->size; }
        s_ct.topology = topology; s_ct.stride = layout.stride; s_ct.prim = prim;
        s_ct.pipeline = pipeline; s_ct.n_targets = n_targets; s_ct.depth_handle = depth_handle; s_ct.zslot = zslot;
        for (u32 i = 0; i < n_targets; i++) { s_ct.handles[i] = handles[i]; s_ct.surf[i] = targets[i]; }
        memcpy(s_ct.xf, xf, sizeof s_ct.xf); s_ct.vpc_lo = g.vpc_lo; s_ct.vpc_n = g.vpc_n;
        memcpy(s_ct.fp_cb, g.fp_cb, fp_bytes); s_ct.fp_bytes = fp_bytes;
        memcpy(s_ct.textures, textures, sizeof s_ct.textures); memcpy(s_ct.samplers, samplers, sizeof s_ct.samplers); s_ct.tex_mask = tex_mask;
        memcpy(s_ct.vtextures, vtextures, sizeof s_ct.vtextures); memcpy(s_ct.vsamplers, vsamplers, sizeof s_ct.vsamplers); s_ct.vtex_mask = vtex_mask;
        s_ct.hud = s_ct_hud; s_ct.hud_w = g.surfaces[target].w; s_ct.W = W; s_ct.H = H;
        memcpy(s_ct.sc, s_ct_sc, sizeof s_ct.sc); s_ct.sref = rsx_dsp_reg(&g.rsx, M_STENCIL_FUNC_REF) & 0xFFu;
        s_ct_full++;
        { static u32 since; if (++since >= 3000u) { since = 0;
              fprintf(stderr, "[caster fast] %u replayed, %u full-path templates\\n", s_ct_fast, s_ct_full); s_ct_fast = s_ct_full = 0; } }
    } else if (!s_plain_caster) s_ct.valid = 0;   /* another draw in between: the next caster records afresh */

    if (zslot != ENG_INVALID && rs.depth_test && rs.depth_write) {
        g.zdepths[zslot].had_write = 1;''')
open(C, "w").write(c); print("patched")
