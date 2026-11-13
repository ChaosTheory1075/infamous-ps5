# vk rpmerge: consecutive engine draws into the same targets share one render pass, without a barrier each
VKF = "libs/video/rsx_vulkan_backend.c"
edit(VKF,
     '''static int vk_load_wsi_device_functions(void)
{
    VK_WSI_DEVICE_FNS(LOAD_D)
    return 0;
}''',
     '''static int vk_load_wsi_device_functions(void)
{
    VK_WSI_DEVICE_FNS(LOAD_D)
    return 0;
}

/* Render pass merging (PS3RECOMP_VK_RPMERGE=0 turns it off). Every engine draw was its own render
 * pass with LOAD/STORE and, before it, a full ALL_COMMANDS barrier on its targets: on the GPU a wait
 * for idle and a cache flush per draw, thousands a frame, so the console was GPU-bound in inFAMOUS 1
 * (looking at the sky, with few draws, ran at 20-30 fps). Now a draw into the same render pass,
 * framebuffer and area as the open one, sampling none of its targets, continues it. Every command
 * that may not be recorded inside a render pass closes the open one first: the macros below wrap
 * those entry points (they are loaded above, by name, before these exist). */
static int s_rp_open;                           /* an engine draw's render pass is open on s_vk.cmd */
static VkRenderPass  s_rp_rp;
static VkFramebuffer s_rp_fb;
static u32           s_rp_w, s_rp_h;
static unsigned      s_rp_begun, s_rp_draws;
static int vk_rp_close(void)
{
    if (s_rp_open) { s_rp_open = 0; pvkCmdEndRenderPass(s_vk.cmd); }
    return 0;
}
static int vk_rp_merge(void)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3RECOMP_VK_RPMERGE"); on = !(e && e[0] == '0'); }
    return on;
}
#define pvkCmdPipelineBarrier       (vk_rp_close(), pvkCmdPipelineBarrier)
#define pvkCmdClearColorImage       (vk_rp_close(), pvkCmdClearColorImage)
#define pvkCmdClearDepthStencilImage (vk_rp_close(), pvkCmdClearDepthStencilImage)
#define pvkCmdCopyImageToBuffer     (vk_rp_close(), pvkCmdCopyImageToBuffer)
#define pvkCmdCopyBufferToImage     (vk_rp_close(), pvkCmdCopyBufferToImage)
#define pvkCmdCopyImage             (vk_rp_close(), pvkCmdCopyImage)
#define pvkCmdBlitImage             (vk_rp_close(), pvkCmdBlitImage)
#define pvkCmdBeginRenderPass       (vk_rp_close(), pvkCmdBeginRenderPass)
#define pvkEndCommandBuffer         (vk_rp_close(), pvkEndCommandBuffer)''',
     "vk rpmerge: close")

edit(VKF,
     '''    if (vk_begin()) return;
    /* Everything submitted before is complete (each submission is waited
     * on); this orders memory for the surfaces this draw touches. */
    for (u32 i = 0; i < n; i++)
        vk_barrier_image(s_eobj[s_eng_bound.rt[i]].im.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);
    VkRenderPassBeginInfo rbi = { .sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,
                                  .renderPass = rp, .framebuffer = fb,
                                  .renderArea = { { 0, 0 }, { w, h } } };
    pvkCmdBeginRenderPass(s_vk.cmd, &rbi, VK_SUBPASS_CONTENTS_INLINE);''',
     '''    if (vk_begin()) return;
    /* A draw that samples one of the open pass's targets (directly or through a view of it) needs the
     * barrier between the two: no merging then. */
    int keep = s_rp_open && vk_rp_merge() && s_rp_rp == rp && s_rp_fb == fb && s_rp_w == w && s_rp_h == h;
    for (u32 u = 0; keep && u < RSX_MAX_TEXTURES; u++) {
        if (!((s_e2.tex_mask >> u) & 1u) || !s_e2.tex[u] || s_e2.tex[u] >= VK_ENG_MAX_OBJ) continue;
        const vk_eng_obj* o = &s_eobj[s_e2.tex[u]];
        const u32 t = o->kind == VK_ENG_VIEW ? o->surface : s_e2.tex[u];
        if (t && t == s_eng_bound.depth) keep = 0;
        for (u32 i = 0; i < n; i++) if (t && t == s_eng_bound.rt[i]) keep = 0;
    }
    s_rp_draws++;
    if (!keep) {
        vk_rp_close();
        /* This orders memory for the surfaces this draw touches after everything recorded or
         * submitted before it. */
        for (u32 i = 0; i < n; i++)
            vk_barrier_image(s_eobj[s_eng_bound.rt[i]].im.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);
        VkRenderPassBeginInfo rbi = { .sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,
                                      .renderPass = rp, .framebuffer = fb,
                                      .renderArea = { { 0, 0 }, { w, h } } };
        pvkCmdBeginRenderPass(s_vk.cmd, &rbi, VK_SUBPASS_CONTENTS_INLINE);
        s_rp_open = 1; s_rp_rp = rp; s_rp_fb = fb; s_rp_w = w; s_rp_h = h;
        s_rp_begun++;
    }
    {   static uint64_t t0;
        const uint64_t now = ps3_ft_now();
        if (!t0) t0 = now;
        if (now - t0 >= 10000000000ull) {
            fprintf(stderr, "[vk] render passes: %u for %u draws in %.0f s\\n", s_rp_begun, s_rp_draws, (now - t0) / 1e9);
            s_rp_begun = s_rp_draws = 0; t0 = now;
        } }''',
     "vk rpmerge: draw begin")
edit(VKF,
     '''        pvkCmdDraw(s_vk.cmd, vertex_count, 1, 0, 0);
    }
    pvkCmdEndRenderPass(s_vk.cmd);
    vk_submit_and_wait();
}''',
     '''        pvkCmdDraw(s_vk.cmd, vertex_count, 1, 0, 0);
    }
    if (!vk_rp_merge()) vk_rp_close();        /* else left open for the next draw */
    vk_submit_and_wait();
}''',
     "vk rpmerge: draw end")
