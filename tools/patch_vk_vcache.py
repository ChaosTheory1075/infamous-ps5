# vk vcache: the engine's vertex cache on Vulkan (vbuf hooks), present readback only when needed, bigger ring
edit("libs/video/rsx_vulkan_backend.c",
     '''#define VK_RING_BYTES   (128u << 20)
#define VK_DPOOL_SETS   4096u''',
     '''/* 128 MB / 4096 sets filled up once a frame in the console's inFAMOUS worlds, and each time is a
 * vk_flush: a submission and a wait for the GPU in the middle of the frame. */
#define VK_RING_BYTES   (256u << 20)
#define VK_DPOOL_SETS   16384u''',
     "vk vcache: ring size")
edit("libs/video/rsx_vulkan_backend.c",
     '''    VkDeviceSize vs_off, ps_off;
    void* v = vk_ring_alloc(vbytes, 16, voff);
    memcpy(v, vertices, (size_t)vbytes);''',
     '''    VkDeviceSize vs_off, ps_off;
    void* v = vk_ring_alloc(vbytes, 16, voff);
    if (vbytes) memcpy(v, vertices, (size_t)vbytes);   /* 0: a cached vertex buffer (draw_vbuf) */''',
     "vk vcache: ring skip")

# vk_eng_draw -> vk_eng_draw_from with an optional vertex buffer of the engine's vertex cache
edit("libs/video/rsx_vulkan_backend.c",
     '''static void vk_eng_draw(void* user, rsx_topology topology, const void* vertices, u32 vertex_count,
                        u32 stride, const u32* indices, u32 index_count)
{
    (void)user;
    if (!s_e2.pipeline || !vertices || !vertex_count || !stride) return;''',
     '''static void vk_eng_draw_from(void* user, rsx_topology topology, const void* vertices, u32 vertex_count,
                             u32 stride, const u32* indices, u32 index_count, VkBuffer xbuf, VkDeviceSize xoff);
static void vk_eng_draw(void* user, rsx_topology topology, const void* vertices, u32 vertex_count,
                        u32 stride, const u32* indices, u32 index_count)
{
    vk_eng_draw_from(user, topology, vertices, vertex_count, stride, indices, index_count, VK_NULL_HANDLE, 0);
}

/* The engine's vertex cache (rsx_draw_engine.c, PS3RECOMP_ENG_VCACHE): decoded vertices of
 * geometry that did not change between frames live in persistent buffers and are drawn from there,
 * not fetched, decoded and copied into the ring again every frame. Without these hooks the cache
 * stayed off on Vulkan. Buffers are carved from 32 MB host-visible slabs (one allocation each, not
 * one per mesh); a slab is freed when its last buffer is released, through vk_destroy_buffer, which
 * keeps it until the batch that may still draw from it is submitted. */
#define VK_VB_SLAB   (32u << 20)
#define VK_VB_SLABS  256u
#define VK_VB_MAX    65536u
static struct { vk_buffer b; VkDeviceSize used; u32 live; } s_vbslab[VK_VB_SLABS];
static u32 s_vbslab_cur = VK_VB_SLABS;           /* the slab new buffers come from */
static struct { u32 slab; VkDeviceSize off; } s_vbh[VK_VB_MAX];
static u32 s_vbh_free[VK_VB_MAX], s_vbh_nfree, s_vbh_n;

static void vk_vb_slab_drop(u32 s)
{
    vk_destroy_buffer(&s_vbslab[s].b);
    s_vbslab[s].used = 0; s_vbslab[s].live = 0;
    if (s_vbslab_cur == s) s_vbslab_cur = VK_VB_SLABS;
}

static u32 vk_eng_vbuf_create(void* user, const void* data, u32 bytes)
{
    (void)user;
    if (!s_vk.device || !data || !bytes) return 0;
    const VkDeviceSize need = ((VkDeviceSize)bytes + 255u) & ~(VkDeviceSize)255u;
    u32 s = s_vbslab_cur;
    if (s >= VK_VB_SLABS || !s_vbslab[s].b.buf || s_vbslab[s].used + need > s_vbslab[s].b.size) {
        s = VK_VB_SLABS;
        for (u32 i = 0; i < VK_VB_SLABS; i++) if (!s_vbslab[i].b.buf) { s = i; break; }
        if (s == VK_VB_SLABS) return 0;
        const VkDeviceSize size = need > VK_VB_SLAB ? need : VK_VB_SLAB;
        if (vk_create_host_buffer(&s_vbslab[s].b, size, VK_BUFFER_USAGE_VERTEX_BUFFER_BIT) || !s_vbslab[s].b.coherent) {
            if (s_vbslab[s].b.buf) vk_destroy_buffer(&s_vbslab[s].b);
            memset(&s_vbslab[s], 0, sizeof s_vbslab[s]);
            return 0;
        }
        s_vbslab[s].used = 0; s_vbslab[s].live = 0;
        if (need <= VK_VB_SLAB) s_vbslab_cur = s;    /* an outsized one stays its buffer's alone */
    }
    u32 h;
    if (s_vbh_nfree) h = s_vbh_free[--s_vbh_nfree];
    else if (s_vbh_n < VK_VB_MAX) h = s_vbh_n++;
    else return 0;
    s_vbh[h].slab = s; s_vbh[h].off = s_vbslab[s].used;
    memcpy((u8*)s_vbslab[s].b.ptr + s_vbslab[s].used, data, bytes);
    s_vbslab[s].used += need;
    s_vbslab[s].live++;
    return h + 1u;
}

static void vk_eng_vbuf_release(void* user, u32 vbuf)
{
    (void)user;
    if (!vbuf || vbuf > s_vbh_n) return;
    const u32 h = vbuf - 1u, s = s_vbh[h].slab;
    if (s >= VK_VB_SLABS || !s_vbslab[s].b.buf) return;
    s_vbh[h].slab = VK_VB_SLABS;
    s_vbh_free[s_vbh_nfree++] = h;
    if (s_vbslab[s].live && --s_vbslab[s].live == 0) vk_vb_slab_drop(s);
}

static void vk_eng_draw_vbuf(void* user, rsx_topology topology, u32 vbuf, u32 vertex_count, u32 stride,
                             const u32* indices, u32 index_count)
{
    if (!vbuf || vbuf > s_vbh_n) return;
    const u32 s = s_vbh[vbuf - 1u].slab;
    if (s >= VK_VB_SLABS || !s_vbslab[s].b.buf) return;
    vk_eng_draw_from(user, topology, NULL, vertex_count, stride, indices, index_count,
                     s_vbslab[s].b.buf, s_vbh[vbuf - 1u].off);
}

static void vk_eng_draw_from(void* user, rsx_topology topology, const void* vertices, u32 vertex_count,
                             u32 stride, const u32* indices, u32 index_count, VkBuffer xbuf, VkDeviceSize xoff)
{
    (void)user;
    if (!s_e2.pipeline || (!vertices && !xbuf) || !vertex_count || !stride) return;''',
     "vk vcache: draw_from")
edit("libs/video/rsx_vulkan_backend.c",
     '''    const VkDeviceSize vbytes = (VkDeviceSize)vertex_count * stride;
    VkBuffer vbuf, ibuf;
    VkDeviceSize voff = 0, ioff = 0;
    if (vk_batching()) {
        if (vk_batch_draw_begin(vertices, vbytes, indices,
                                (indices && index_count) ? (VkDeviceSize)index_count * 4u : 0, &voff, &ioff))
            return;
        vbuf = ibuf = s_ring.buf;
    } else {
        if (vk_ensure_vertex_buffer(vbytes)) return;
        memcpy(s_vk.vertices.ptr, vertices, (size_t)vbytes);''',
     '''    const VkDeviceSize vbytes = xbuf ? 0 : (VkDeviceSize)vertex_count * stride;
    VkBuffer vbuf, ibuf;
    VkDeviceSize voff = 0, ioff = 0;
    if (vk_batching()) {
        if (vk_batch_draw_begin(vertices, vbytes, indices,
                                (indices && index_count) ? (VkDeviceSize)index_count * 4u : 0, &voff, &ioff))
            return;
        vbuf = ibuf = s_ring.buf;
        if (xbuf) { vbuf = xbuf; voff = xoff; }
    } else if (xbuf) {
        if (indices && index_count) {
            if (vk_eng_ensure_indices((VkDeviceSize)index_count * 4u)) return;
            memcpy(s_e2.indices.ptr, indices, (size_t)index_count * 4u);
        }
        vk_eng_write_descriptors();
        vbuf = xbuf; voff = xoff; ibuf = s_e2.indices.buf;
    } else {
        if (vk_ensure_vertex_buffer(vbytes)) return;
        memcpy(s_vk.vertices.ptr, vertices, (size_t)vbytes);''',
     "vk vcache: draw_from body")
edit("libs/video/rsx_vulkan_backend.c",
     '''    .draw                 = vk_eng_draw,''',
     '''    .draw                 = vk_eng_draw,
    .vbuf_create          = vk_eng_vbuf_create,
    .vbuf_release         = vk_eng_vbuf_release,
    .draw_vbuf            = vk_eng_draw_vbuf,''',
     "vk vcache: hooks")

# present: the whole frame was copied to the CPU and waited for every frame, for one diagnostic pixel
edit("libs/video/rsx_vulkan_backend.c",
     '''static void vk_dump_ppm(const unsigned char* rgba)
{
    static double every = -1;
    static unsigned long long last_ns;''',
     '''static unsigned long long s_dump_last_ns;
/* Whether this present reads the frame back: always headless (the readback is the output) or with a
 * per-frame dump; in a window only when a timed dump or a debugger's shot is due, and every
 * 64th frame so last_center stays roughly current. Every other window present skips a full copy of
 * the frame and a wait for the GPU. */
static int vk_readback_due(void)
{
    if (!s_vk.windowed || !s_vk.swapchain) return 1;
    if ((s_vk.presented & 63u) == 0 || g_vk_dump_now) return 1;
    if (!s_vk.dump_path) return 0;
    static double every = -1;
    if (every < 0) { const char* e = getenv("PS3RECOMP_VK_DUMP_EVERY"); every = e ? atof(e) : 0; }
    if (every <= 0) return 1;
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    const unsigned long long now = (unsigned long long)ts.tv_sec * 1000000000ull + (unsigned long long)ts.tv_nsec;
    return !s_dump_last_ns || now - s_dump_last_ns >= (unsigned long long)(every * 1e9);
}
static void vk_dump_ppm(const unsigned char* rgba)
{
    static double every = -1;
#define last_ns s_dump_last_ns''',
     "vk vcache: readback due")
edit("libs/video/rsx_vulkan_backend.c",
     '''        snprintf(path, sizeof path, "%s.%03u.ppm", s_vk.dump_path, seq++ % 200u);''',
     '''        snprintf(path, sizeof path, "%s.%03u.ppm", s_vk.dump_path, seq++ % 200u);
#undef last_ns''',
     "vk vcache: readback due end")
edit("libs/video/rsx_vulkan_backend.c",
     '''    (void)ud; (void)buffer_id;
    if (!s_vk.device) return;

    if (vk_begin()) return;
    vk_barrier_image(s_vk.color.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);''',
     '''    (void)ud; (void)buffer_id;
    if (!s_vk.device) return;

    if (!vk_readback_due()) {
        s_vk.presented++;
        s_g.last_draws = s_g.draws;
        s_g.draws = 0;
        vk_present_window();
        return;
    }
    if (vk_begin()) return;
    vk_barrier_image(s_vk.color.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);''',
     "vk vcache: present skip")
