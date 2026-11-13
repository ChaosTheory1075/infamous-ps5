# vk async: two frames in flight -- a window present submits the frame and goes on recording the next
VKF = "libs/video/rsx_vulkan_backend.c"
edit(VKF,
     '''static VkDescriptorSet  s_wd_set;               /* this draw's set / ring slice, or 0      */''',
     '''/* Frames in flight (PS3RECOMP_VK_ASYNC=0 turns it off): a window present submits the frame and the
 * next one is recorded while the GPU draws it, instead of the CPU waiting for the GPU at every
 * present (a quarter to a third of the console's frame time in all three games). What a submission
 * uses that the CPU writes or frees -- command buffer, fence, acquire semaphore, ring, descriptor
 * pool, the objects released while it was recorded -- belongs to one of two slots; a present waits
 * only for the older slot, and a forced flush (the engine reading results) still waits for all. */
#define VK_SLOTS 2
typedef struct { u8 kind; uint64_t h; } vk_gobj;   /* 1 pipeline, 2 shader module, 3 framebuffer */
#define VK_GOBJ_MAX 4096
typedef struct {
    VkCommandBuffer cmd; VkFence fence; VkSemaphore acq;
    vk_buffer ring; VkDescriptorPool dpool;
    int pending;
    vk_buffer* gbuf; u32 ngbuf;
    vk_image* gimg; u32 ngimg;
    vk_gobj* gobj; u32 ngobj;
} vk_slot;
static vk_slot s_slot[VK_SLOTS];
static u32 s_cur;
static int s_inflight;                          /* the other slot is submitted and not waited for */
static int s_async_ready;                       /* slots set up */
static vk_gobj s_gobj[VK_GOBJ_MAX];
static u32 s_ngobj;
static VkDescriptorSet  s_wd_set;               /* this draw's set / ring slice, or 0      */''',
     "vk async: slots")

edit(VKF,
     '''    if (s_rec && vk_batching() && s_ngimg < VK_GARBAGE_MAX && (im->img || im->view)) {''',
     '''    if ((s_rec || s_inflight) && vk_batching() && s_ngimg < VK_GARBAGE_MAX && (im->img || im->view)) {''',
     "vk async: image garbage")
edit(VKF,
     '''    if (s_rec && vk_batching() && s_ngbuf < VK_GARBAGE_MAX && b->buf) {''',
     '''    if ((s_rec || s_inflight) && vk_batching() && s_ngbuf < VK_GARBAGE_MAX && b->buf) {''',
     "vk async: buffer garbage")

edit(VKF,
     '''    s_ngimg = 0;
    s_ring_off = 0;
    if (s_dpool && s_dsets) { pvkResetDescriptorPool(s_vk.device, s_dpool, 0); s_dsets = 0; }
}''',
     '''    s_ngimg = 0;
    vk_gobj_free(s_gobj, &s_ngobj);
    s_ring_off = 0;
    if (s_dpool && s_dsets) { pvkResetDescriptorPool(s_vk.device, s_dpool, 0); s_dsets = 0; }
}

/* A slot whose submission has completed: free what was released while it was recorded. */
static void vk_slot_free(vk_slot* S)
{
    for (u32 i = 0; i < S->ngbuf; i++) {
        vk_buffer* b = &S->gbuf[i];
        if (b->ptr) pvkUnmapMemory(s_vk.device, b->mem);
        if (b->buf) pvkDestroyBuffer(s_vk.device, b->buf, NULL);
        if (b->mem) pvkFreeMemory(s_vk.device, b->mem, NULL);
    }
    S->ngbuf = 0;
    for (u32 i = 0; i < S->ngimg; i++) {
        vk_image* im = &S->gimg[i];
        if (im->view) pvkDestroyImageView(s_vk.device, im->view, NULL);
        if (im->img)  pvkDestroyImage(s_vk.device, im->img, NULL);
        if (im->mem)  pvkFreeMemory(s_vk.device, im->mem, NULL);
    }
    S->ngimg = 0;
    vk_gobj_free(S->gobj, &S->ngobj);
    S->pending = 0;
}

/* The other slot's submission is complete (a wait for a later one returned, or its own fence). */
static void vk_slots_retire(void)
{
    for (u32 i = 0; i < VK_SLOTS; i++)
        if (i != s_cur && s_slot[i].pending) vk_slot_free(&s_slot[i]);
    s_inflight = 0;
}''',
     "vk async: slot free")

# vk_gobj_free has to come before vk_batch_after_flush
edit(VKF,
     '''/* After a real submission: free what was released while recording, restart the ring and pool. */''',
     '''static void vk_gobj_free(vk_gobj* g, u32* n)
{
    for (u32 i = 0; i < *n; i++) {
        if (g[i].kind == 1) pvkDestroyPipeline(s_vk.device, (VkPipeline)(uintptr_t)g[i].h, NULL);
        else if (g[i].kind == 2) pvkDestroyShaderModule(s_vk.device, (VkShaderModule)(uintptr_t)g[i].h, NULL);
        else if (g[i].kind == 3) pvkDestroyFramebuffer(s_vk.device, (VkFramebuffer)(uintptr_t)g[i].h, NULL);
    }
    *n = 0;
}

/* A pipeline, shader module or framebuffer the open command buffer or a submission in flight may still
 * use: destroyed once that is complete, like vk_destroy_image. 0: destroy it now. */
static int vk_gobj_defer(u8 kind, uint64_t h)
{
    if (!h || !((s_rec || s_inflight) && vk_batching()) || s_ngobj >= VK_GOBJ_MAX) return 0;
    s_gobj[s_ngobj].kind = kind; s_gobj[s_ngobj].h = h; s_ngobj++;
    return 1;
}

/* After a real submission: free what was released while recording, restart the ring and pool. */''',
     "vk async: gobj")

edit(VKF,
     '''static int vk_submit_and_wait_at(int line)
{
    if (!s_rec) return 0;''',
     '''static int vk_submit_and_wait_at(int line)
{
    if (!s_rec) {
        /* Nothing recorded, but the engine may be about to read what an in-flight frame wrote. */
        if (s_force && s_inflight) {
            const uint64_t ft0 = ps3_ft_now();
            for (u32 i = 0; i < VK_SLOTS; i++)
                if (i != s_cur && s_slot[i].pending)
                    pvkWaitForFences(s_vk.device, 1, &s_slot[i].fence, VK_TRUE, UINT64_MAX);
            const uint64_t ft1 = ps3_ft_now();
            if (PS3_FT_ON()) ps3_ft_span(PS3_FT_GPU_WAIT, 0, 0u, (uint32_t)line, ft0, ft1);
            vk_flush_note(line, ft1 - ft0);
            vk_slots_retire();
        }
        return 0;
    }''',
     "vk async: idle forced flush")
edit(VKF,
     '''    if (PS3_FT_ON()) ps3_ft_span(PS3_FT_GPU_WAIT, 0, s_force ? 0u : 1u, (uint32_t)line, ft0, ft1);
    vk_flush_note(line, ft1 - ft0);
    vk_batch_after_flush();
    return 0;
}''',
     '''    if (PS3_FT_ON()) ps3_ft_span(PS3_FT_GPU_WAIT, 0, s_force ? 0u : 1u, (uint32_t)line, ft0, ft1);
    vk_flush_note(line, ft1 - ft0);
    if (s_inflight) vk_slots_retire();          /* the queue is in order: older work is done too */
    vk_batch_after_flush();
    return 0;
}''',
     "vk async: flush retires")

# the asynchronous window present
edit(VKF,
     '''/* Blit the offscreen target into the next swapchain image and present it. */
static void vk_present_window(void)
{
    if (!s_vk.windowed || !s_vk.swapchain) return;
''',
     '''static int vk_async(void)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3RECOMP_VK_ASYNC"); on = !(e && e[0] == '0'); }
    return on && vk_batching() && s_vk.windowed && s_vk.swapchain;
}

static int vk_async_setup(void)
{
    if (s_async_ready) return s_async_ready > 0;
    s_async_ready = -1;
    for (u32 i = 0; i < VK_SLOTS; i++) {
        vk_slot* S = &s_slot[i];
        S->gbuf = (vk_buffer*)calloc(VK_GARBAGE_MAX, sizeof *S->gbuf);
        S->gimg = (vk_image*)calloc(VK_GARBAGE_MAX, sizeof *S->gimg);
        S->gobj = (vk_gobj*)calloc(VK_GOBJ_MAX, sizeof *S->gobj);
        if (!S->gbuf || !S->gimg || !S->gobj) { VK_LOG("async: out of memory\\n"); return 0; }
        if (i == 0) { S->cmd = s_vk.cmd; S->fence = s_vk.fence; S->acq = s_vk.sem_acquire; continue; }
        VkCommandBufferAllocateInfo cai = { .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
                                            .commandPool = s_vk.pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
                                            .commandBufferCount = 1 };
        VkFenceCreateInfo fci = { .sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO };
        VkSemaphoreCreateInfo semi = { .sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO };
        if (pvkAllocateCommandBuffers(s_vk.device, &cai, &S->cmd) != VK_SUCCESS ||
            pvkCreateFence(s_vk.device, &fci, NULL, &S->fence) != VK_SUCCESS ||
            pvkCreateSemaphore(s_vk.device, &semi, NULL, &S->acq) != VK_SUCCESS) {
            VK_LOG("async: no second command buffer / fence / semaphore; presents stay synchronous\\n");
            return 0;
        }
    }
    s_cur = 0;
    s_async_ready = 1;
    VK_LOG("async: %u frames in flight\\n", VK_SLOTS);
    return 1;
}

/* After an asynchronous present: the frame just submitted keeps its slot; recording moves to the other
 * one, once its older submission is complete. */
static void vk_slot_rotate(void)
{
    vk_slot* S = &s_slot[s_cur];
    S->ring = s_ring; S->dpool = s_dpool;
    memcpy(S->gbuf, s_gbuf, s_ngbuf * sizeof *s_gbuf); S->ngbuf = s_ngbuf; s_ngbuf = 0;
    memcpy(S->gimg, s_gimg, s_ngimg * sizeof *s_gimg); S->ngimg = s_ngimg; s_ngimg = 0;
    memcpy(S->gobj, s_gobj, s_ngobj * sizeof *s_gobj); S->ngobj = s_ngobj; s_ngobj = 0;
    S->pending = 1;
    s_cur = (s_cur + 1u) % VK_SLOTS;
    vk_slot* N = &s_slot[s_cur];
    if (N->pending) {
        const uint64_t w0 = ps3_ft_now();
        pvkWaitForFences(s_vk.device, 1, &N->fence, VK_TRUE, UINT64_MAX);
        const uint64_t w1 = ps3_ft_now();
        if (PS3_FT_ON()) ps3_ft_span(PS3_FT_GPU_WAIT, 0, 1u, (uint32_t)__LINE__, w0, w1);
        vk_flush_note(__LINE__, w1 - w0);
        vk_slot_free(N);
    }
    s_inflight = 1;
    s_vk.cmd = N->cmd; s_vk.fence = N->fence; s_vk.sem_acquire = N->acq;
    s_ring = N->ring; s_dpool = N->dpool;
    s_ring_off = 0;
    if (s_dpool) pvkResetDescriptorPool(s_vk.device, s_dpool, 0);
    s_dsets = 0;
}

/* Blit the offscreen target into the next swapchain image and present it. */
static void vk_present_window(void)
{
    if (!s_vk.windowed || !s_vk.swapchain) return;
    const int async = vk_async() && vk_async_setup();
''',
     "vk async: present setup")
edit(VKF,
     '''        VK_LOG("vkAcquireNextImageKHR failed (VkResult %d)\\n", (int)r); return;
    }

    vk_flush();
    if (vk_begin()) return;''',
     '''        VK_LOG("vkAcquireNextImageKHR failed (VkResult %d)\\n", (int)r); return;
    }

    if (!async) vk_flush();                    /* async: the frame goes in this submission */
    if (vk_begin()) return;''',
     "vk async: present no flush")
edit(VKF,
     '''    pvkResetFences(s_vk.device, 1, &s_vk.fence);
    if (pvkQueueSubmit(s_vk.queue, 1, &si, s_vk.fence) != VK_SUCCESS) {
        VK_LOG("vkQueueSubmit (window) failed\\n"); return;
    }
    {   const uint64_t pw0 = ps3_ft_now();''',
     '''    pvkResetFences(s_vk.device, 1, &s_vk.fence);
    if (pvkQueueSubmit(s_vk.queue, 1, &si, s_vk.fence) != VK_SUCCESS) {
        VK_LOG("vkQueueSubmit (window) failed\\n"); return;
    }
    if (async) {
        VkPresentInfoKHR api = {
            .sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR,
            .waitSemaphoreCount = 1, .pWaitSemaphores = &s_vk.sc_done[idx],
            .swapchainCount = 1, .pSwapchains = &s_vk.swapchain, .pImageIndices = &idx,
        };
        r = pvkQueuePresentKHR(s_vk.queue, &api);
        vk_slot_rotate();
        if (r == VK_ERROR_OUT_OF_DATE_KHR || r == VK_SUBOPTIMAL_KHR) vk_swapchain_lost();
        else if (r != VK_SUCCESS) VK_LOG("vkQueuePresentKHR failed (VkResult %d)\\n", (int)r);
        return;
    }
    {   const uint64_t pw0 = ps3_ft_now();''',
     "vk async: present submit")

# pipelines and framebuffers the GPU may still use
edit(VKF,
     '''    for (u32 i = 0; i < s_e2.fb_count; i++)
        if (s_e2.fb[i].fb) pvkDestroyFramebuffer(s_vk.device, s_e2.fb[i].fb, NULL);''',
     '''    for (u32 i = 0; i < s_e2.fb_count; i++)
        if (s_e2.fb[i].fb && !vk_gobj_defer(3, (uint64_t)(uintptr_t)s_e2.fb[i].fb))
            pvkDestroyFramebuffer(s_vk.device, s_e2.fb[i].fb, NULL);''',
     "vk async: fb defer")
edit(VKF,
     '''    for (u32 t = 0; t < VK_ENG_TOPOLOGIES; t++)
        if (P->variant[t]) pvkDestroyPipeline(s_vk.device, P->variant[t], NULL);
    if (P->vs) pvkDestroyShaderModule(s_vk.device, P->vs, NULL);
    if (P->fs) pvkDestroyShaderModule(s_vk.device, P->fs, NULL);
    memset(P, 0, sizeof *P);
    if (s_e2.pipeline == pipeline) s_e2.pipeline = 0;''',
     '''    for (u32 t = 0; t < VK_ENG_TOPOLOGIES; t++)
        if (P->variant[t] && !vk_gobj_defer(1, (uint64_t)(uintptr_t)P->variant[t]))
            pvkDestroyPipeline(s_vk.device, P->variant[t], NULL);
    if (P->vs && !vk_gobj_defer(2, (uint64_t)(uintptr_t)P->vs)) pvkDestroyShaderModule(s_vk.device, P->vs, NULL);
    if (P->fs && !vk_gobj_defer(2, (uint64_t)(uintptr_t)P->fs)) pvkDestroyShaderModule(s_vk.device, P->fs, NULL);
    memset(P, 0, sizeof *P);
    if (s_e2.pipeline == pipeline) s_e2.pipeline = 0;''',
     "vk async: pipe defer")
