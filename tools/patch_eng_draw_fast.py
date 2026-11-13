# eng draw fast: the caster replay generalised to any draw. 60% of inFAMOUS 1's non-caster draws carry exactly
# the previous draw's state and texture registers (86% the state; route measurement, 2026-11-06). A draw from
# the vertex cache with the index memo's indices, whose decoded render state, surface, viewport, scissor/
# stencil/poly-offset/clamp/window registers, program memos (slot + contents), stride, topology, primitive
# AND the raw registers of every texture unit its program samples equal the previous full-path draw's in the
# same frame, replays that draw's binds (targets, pipeline, fragment constants, the same texture handles and
# samplers) with its own vertex constants, vertex buffer and indices. Consecutive draws in one frame cannot
# see a texture re-upload or eviction between them (the previous draw validated those textures this frame).
# Not for depth-bounds draws (the emulation's copy) or programs with vertex textures. Any other draw in
# between ends the template. PS3RECOMP_ENG_DRAW_FAST=1 (live toggle PS3T_ENG_DRAW_FAST).
import sys
C = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_draw_engine.c"
H = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/include/ps3emu/ps3_toggles.h"
c = open(C).read(); h = open(H).read()
if "eng draw fast" in c: print("already"); sys.exit(0)
def edit(s, old, new):
    if s.count(old) != 1: print("NOT FOUND/UNIQUE:", old[:80]); sys.exit(1)
    return s.replace(old, new)

h = edit(h, '''    PS3T_GCM_FAST_WORDS,     /* cellGcmSys.c: plain NV4097 words straight to the draw engine */
    PS3T_COUNT''', '''    PS3T_GCM_FAST_WORDS,     /* cellGcmSys.c: plain NV4097 words straight to the draw engine */
    PS3T_ENG_DRAW_FAST,      /* rsx_draw_engine.c: any draw replayed from the previous one (eng draw fast) */
    PS3T_COUNT''')
h = edit(h, '''        { "PS3_GCM_FAST_WORDS",         PS3_TK_ATOI, 0 },''', '''        { "PS3_GCM_FAST_WORDS",         PS3_TK_ATOI, 0 },
        { "PS3RECOMP_ENG_DRAW_FAST",    PS3_TK_ATOI, 0 },''')

# template + replay, next to the caster one
c = edit(c, '''/* eng caster fast: replay the template for this caster; 0 = its inputs differ (take the full path). */''',
'''/* eng draw fast: the previous full-path draw's inputs and binds (any program) */
static struct {
    int valid; u32 frame;
    rsx_be_render_state rs; rsx_dsp_surface sf; rsx_dsp_viewport vp; u32 regs[8];
    const eng_vp_memo* vpm; const eng_fp_memo* fpm;
    u64 vph, fps_; u32 vstart, vinstrs, floc, foff, fsize;
    rsx_topology topology; u32 stride, prim;
    u32 pipeline, handles[RSX_BE_MAX_COLOR_TARGETS], n_targets, depth_handle, zslot, surf[RSX_BE_MAX_COLOR_TARGETS];
    float xf[8]; u32 vpc_lo, vpc_n;
    u8 fp_cb[ENG_CT_FP_MAX]; u32 fp_bytes;
    u32 textures[RSX_BE_MAX_TEXTURES]; rsx_be_sampler_desc samplers[RSX_BE_MAX_TEXTURES]; u32 tex_mask;
    u32 treg[RSX_BE_MAX_TEXTURES][9];
    int hud; u32 hud_w; float W, H; u32 sc[4]; u32 sref;
} s_dt;
static volatile int s_dt_on = -1; static unsigned s_dt_fast, s_dt_full;
static void eng_dt_set(int id, int v) { (void)id; __atomic_store_n(&s_dt_on, v > 0 ? v : 0, __ATOMIC_RELAXED); s_dt.valid = 0; }
static int eng_dt_on(void)
{
    if (__builtin_expect(s_dt_on < 0, 0)) {
        const char* e = getenv("PS3RECOMP_ENG_DRAW_FAST"); const int v = e ? atoi(e) : 0;
        __atomic_store_n(&s_dt_on, v > 0 ? v : 0, __ATOMIC_RELAXED);
        ps3_toggle_watch(PS3T_ENG_DRAW_FAST, eng_dt_set);
        if (v > 0) __atomic_store_n(&s_dt_on, v, __ATOMIC_RELAXED);
    }
    return __atomic_load_n(&s_dt_on, __ATOMIC_RELAXED);
}
static void eng_dt_tregs(u32 mask, u32 out[RSX_BE_MAX_TEXTURES][9])
{
    for (u32 u = 0; u < RSX_BE_MAX_TEXTURES; u++) {
        if (!((mask >> u) & 1u)) { memset(out[u], 0, sizeof out[u]); continue; }
        for (u32 k = 0; k < 8; k++) out[u][k] = rsx_dsp_reg(&g.rsx, 0x1A00u + u * 0x20u + k * 4u);
        out[u][8] = rsx_dsp_reg(&g.rsx, 0x1840u + u * 4u);
    }
}
static int eng_dt_replay(rsx_topology topology, u32 vbuf, u32 n_verts, const eng_im_entry* e)
{
    rsx_be_render_state frs; rsx_dsp_surface fsf; rsx_dsp_viewport fvp; u32 fr[8];
    memset(&fsf, 0, sizeof fsf); memset(&fvp, 0, sizeof fvp);
    rsx_draw_engine_decode_render_state(&g.rsx, &frs);
    rsx_dsp_get_surface(&g.rsx, &fsf);
    rsx_dsp_get_viewport(&g.rsx, &fvp);
    eng_ct_regs(fr);
    const eng_vp_memo* fvm = NULL; const eng_fp_memo* ffm = NULL;
    eng_guest_programs(&fvm, &ffm);
    int same = fvm == s_dt.vpm && ffm == s_dt.fpm && fvm && ffm &&
               fvm->hash == s_dt.vph && fvm->start == s_dt.vstart && fvm->instrs == s_dt.vinstrs &&
               ffm->structural == s_dt.fps_ && ffm->loc == s_dt.floc && ffm->off == s_dt.foff && ffm->size == s_dt.fsize &&
               !memcmp(&frs, &s_dt.rs, sizeof frs) &&
               !memcmp(&fsf, &s_dt.sf, sizeof fsf) && !memcmp(&fvp, &s_dt.vp, sizeof fvp) && !memcmp(fr, s_dt.regs, sizeof fr) &&
               s_dt.zslot < g.n_zdepths && g.zdepths[s_dt.zslot].handle == s_dt.depth_handle && g.zdepths[s_dt.zslot].cleared;
    for (u32 i = 0; same && i < s_dt.n_targets; i++) same = g.surfaces[s_dt.surf[i]].handle == s_dt.handles[i];
    if (same) {
        u32 tr[RSX_BE_MAX_TEXTURES][9];
        eng_dt_tregs(s_dt.tex_mask, tr);
        same = !memcmp(tr, s_dt.treg, sizeof tr);
    }
    if (!same) return 0;
    g.be->bind_targets(g.be->user, s_dt.handles, s_dt.n_targets, s_dt.depth_handle);
    g.be->bind_pipeline(g.be->user, s_dt.pipeline);
    g.be->bind_vs_constants_range(g.be->user, g.rsx.constants, s_dt.vpc_lo, s_dt.vpc_n,
                                  s_dt.xf, sizeof s_dt.xf, ENG_VP_CB_BYTES);
    g.be->bind_ps_constants(g.be->user, s_dt.fp_cb, s_dt.fp_bytes);
    g.be->bind_textures(g.be->user, s_dt.textures, s_dt.samplers, s_dt.tex_mask);
    { u32 vt[RSX_BE_MAX_VERTEX_TEXTURES] = { 0 }; rsx_be_sampler_desc vs[RSX_BE_MAX_VERTEX_TEXTURES];
      memset(vs, 0, sizeof vs); g.be->bind_vertex_textures(g.be->user, vt, vs, 0); }
    if (g.be->set_hud) g.be->set_hud(g.be->user, s_dt.hud, s_dt.hud_w);
    g.be->set_viewport(g.be->user, 0.0f, 0.0f, s_dt.W, s_dt.H);
    g.be->set_scissor(g.be->user, s_dt.sc[0], s_dt.sc[1], s_dt.sc[2], s_dt.sc[3]);
    g.be->set_stencil_ref(g.be->user, s_dt.sref);
    eng_apply_depth_bias(fsf.zeta_offset, &frs);
    eng_apply_depth_clip(fsf.zeta_offset, &frs, fvp.scale[1]);
    g.be->draw_vbuf(g.be->user, topology, vbuf, n_verts, s_dt.stride, e->idx, e->n_draw);
    g.guest_draws++;
    if (s_pl_on) eng_pl_note(1, 0);   /* eng passlog */
    if (frs.depth_test && frs.depth_write) {
        eng_zdepth* z = &g.zdepths[s_dt.zslot];
        z->had_write = 1; z->stamp = ++s_surf_clock;
        z->snapshot_valid = 0; z->crop_z_valid = 0; z->snapshot_rgba_valid = 0; z->crop_valid = 0;
    }
    s_dt_fast++;
    return 1;
}

/* eng caster fast: replay the template for this caster; 0 = its inputs differ (take the full path). */''')

# replay site: right after the caster replay site
c = edit(c, '''    rsx_be_render_state rs;
    rsx_draw_engine_decode_render_state(&g.rsx, &rs);

    u32 targets[RSX_BE_MAX_COLOR_TARGETS];''', '''    /* eng draw fast */
    if (!s_plain_caster && s_dt.valid && s_dt.frame == g.frames && eng_dt_on() && dc.vbuf && indexed &&
        dc.im_hit && dc.im_hit->n_draw == n_draw && topology == s_dt.topology && layout.stride == s_dt.stride &&
        prim == s_dt.prim && eng_dt_replay(topology, dc.vbuf, dc.n_verts, dc.im_hit)) return;

    rsx_be_render_state rs;
    rsx_draw_engine_decode_render_state(&g.rsx, &rs);

    u32 targets[RSX_BE_MAX_COLOR_TARGETS];''')

# record after a full-path non-caster draw; any other draw ends it
c = edit(c, '''    } else if (!s_plain_caster) s_ct.valid = 0;   /* another draw in between: the next caster records afresh */''',
'''    } else if (!s_plain_caster) s_ct.valid = 0;   /* another draw in between: the next caster records afresh */
    /* eng draw fast: this full-path draw is the next ones' template */
    if (!s_plain_caster && eng_dt_on() && dc.vbuf && indexed && dc.im_hit && draw_idx == dc.im_hit->idx && !rie &&
        vpc_range && zslot != ENG_INVALID && n_targets <= RSX_BE_MAX_COLOR_TARGETS && fp_bytes <= ENG_CT_FP_MAX &&
        !s_dbz.unit && !vtex_mask) {
        s_dt.valid = 1; s_dt.frame = g.frames; s_dt.rs = rs;
        memset(&s_dt.sf, 0, sizeof s_dt.sf); memset(&s_dt.vp, 0, sizeof s_dt.vp);
        rsx_dsp_get_surface(&g.rsx, &s_dt.sf); rsx_dsp_get_viewport(&g.rsx, &s_dt.vp);
        eng_ct_regs(s_dt.regs);
        s_dt.vpm = NULL; s_dt.fpm = NULL; eng_guest_programs(&s_dt.vpm, &s_dt.fpm);
        if (!s_dt.vpm || !s_dt.fpm) s_dt.valid = 0;
        else { s_dt.vph = s_dt.vpm->hash; s_dt.vstart = s_dt.vpm->start; s_dt.vinstrs = s_dt.vpm->instrs;
               s_dt.fps_ = s_dt.fpm->structural; s_dt.floc = s_dt.fpm->loc; s_dt.foff = s_dt.fpm->off; s_dt.fsize = s_dt.fpm->size; }
        s_dt.topology = topology; s_dt.stride = layout.stride; s_dt.prim = prim;
        s_dt.pipeline = pipeline; s_dt.n_targets = n_targets; s_dt.depth_handle = depth_handle; s_dt.zslot = zslot;
        for (u32 i = 0; i < n_targets; i++) { s_dt.handles[i] = handles[i]; s_dt.surf[i] = targets[i]; }
        memcpy(s_dt.xf, xf, sizeof s_dt.xf); s_dt.vpc_lo = g.vpc_lo; s_dt.vpc_n = g.vpc_n;
        memcpy(s_dt.fp_cb, g.fp_cb, fp_bytes); s_dt.fp_bytes = fp_bytes;
        memcpy(s_dt.textures, textures, sizeof s_dt.textures); memcpy(s_dt.samplers, samplers, sizeof s_dt.samplers);
        s_dt.tex_mask = tex_mask; eng_dt_tregs(tex_mask, s_dt.treg);
        s_dt.hud = s_ct_hud; s_dt.hud_w = g.surfaces[target].w; s_dt.W = W; s_dt.H = H;
        memcpy(s_dt.sc, s_ct_sc, sizeof s_dt.sc); s_dt.sref = rsx_dsp_reg(&g.rsx, M_STENCIL_FUNC_REF) & 0xFFu;
        s_dt_full++;
        { static u32 since; if (++since >= 3000u) { since = 0;
              fprintf(stderr, "[draw fast] %u replayed, %u full-path templates\\n", s_dt_fast, s_dt_full); s_dt_fast = s_dt_full = 0; } }
    } else s_dt.valid = 0;''')
open(C, "w").write(c); open(H, "w").write(h); print("patched")
