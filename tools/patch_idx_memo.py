
# idx memo: an indexed draw whose index bytes, index registers and primitive are those of an
# earlier draw reuses that draw's result: the vertex range (lo, span) and the finished triangle
# indices, skipping the index decode into references, the range remap and the topology index
# write. Crater (DRAWSTATS ds2/dd1c): refs 2.5 ms + remap 3.7-3.9 ms a frame, 4.3M references
# (17 MB of rebuilt indices) for ~13.5k draws, 13.3k of which draw from the vertex cache, i.e.
# the same meshes every frame. Only one-run index draws that took the ranged remap and had no
# restart cut are kept. The index bytes are hashed in full on every draw (64-bit, the vertex
# cache's eng_hash_span), so a changed index buffer is a miss at once. On a hit only refs[0]
# is set; the whole reference list is filled in before anything that reads past it (a wrapping
# element range or a frequency-divided attribute in the fetch plan, a vertex-cache miss, a
# non-indexed fallback). PS3RECOMP_ENG_IDXMEMO=0 = old.
edit("libs/video/rsx_draw_engine.c",
     '''/* The draw accumulator: one BEGIN_END group's batches, references and cuts. */
static struct {''',
     '''/* idx memo: one remembered index result (key fields, index-byte hash, range, indices) */
typedef struct {
    u64 key, content;
    u32 f[8];
    u32 lo, base, span, count, n_draw, idx_cap, last_frame;
    u8 complete;
    u32* idx;
} eng_im_entry;
#define ENG_IM_N 32768u
static eng_im_entry s_im[ENG_IM_N];
static u64 ds_im_hit, ds_im_miss;

/* The draw accumulator: one BEGIN_END group's batches, references and cuts. */
static struct {
    eng_im_entry* im_hit;     /* idx memo: this draw's remembered result */
    eng_im_entry* im_store;   /* idx memo: the entry this draw's result goes into */
    int im_lazy;              /* idx memo: refs[1..] not filled yet */''',
     "idx memo struct")
edit("libs/video/rsx_draw_engine.c",
     '''    dc.inl = NULL;
    dc.inl_bytes = 0;
}''',
     '''    dc.inl = NULL;
    dc.inl_bytes = 0;
    dc.im_hit = dc.im_store = NULL; dc.im_lazy = 0;   /* idx memo */
}''',
     "idx memo reset")
edit("libs/video/rsx_draw_engine.c",
     '''static void dc_fetch(const rsx_vertex_layout_plan* layout, int allow_remap)
{
    const int dso = eng_ds_enabled();
    u64 t0 = dso ? eng_ds_now() : 0, t1;''',
     '''/* idx memo */
static int eng_im_on(void)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3RECOMP_ENG_IDXMEMO"); on = !(e && *e == '0'); }
    return on;
}

/* idx memo: this draw's one index run against the remembered results: dc.im_hit on a match,
 * else dc.im_store = the entry (keyed, not complete) its result goes into. */
static void eng_im_lookup(void)
{
    rsx_dsp_index_array ia;
    rsx_dsp_get_index_array(&g.rsx, &ia);
    const u32 esz = ia.is_u32 ? 4u : 2u;
    const u32 base_index = rsx_dsp_vertex_data_base_index(&g.rsx);
    const int restart_en = rsx_dsp_restart_index_enabled(&g.rsx, ia.is_u32);
    const u32 restart_val = rsx_dsp_restart_index(&g.rsx);
    const u32 ia_loc = ia.location ? RSX_LOCATION_MAIN : RSX_LOCATION_LOCAL;
    const u32 first = dc.idx[0].first, count = dc.idx[0].count;
    const u64 start = (u64)ia.offset + (u64)first * esz, bytes = (u64)count * esz;
    if (start + bytes > 0x100000000ull) return;
    const u8* run = eng_guest_ptr(NULL, ia_loc, (u32)start, (u32)bytes);
    if (!run) return;
    const u32 f[8] = { ia.offset, ia_loc | ((u32)ia.is_u32 << 4) | ((u32)(restart_en != 0) << 5), first, count,
                       base_index, restart_en ? restart_val : 0u, g.rsx.current_primitive, 0x494D454Du };
    const u64 key = eng_fnv1a(f, sizeof f, 1469598103934665603ull);
    const u64 c = eng_hash_span(run, bytes, 0x51ED270B27A3F5E1ull);
    eng_im_entry* e = &s_im[key & (ENG_IM_N - 1u)];
    if (e->complete && e->key == key && !memcmp(e->f, f, sizeof f) && e->content == c) {
        e->last_frame = g.frames;
        dc.im_hit = e;
        ds_im_hit++;
        return;
    }
    e->key = key; memcpy(e->f, f, sizeof f); e->content = c; e->complete = 0;
    dc.im_store = e;
    ds_im_miss++;
}

/* idx memo: the reference list a hit skipped, for a reader past refs[0] */
static int dc_im_fill(void)
{
    if (!dc.im_lazy) return 1;
    const eng_im_entry* e = dc.im_hit;
    if (!dc_reserve_refs(e->span)) return 0;
    for (u32 i = 0; i < e->span; i++) { dc.refs[i].vertex_id = e->lo + i; dc.refs[i].base_index = e->base; }
    dc.im_lazy = 0;
    return 1;
}

static void dc_fetch(const rsx_vertex_layout_plan* layout, int allow_remap)
{
    const int dso = eng_ds_enabled();
    u64 t0 = dso ? eng_ds_now() : 0, t1;
    dc.im_hit = dc.im_store = NULL; dc.im_lazy = 0;   /* idx memo */
    if (allow_remap && eng_im_on() && !dc.n_arr && dc.n_idx == 1 && !dc.inl && dc.idx[0].count > 1 && dc.fetch_ok)
        eng_im_lookup();''',
     "idx memo lookup")
edit("libs/video/rsx_draw_engine.c",
     '''    if (dc.n_idx && dc.fetch_ok) {
        const u32 base_index = rsx_dsp_vertex_data_base_index(&g.rsx);''',
     '''    if (dc.n_idx && dc.fetch_ok && !dc.im_hit) {   /* idx memo: a hit skips the decode */
        const u32 base_index = rsx_dsp_vertex_data_base_index(&g.rsx);''',
     "idx memo skip decode")
edit("libs/video/rsx_draw_engine.c",
     '''    if (!dc.fetch_ok) return;

    dc.n_source_refs = dc.n_refs;''',
     '''    if (!dc.fetch_ok) return;
    if (dc.im_hit) {   /* idx memo: refs[0] now, the rest when something reads them */
        if (!dc_reserve_refs(dc.im_hit->span)) { dc.fetch_ok = 0; return; }
        dc.refs[0].vertex_id = dc.im_hit->lo; dc.refs[0].base_index = dc.im_hit->base;
        dc.n_refs = dc.im_hit->count;
    }

    dc.n_source_refs = dc.n_refs;''',
     "idx memo refs0")
edit("libs/video/rsx_draw_engine.c",
     '''    int consecutive = 0;   /* refs = one run of vertex ids (the ranged remap) */
    if (allow_remap && dc.n_refs > 1) {''',
     '''    int consecutive = 0;   /* refs = one run of vertex ids (the ranged remap) */
    if (dc.im_hit) {   /* idx memo: the ranged remap's result */
        dc.refs_remapped = 1;
        dc.n_refs = dc.im_hit->span;
        consecutive = 1;
        dc.im_lazy = dc.im_hit->span > 1;
    } else if (allow_remap && dc.n_refs > 1) {''',
     "idx memo remap")
edit("libs/video/rsx_draw_engine.c",
     '''    if (dso) { t1 = eng_ds_now(); ds.ns_remap += t1 - t0; t0 = t1; }
    dc.layout = *layout;
    rsx_vertex_fetch_plan_init(&dc.fetch_plan, &g.rsx, layout, eng_guest_ptr, NULL);
    rsx_vertex_fetch_plan_set_inline(&dc.fetch_plan, &g.rsx, dc.inl, dc.inl_bytes);''',
     '''    /* idx memo: keep only a one-run (ranged) result without cuts */
    if (dc.im_store) {
        if (consecutive && !dc.n_cuts) {
            dc.im_store->lo = dc.refs[0].vertex_id; dc.im_store->base = dc.refs[0].base_index;
            dc.im_store->span = dc.n_refs; dc.im_store->count = dc.n_source_refs;
        } else dc.im_store = NULL;
    }
    if (dso) { t1 = eng_ds_now(); ds.ns_remap += t1 - t0; t0 = t1; }
    dc.layout = *layout;
    rsx_vertex_fetch_plan_init(&dc.fetch_plan, &g.rsx, layout, eng_guest_ptr, NULL);
    rsx_vertex_fetch_plan_set_inline(&dc.fetch_plan, &g.rsx, dc.inl, dc.inl_bytes);
    if (dc.im_lazy) {   /* idx memo: prepare_ex walks every reference for these */
        int need = (u64)rsx_vertex_element_index(dc.im_hit->lo, dc.im_hit->base, 0, 0) + dc.n_refs - 1u > 0x000FFFFFu;
        for (u32 slot = 0; slot < layout->count && !need; slot++)
            need = dc.fetch_plan.attr[layout->attrs[slot]].desc.frequency > 1;
        if (need && !dc_im_fill()) { dc.fetch_ok = 0; return; }
    }''',
     "idx memo plan fill")
edit("libs/video/rsx_draw_engine.c",
     '''    if (!dc_reserve_verts((u64)dc.n_refs * layout->stride)) {
        dc.fetch_ok = 0;
        return;
    }''',
     '''    if (!dc_im_fill() || !dc_reserve_verts((u64)dc.n_refs * layout->stride)) {   /* idx memo: fetched from refs */
        dc.fetch_ok = 0;
        return;
    }''',
     "idx memo fetch fill")
edit("libs/video/rsx_draw_engine.c",
     '''    if (dc.vbuf_hit && !indexed) {
        if (!dc_reserve_verts((u64)dc.n_refs * dc.layout.stride) ||''',
     '''    if (dc.vbuf_hit && !indexed) {
        if (!dc_im_fill() ||   /* idx memo */
            !dc_reserve_verts((u64)dc.n_refs * dc.layout.stride) ||''',
     "idx memo nonindexed fill")
edit("libs/video/rsx_draw_engine.c",
     '''    if (indexed) {
        if (!dc_reserve_indices(n_draw)) { eng_drop("reserve_indices", prim); return; }
        rsx_draw_engine_write_topology_indices(
            prim, dc.n_source_refs, dc.cuts, dc.n_cuts,
            dc.refs_remapped ? dc.ref_remap.occurrence_to_unique : NULL,
            g.indices);
    }''',
     '''    const u32* draw_idx = g.indices;   /* idx memo: the remembered indices on a hit */
    if (indexed && dc.im_hit && dc.im_hit->n_draw == n_draw) {
        draw_idx = dc.im_hit->idx;
    } else if (indexed) {
        if (dc.im_hit) { eng_drop("idx_memo", prim); return; }   /* (n_draw is fixed by the key) */
        if (!dc_reserve_indices(n_draw)) { eng_drop("reserve_indices", prim); return; }
        rsx_draw_engine_write_topology_indices(
            prim, dc.n_source_refs, dc.cuts, dc.n_cuts,
            dc.refs_remapped ? dc.ref_remap.occurrence_to_unique : NULL,
            g.indices);
        draw_idx = g.indices;
        if (dc.im_store) {   /* idx memo: keep this result */
            eng_im_entry* e = dc.im_store;
            if (e->idx_cap < n_draw) {
                u32* p = (u32*)realloc(e->idx, (size_t)n_draw * sizeof(u32));
                if (p) { e->idx = p; e->idx_cap = n_draw; }
            }
            if (e->idx_cap >= n_draw) {
                memcpy(e->idx, g.indices, (size_t)n_draw * sizeof(u32));
                e->n_draw = n_draw; e->last_frame = g.frames; e->complete = 1;
            }
        }
    }''',
     "idx memo indices")
edit("libs/video/rsx_draw_engine.c",
     '''        g.be->draw_vbuf(g.be->user, topology, dc.vbuf, uploaded, layout.stride,
                        g.indices, n_draw);
    else
        g.be->draw(g.be->user, topology, dc.verts, uploaded, layout.stride,
                   indexed ? g.indices : NULL, indexed ? n_draw : 0);''',
     '''        g.be->draw_vbuf(g.be->user, topology, dc.vbuf, uploaded, layout.stride,
                        draw_idx, n_draw);   /* idx memo */
    else
        g.be->draw(g.be->user, topology, dc.verts, uploaded, layout.stride,
                   indexed ? draw_idx : NULL, indexed ? n_draw : 0);''',
     "idx memo draw")
edit("libs/video/rsx_draw_engine.c",
     '''                if (ds.span_draws)
            fprintf(stderr, "[drawstats] index ranges:''',
     '''        fprintf(stderr, "[drawstats] idx memo: %llu hits, %llu misses\\n",
                (unsigned long long)ds_im_hit, (unsigned long long)ds_im_miss);
        ds_im_hit = ds_im_miss = 0;
                if (ds.span_draws)
            fprintf(stderr, "[drawstats] index ranges:''',
     "idx memo stats")
