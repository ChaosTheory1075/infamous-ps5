# eng caster fast 2: a replayed caster also skips the vertex fetch (layout, plan, vertex-cache probe).
# Each index-memo entry remembers the vertex-cache entry, its key and buffer, the unique-vertex count and
# the position attribute (offset/stride/type/size) of its last full-path caster draw. Before the layout
# work, a caster into the cull target whose memo entry hits, whose position attribute is the remembered one,
# whose vertex-cache entry still holds that key and buffer, and whose last full check is under 4 frames old
# goes straight to the replay (cull test, state compare, binds, draw). Every 4th frame per entry, and any
# miss, takes the full path, which re-validates the vertex bytes through the cache as before.
# PS3RECOMP_ENG_CASTER_FAST=2 (needs tools/patch_eng_caster_fast.py; 1 = without this part).
import sys
C = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_draw_engine.c"
c = open(C).read()
if "eng caster fast 2" in c: print("already"); sys.exit(0)
def edit(s, old, new):
    if s.count(old) != 1: print("NOT FOUND/UNIQUE:", old[:80]); sys.exit(1)
    return s.replace(old, new)

c = edit(c, '''    u32 ibuf, ibuf_n;   /* resident ib: GPU copy of idx[0..ibuf_n) */
} eng_im_entry;''', '''    u32 ibuf, ibuf_n;   /* resident ib: GPU copy of idx[0..ibuf_n) */
    void* fc_vce; u64 fc_vkey; u32 fc_vbuf, fc_nverts, fc_tag, fc_frame;   /* eng caster fast 2 */
} eng_im_entry;''')
c = edit(c, '''    u32 vbuf;          /* a cached persistent vertex buffer this draw uses, else 0 */''',
'''    u32 vbuf;          /* a cached persistent vertex buffer this draw uses, else 0 */
    void* vce;         /* eng caster fast 2: its vertex-cache entry */''')
c = edit(c, '''            dc.vbuf = ve->vbuf;
            dc.vbuf_hit = 1;''', '''            dc.vbuf = ve->vbuf;
            dc.vce = ve;   /* eng caster fast 2 */
            dc.vbuf_hit = 1;''')
c = edit(c, '''    dc.im_hit = dc.im_store = NULL; dc.im_lazy = 0;   /* idx memo */
    if (allow_remap && eng_im_on()''', '''    dc.im_hit = dc.im_store = NULL; dc.im_lazy = 0;   /* idx memo */
    dc.vce = NULL;   /* eng caster fast 2 */
    if (allow_remap && eng_im_on()''')

# the position attribute's tag, shared by the cull and the fast path
c = edit(c, '''static int s_plain_caster;   /* this draw is a judged plain caster (eng shadow cull) */''',
'''static int s_plain_caster;   /* this draw is a judged plain caster (eng shadow cull) */
static u32 eng_caster_attr_tag(void)   /* eng caster fast 2: attribute 0 and the base index */
{
    rsx_dsp_vertex_attr a; rsx_dsp_get_vertex_attr(&g.rsx, 0, &a);
    return a.offset ^ (a.stride * 2654435761u) ^ (a.location << 30) ^ (a.type << 24) ^ (a.size << 20) ^
           (a.frequency << 12) ^ (rsx_dsp_vertex_data_base_index(&g.rsx) * 40503u);
}''')

# the replay body becomes a function both paths call
c = edit(c, '''    /* eng caster fast */
    if (s_plain_caster && s_ct.valid && s_ct.frame == g.frames && eng_ct_on() && dc.vbuf && indexed &&
        dc.im_hit && dc.im_hit->n_draw == n_draw && topology == s_ct.topology && layout.stride == s_ct.stride &&
        prim == s_ct.prim) {''', '''    /* eng caster fast */
    if (s_plain_caster && s_ct.valid && s_ct.frame == g.frames && eng_ct_on() && dc.vbuf && indexed &&
        dc.im_hit && dc.im_hit->n_draw == n_draw && topology == s_ct.topology && layout.stride == s_ct.stride &&
        prim == s_ct.prim && eng_ct_replay(topology, dc.vbuf, dc.n_verts, dc.im_hit)) {
        if (dc.vce) {   /* eng caster fast 2: what the next replay of this entry may skip the fetch with */
            eng_im_entry* e = dc.im_hit; const eng_vc_entry* v = (const eng_vc_entry*)dc.vce;
            e->fc_vce = dc.vce; e->fc_vkey = v->key; e->fc_vbuf = dc.vbuf; e->fc_nverts = dc.n_verts;
            e->fc_tag = eng_caster_attr_tag(); e->fc_frame = g.frames;
        }
        return;
    }
    if (0) {''')
# define eng_ct_replay before sink_end: extract the old inline block's body into the function
i = c.index('    if (0) {\n        rsx_be_render_state frs;')
j = c.index('            s_ct_fast++;\n            return;\n        }\n    }\n', i)
body = c[i:j + len('            s_ct_fast++;\n            return;\n        }\n    }\n')]
c = c.replace(body, '')
fn = body.replace('    if (0) {\n', '').rsplit('    }\n', 1)[0]
fn = fn.replace('g.be->draw_vbuf(g.be->user, topology, dc.vbuf, dc.n_verts, layout.stride, dc.im_hit->idx, n_draw);',
                'g.be->draw_vbuf(g.be->user, topology, vbuf, n_verts, s_ct.stride, e->idx, e->n_draw);')
fn = fn.replace('            s_ct_fast++;\n            return;\n        }', '            s_ct_fast++;\n            return 1;\n        }')
fn = '''/* eng caster fast: replay the template for this caster; 0 = its inputs differ (take the full path). */
static int eng_ct_replay(rsx_topology topology, u32 vbuf, u32 n_verts, const eng_im_entry* e)
{
    {
''' + fn + '''    }
    return 0;
}

'''
c = edit(c, '''static void sink_end(void* user, const rsx_dispatch* r)''', fn + '''static void sink_end(void* user, const rsx_dispatch* r)''')

# pre-fetch path
c = edit(c, '''    rsx_vertex_layout_plan layout;
    const u64 ds_tl = eng_ds_enabled() ? eng_ds_now() : 0;''', '''    /* eng caster fast 2: a replayed caster needs no layout, plan or vertex-cache probe */
    if (rebuild && s_ct.valid && s_ct.frame == g.frames && __atomic_load_n(&s_ct_on, __ATOMIC_RELAXED) == 2 &&
        topology == s_ct.topology && prim == s_ct.prim && eng_im_on() && !dc.n_arr && dc.n_idx >= 1 && !dc.inl &&
        dc.fetch_ok && (dc.n_idx > 1 || dc.idx[0].count > 1)) {
        dc.im_hit = dc.im_store = NULL; dc.im_lazy = 0; dc.vce = NULL;
        eng_im_lookup();
        eng_im_entry* e = dc.im_hit;
        if (e && e->fc_vce && e->n_draw && g.frames - e->fc_frame < 4u && e->fc_tag == eng_caster_attr_tag() &&
            ((eng_vc_entry*)e->fc_vce)->key == e->fc_vkey && ((eng_vc_entry*)e->fc_vce)->vbuf == e->fc_vbuf) {
            if (eng_shadow_cull_skip()) return;   /* eng shadow cull (judges dc.im_hit) */
            if (s_plain_caster && eng_ct_replay(topology, e->fc_vbuf, e->fc_nverts, e)) { s_ct_fast2++; return; }
        }
    }
    rsx_vertex_layout_plan layout;
    const u64 ds_tl = eng_ds_enabled() ? eng_ds_now() : 0;''')
c = edit(c, '''static volatile int s_ct_on = -1; static unsigned s_ct_fast, s_ct_full;''',
'''static volatile int s_ct_on = -1; static unsigned s_ct_fast, s_ct_full, s_ct_fast2;''')
c = edit(c, '''static void eng_ct_set(int id, int v) { (void)id; __atomic_store_n(&s_ct_on, v > 0, __ATOMIC_RELAXED); s_ct.valid = 0; }''',
'''static void eng_ct_set(int id, int v) { (void)id; __atomic_store_n(&s_ct_on, v > 0 ? v : 0, __ATOMIC_RELAXED); s_ct.valid = 0; }''')
c = edit(c, '''        const char* e = getenv("PS3RECOMP_ENG_CASTER_FAST");
        __atomic_store_n(&s_ct_on, e && *e == '1', __ATOMIC_RELAXED);
        ps3_toggle_watch(PS3T_ENG_CASTER_FAST, eng_ct_set);
        if (e && *e == '1') __atomic_store_n(&s_ct_on, 1, __ATOMIC_RELAXED);   /* the env wins over an absent toggle line */''',
'''        const char* e = getenv("PS3RECOMP_ENG_CASTER_FAST");
        const int v = e ? atoi(e) : 0;
        __atomic_store_n(&s_ct_on, v > 0 ? v : 0, __ATOMIC_RELAXED);
        ps3_toggle_watch(PS3T_ENG_CASTER_FAST, eng_ct_set);
        if (v > 0) __atomic_store_n(&s_ct_on, v, __ATOMIC_RELAXED);   /* the env wins over an absent toggle line */''')
# record the fast-path cache in the memo entry with the template
c = edit(c, '''        s_ct_full++;
        { static u32 since;''', '''        s_ct_full++;
        if (dc.vce) {   /* eng caster fast 2 */
            eng_im_entry* e = dc.im_hit; const eng_vc_entry* v = (const eng_vc_entry*)dc.vce;
            e->fc_vce = dc.vce; e->fc_vkey = v->key; e->fc_vbuf = dc.vbuf; e->fc_nverts = dc.n_verts;
            e->fc_tag = eng_caster_attr_tag(); e->fc_frame = g.frames;
        }
        { static u32 since;''')
c = edit(c, '''              fprintf(stderr, "[caster fast] %u replayed, %u full-path templates\\n", s_ct_fast, s_ct_full); s_ct_fast = s_ct_full = 0; } }''',
'''              fprintf(stderr, "[caster fast] %u replayed (%u without a fetch), %u full-path templates\\n", s_ct_fast, s_ct_fast2, s_ct_full); s_ct_fast = s_ct_full = s_ct_fast2 = 0; } }''')
open(C, "w").write(c); print("patched")
