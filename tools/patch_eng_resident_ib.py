# resident ib: an index-memo hit draws from a GPU copy of its remembered indices. On a hit the engine
# already skips the index decode, but every draw still handed its indices to the backend, which copied
# them into the ring (~8 MB per heavy inFAMOUS 1 frame, ~9k memo hits a frame on the route). Now each memo
# entry keeps a persistent buffer (the vertex cache's slabs, which gain INDEX_BUFFER usage), made on the
# entry's first hit that also has a cached vertex buffer, released when the entry is rewritten. New
# optional backend call draw_vbuf_ib (vertices and indices both resident). Default off (measured ~1.5% of the RSX thread, under the keep bar); PS3RECOMP_ENG_RESIDENT_IB=1 turns it on.
import sys
H = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_draw_engine.h"
C = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_draw_engine.c"
V = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_vulkan_backend.c"
h = open(H).read(); c = open(C).read(); v = open(V).read()
if "resident ib" in c: print("already"); sys.exit(0)
def edit(s, old, new):
    if s.count(old) != 1: print("NOT FOUND/UNIQUE:", old[:80]); sys.exit(1)
    return s.replace(old, new)

h = edit(h, '''    void (*draw_vbuf)(void* user, rsx_topology topology, u32 vbuf,
                      u32 vertex_count, u32 stride, const u32* indices,
                      u32 index_count);''', '''    void (*draw_vbuf)(void* user, rsx_topology topology, u32 vbuf,
                      u32 vertex_count, u32 stride, const u32* indices,
                      u32 index_count);
    /* Optional (resident ib). draw_vbuf with the 32-bit indices also taken
     * from a vbuf_create buffer. */
    void (*draw_vbuf_ib)(void* user, rsx_topology topology, u32 vbuf,
                         u32 vertex_count, u32 stride, u32 ibuf,
                         u32 index_count);''')

# engine: the entry's buffer, released when the entry is rewritten, used on a hit
c = edit(c, '''    float bb[6]; u32 bb_tag, bb_frame; u8 bb_ok;   /* eng shadow cull: position box, its attribute */
} eng_im_entry;''', '''    float bb[6]; u32 bb_tag, bb_frame; u8 bb_ok;   /* eng shadow cull: position box, its attribute */
    u32 ibuf, ibuf_n;   /* resident ib: GPU copy of idx[0..ibuf_n) */
} eng_im_entry;''')
c = edit(c, '''    e->stable = 0; e->sparse = sp;
    e->key = key; memcpy(e->f, f, sizeof f); e->content = c; e->complete = 0;''', '''    e->stable = 0; e->sparse = sp;
    if (e->ibuf) { if (g.be->vbuf_release) g.be->vbuf_release(g.be->user, e->ibuf); e->ibuf = 0; e->ibuf_n = 0; }   /* resident ib */
    e->key = key; memcpy(e->f, f, sizeof f); e->content = c; e->complete = 0;''')
c = edit(c, '''    if (dc.vbuf && indexed)
        g.be->draw_vbuf(g.be->user, topology, dc.vbuf, uploaded, layout.stride,
                        draw_idx, n_draw);   /* idx memo */''', '''    static int rib = -1;   /* resident ib */
    if (rib < 0) { const char* e = getenv("PS3RECOMP_ENG_RESIDENT_IB"); rib = e && *e == '1'; }
    eng_im_entry* const rie = (rib && dc.vbuf && indexed && dc.im_hit && draw_idx == dc.im_hit->idx &&
                               g.be->draw_vbuf_ib && g.be->vbuf_create) ? dc.im_hit : NULL;
    if (rie && rie->ibuf && rie->ibuf_n != n_draw) { if (g.be->vbuf_release) g.be->vbuf_release(g.be->user, rie->ibuf); rie->ibuf = 0; }
    if (rie && !rie->ibuf) { rie->ibuf = g.be->vbuf_create(g.be->user, rie->idx, n_draw * 4u); rie->ibuf_n = rie->ibuf ? n_draw : 0; }
    if (rie && rie->ibuf)
        g.be->draw_vbuf_ib(g.be->user, topology, dc.vbuf, uploaded, layout.stride, rie->ibuf, n_draw);
    else if (dc.vbuf && indexed)
        g.be->draw_vbuf(g.be->user, topology, dc.vbuf, uploaded, layout.stride,
                        draw_idx, n_draw);   /* idx memo */''')

# backend: slabs usable as index buffers, the external index buffer through vk_eng_draw_from
v = edit(v, '''        if (vk_create_host_buffer(&s_vbslab[s].b, size, VK_BUFFER_USAGE_VERTEX_BUFFER_BIT) || !s_vbslab[s].b.coherent) {''',
'''        if (vk_create_host_buffer(&s_vbslab[s].b, size, VK_BUFFER_USAGE_VERTEX_BUFFER_BIT |
                                  VK_BUFFER_USAGE_INDEX_BUFFER_BIT /* resident ib */) || !s_vbslab[s].b.coherent) {''')
v = edit(v, '''static void vk_eng_draw_vbuf(void* user, rsx_topology topology, u32 vbuf, u32 vertex_count, u32 stride,
                             const u32* indices, u32 index_count)
{''', '''static VkBuffer s_xib; static VkDeviceSize s_xib_off;   /* resident ib: the next draw's index buffer */
static void vk_eng_draw_vbuf_ib(void* user, rsx_topology topology, u32 vbuf, u32 vertex_count, u32 stride,
                                u32 ibuf, u32 index_count);
static void vk_eng_draw_vbuf(void* user, rsx_topology topology, u32 vbuf, u32 vertex_count, u32 stride,
                             const u32* indices, u32 index_count)
{''')
v = edit(v, '''static void vk_eng_draw_from(void* user, rsx_topology topology, const void* vertices, u32 vertex_count,
                             u32 stride, const u32* indices, u32 index_count, VkBuffer xbuf, VkDeviceSize xoff)
{''', '''static void vk_eng_draw_vbuf_ib(void* user, rsx_topology topology, u32 vbuf, u32 vertex_count, u32 stride,
                                u32 ibuf, u32 index_count)
{
    if (!vbuf || vbuf > s_vbh_n || !ibuf || ibuf > s_vbh_n || !index_count) return;
    const u32 s = s_vbh[vbuf - 1u].slab, si = s_vbh[ibuf - 1u].slab;
    if (s >= VK_VB_SLABS || !s_vbslab[s].b.buf || si >= VK_VB_SLABS || !s_vbslab[si].b.buf) return;
    s_xib = s_vbslab[si].b.buf; s_xib_off = s_vbh[ibuf - 1u].off;
    vk_eng_draw_from(user, topology, NULL, vertex_count, stride, NULL, index_count,
                     s_vbslab[s].b.buf, s_vbh[vbuf - 1u].off);
}

static void vk_eng_draw_from(void* user, rsx_topology topology, const void* vertices, u32 vertex_count,
                             u32 stride, const u32* indices, u32 index_count, VkBuffer xbuf, VkDeviceSize xoff)
{
    const VkBuffer xib = s_xib; const VkDeviceSize xib_off = s_xib_off;   /* resident ib */
    s_xib = VK_NULL_HANDLE;''')
v = edit(v, '''        vbuf = ibuf = s_ring.buf;
        if (xbuf) { vbuf = xbuf; voff = xoff; }''', '''        vbuf = ibuf = s_ring.buf;
        if (xbuf) { vbuf = xbuf; voff = xoff; }
        if (xib) { ibuf = xib; ioff = xib_off; }   /* resident ib */''')
v = edit(v, '''        vk_eng_write_descriptors();
        vbuf = xbuf; voff = xoff; ibuf = s_e2.indices.buf;''', '''        vk_eng_write_descriptors();
        vbuf = xbuf; voff = xoff; ibuf = s_e2.indices.buf;
        if (xib) { ibuf = xib; ioff = xib_off; }   /* resident ib */''')
v = edit(v, '''    } else if (indices && index_count) {
        if (!dd_ib) pvkCmdBindIndexBuffer(s_vk.cmd, ibuf, ioff, VK_INDEX_TYPE_UINT32);''', '''    } else if ((indices || xib) && index_count) {   /* resident ib */
        if (!dd_ib) pvkCmdBindIndexBuffer(s_vk.cmd, ibuf, ioff, VK_INDEX_TYPE_UINT32);''')
v = edit(v, '''    .draw_vbuf            = vk_eng_draw_vbuf,''', '''    .draw_vbuf            = vk_eng_draw_vbuf,
    .draw_vbuf_ib         = vk_eng_draw_vbuf_ib,   /* resident ib */''')
open(H, "w").write(h); open(C, "w").write(c); open(V, "w").write(v); print("patched")
