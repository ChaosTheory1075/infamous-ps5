
# vk dedup: skip per-draw Vulkan state calls that repeat what this command buffer's open render pass
# already has bound. Every engine draw recorded BindPipeline, SetViewport, SetScissor,
# SetStencilReference, BindDescriptorSets, BindVertexBuffers and BindIndexBuffer before the draw:
# crater (run ds2, PS3RECOMP_ENG_DRAWSTATS) 13.5k draws a frame, "backend draw" 14.3 ms of the RSX
# thread's ~58 ms, ~14% of that thread's samples inside libvulkan_radeon (perf, run cr1); GPU wait
# only 2-5 ms/s ([vk] flush sites), so it is CPU recording cost. ~124 draws per render pass
# ([vk] render passes: ~18k for ~2.25M draws per 10 s). The cache is reset whenever a render pass
# begins (any site: the macro) and when a command buffer starts recording, so another draw path's
# binds can never leave it stale. PS3RECOMP_VK_DEDUP=0 = every call recorded (old).
edit("libs/video/rsx_vulkan_backend.c",
     '''#define pvkCmdBeginRenderPass       (vk_rp_close(), pvkCmdBeginRenderPass)''',
     '''/* vk dedup: what the open render pass of the recording command buffer has bound (valid = 0:
 * nothing known). Reset by every render pass begin and every vk_begin. */
static struct {
    int valid;
    VkPipeline pipe;
    VkViewport vp;
    VkRect2D sc;
    u32 sref;
    VkDescriptorSet dset; uint32_t dyn[2];
    VkBuffer vb; VkDeviceSize voff;
    VkBuffer ib; VkDeviceSize ioff;
} s_dd;
static void vk_dd_reset(void) { s_dd.valid = 0; s_dd.ib = VK_NULL_HANDLE; }
static int vk_dd_on(void)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3RECOMP_VK_DEDUP"); on = !(e && e[0] == '0'); }
    return on;
}
#define pvkCmdBeginRenderPass       (vk_rp_close(), vk_dd_reset(), pvkCmdBeginRenderPass)   /* vk dedup */''',
     "vk dedup state")
edit("libs/video/rsx_vulkan_backend.c",
     '''    VK_CHECK(pvkBeginCommandBuffer(s_vk.cmd, &bi), "vkBeginCommandBuffer");
    s_rec = 1;''',
     '''    VK_CHECK(pvkBeginCommandBuffer(s_vk.cmd, &bi), "vkBeginCommandBuffer");
    s_rec = 1;
    vk_dd_reset();   /* vk dedup: a new recording has nothing bound */''',
     "vk dedup begin")
edit("libs/video/rsx_vulkan_backend.c",
     '''    pvkCmdSetViewport(s_vk.cmd, 0, 1, &vp);
    pvkCmdSetScissor(s_vk.cmd, 0, 1, &sc);
    pvkCmdSetStencilReference(s_vk.cmd, VK_STENCIL_FACE_FRONT_AND_BACK, s_e2.stencil_ref & 0xFFu);
    pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_g.pipe_layout,
                             0, 1, &dset, 2, s_dyn);   /* vk dset reuse: dynamic offsets */
    pvkCmdBindVertexBuffers(s_vk.cmd, 0, 1, &vbuf, &voff);
    static int s_nodraw = -1;
    if (s_nodraw < 0) { const char* e = getenv("PS3RECOMP_VK_NODRAW"); s_nodraw = e && e[0] == '1'; }
    if (s_nodraw) {
    } else if (indices && index_count) {
        pvkCmdBindIndexBuffer(s_vk.cmd, ibuf, ioff, VK_INDEX_TYPE_UINT32);
        pvkCmdDrawIndexed(s_vk.cmd, index_count, 1, 0, 0, 0);''',
     '''    /* vk dedup: record only what differs from the open pass's bound state */
    const int dd = vk_dd_on() && s_dd.valid;
    const u32 sref = s_e2.stencil_ref & 0xFFu;
    if (!dd || s_dd.pipe != pipe) pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, pipe);
    if (!dd || memcmp(&s_dd.vp, &vp, sizeof vp)) pvkCmdSetViewport(s_vk.cmd, 0, 1, &vp);
    if (!dd || memcmp(&s_dd.sc, &sc, sizeof sc)) pvkCmdSetScissor(s_vk.cmd, 0, 1, &sc);
    if (!dd || s_dd.sref != sref) pvkCmdSetStencilReference(s_vk.cmd, VK_STENCIL_FACE_FRONT_AND_BACK, sref);
    if (!dd || s_dd.dset != dset || memcmp(s_dd.dyn, s_dyn, sizeof s_dd.dyn))
        pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_g.pipe_layout,
                                 0, 1, &dset, 2, s_dyn);   /* vk dset reuse: dynamic offsets */
    if (!dd || s_dd.vb != vbuf || s_dd.voff != voff) pvkCmdBindVertexBuffers(s_vk.cmd, 0, 1, &vbuf, &voff);
    const int dd_ib = dd && s_dd.ib == ibuf && s_dd.ioff == ioff;
    s_dd.valid = 1; s_dd.pipe = pipe; s_dd.vp = vp; s_dd.sc = sc; s_dd.sref = sref;
    s_dd.dset = dset; memcpy(s_dd.dyn, s_dyn, sizeof s_dd.dyn);
    s_dd.vb = vbuf; s_dd.voff = voff;
    static int s_nodraw = -1;
    if (s_nodraw < 0) { const char* e = getenv("PS3RECOMP_VK_NODRAW"); s_nodraw = e && e[0] == '1'; }
    if (s_nodraw) {
    } else if (indices && index_count) {
        if (!dd_ib) pvkCmdBindIndexBuffer(s_vk.cmd, ibuf, ioff, VK_INDEX_TYPE_UINT32);
        s_dd.ib = ibuf; s_dd.ioff = ioff;
        pvkCmdDrawIndexed(s_vk.cmd, index_count, 1, 0, 0, 0);''',
     "vk dedup draw")
edit("libs/video/rsx_vulkan_backend.c",
     '''    pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, pipe);
    VkViewport vp = { 0.0f, 0.0f, (float)w, (float)h, 0.0f, 1.0f };''',
     '''    VkViewport vp = { 0.0f, 0.0f, (float)w, (float)h, 0.0f, 1.0f };   /* vk dedup: pipeline bound below */''',
     "vk dedup pipeline")
