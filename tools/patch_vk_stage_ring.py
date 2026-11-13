
# vk stage ring: texture uploads copy through the per-frame ring instead of a new staging buffer each
# A BC-250 if2 RSX-thread profile (kb1, 2026-11-03) had ~25% of the thread in the kernel and the
# driver, most of it vk_create_host_buffer (vkCreateBuffer + vkAllocateMemory + vkMapMemory: an
# amdgpu BO alloc ioctl, a VA alloc and an mmap) and the free after it -- one per texture upload and
# per mip level. The ring (s_ring) is host-visible and coherent and is reused only after the GPU has
# finished the submission that read it (vk_batch_after_flush after a fence wait, vk_slot_rotate after
# the slot's fence), so a copy recorded from it is safe like the vertex data in it. No ring yet, or
# full: the old path. PS3_VK_STAGE_RING=0: always the old path.
edit("libs/video/rsx_vulkan_backend.c",
     '''static vk_buffer        s_ring;                 /* per-frame vertices, indices, constants */
static VkDeviceSize     s_ring_off, s_ubo_align;
''',
     '''static vk_buffer        s_ring;                 /* per-frame vertices, indices, constants */
static VkDeviceSize     s_ring_off, s_ubo_align;
static void* vk_ring_alloc(VkDeviceSize bytes, VkDeviceSize align, VkDeviceSize* off);
/* vk stage ring: staging space for an upload from the ring (*buf = the ring) or a fresh buffer in *own. */
static void* vk_stage_alloc(VkDeviceSize bytes, vk_buffer* own, VkBuffer* buf, VkDeviceSize* off)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3_VK_STAGE_RING"); on = !(e && *e == '0'); }
    memset(own, 0, sizeof *own);
    if (on && s_ring.buf && s_ring.coherent) {
        void* p = vk_ring_alloc(bytes, 16u, off);
        if (p) { *buf = s_ring.buf; return p; }
    }
    if (vk_create_host_buffer(own, bytes, VK_BUFFER_USAGE_TRANSFER_SRC_BIT) || !own->coherent) {
        vk_destroy_buffer(own); return NULL;
    }
    *buf = own->buf; *off = 0;
    return own->ptr;
}
''',
     "vk stage ring decl")
# vk_create_host_buffer / vk_destroy_buffer are defined after the ring declarations: forward-declare them.
edit("libs/video/rsx_vulkan_backend.c",
     '''static void* vk_ring_alloc(VkDeviceSize bytes, VkDeviceSize align, VkDeviceSize* off);
/* vk stage ring:''',
     '''static void* vk_ring_alloc(VkDeviceSize bytes, VkDeviceSize align, VkDeviceSize* off);
static int vk_create_host_buffer(vk_buffer* b, VkDeviceSize size, VkBufferUsageFlags usage);
static void vk_destroy_buffer(vk_buffer* b);
/* vk stage ring:''',
     "vk stage ring fwd")
edit("libs/video/rsx_vulkan_backend.c",
     '''        if (vk_create_host_buffer(&s_ring, VK_RING_BYTES, VK_BUFFER_USAGE_VERTEX_BUFFER_BIT |
                                  VK_BUFFER_USAGE_INDEX_BUFFER_BIT | VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT) ||''',
     '''        if (vk_create_host_buffer(&s_ring, VK_RING_BYTES, VK_BUFFER_USAGE_VERTEX_BUFFER_BIT |
                                  VK_BUFFER_USAGE_INDEX_BUFFER_BIT | VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT |
                                  VK_BUFFER_USAGE_TRANSFER_SRC_BIT /* vk stage ring */) ||''',
     "vk stage ring usage")
# vk_eng_upload_rows
edit("libs/video/rsx_vulkan_backend.c",
     '''    if (tight > row_bytes) tight = row_bytes;
    vk_buffer st = {0};
    if (vk_create_host_buffer(&st, (VkDeviceSize)tight * rows, VK_BUFFER_USAGE_TRANSFER_SRC_BIT) ||
        !st.coherent) { vk_destroy_buffer(&st); return -1; }
    for (u32 y = 0; y < rows; y++)
        memcpy((u8*)st.ptr + (size_t)y * tight, (const u8*)src + (size_t)y * row_bytes, tight);
    int rc = vk_begin();
    if (!rc) {
        vk_barrier_image(img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);
        VkBufferImageCopy region = {
            .imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, mip, layer, 1 },
            .imageExtent = { w, h, 1 },
        };
        pvkCmdCopyBufferToImage(s_vk.cmd, st.buf, img, VK_IMAGE_LAYOUT_GENERAL, 1, &region);''',
     '''    if (tight > row_bytes) tight = row_bytes;
    vk_buffer st; VkBuffer sb; VkDeviceSize so;   /* vk stage ring */
    u8* sp = (u8*)vk_stage_alloc((VkDeviceSize)tight * rows, &st, &sb, &so);
    if (!sp) return -1;
    for (u32 y = 0; y < rows; y++)
        memcpy(sp + (size_t)y * tight, (const u8*)src + (size_t)y * row_bytes, tight);
    int rc = vk_begin();
    if (!rc) {
        vk_barrier_image(img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);
        VkBufferImageCopy region = {
            .bufferOffset = so,
            .imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, mip, layer, 1 },
            .imageExtent = { w, h, 1 },
        };
        pvkCmdCopyBufferToImage(s_vk.cmd, sb, img, VK_IMAGE_LAYOUT_GENERAL, 1, &region);''',
     "vk stage ring rows")
# vk_upload_texture_levels
edit("libs/video/rsx_vulkan_backend.c",
     '''    vk_buffer staging = {0};
    if (vk_create_host_buffer(&staging, total, VK_BUFFER_USAGE_TRANSFER_SRC_BIT) ||
        !staging.coherent) {
        vk_destroy_buffer(&staging); return -1;
    }
    memcpy(staging.ptr, rgba, (size_t)total);
''',
     '''    vk_buffer staging; VkBuffer sb; VkDeviceSize so;   /* vk stage ring */
    u8* sp = (u8*)vk_stage_alloc(total, &staging, &sb, &so);
    if (!sp) return -1;
    memcpy(sp, rgba, (size_t)total);
    for (u32 m = 0; m < nlv; m++) regions[m].bufferOffset += so;
''',
     "vk stage ring levels")
edit("libs/video/rsx_vulkan_backend.c",
     '''        pvkCmdCopyBufferToImage(s_vk.cmd, staging.buf, fresh.img, VK_IMAGE_LAYOUT_GENERAL,
                                nlv, regions);''',
     '''        pvkCmdCopyBufferToImage(s_vk.cmd, sb, fresh.img, VK_IMAGE_LAYOUT_GENERAL,
                                nlv, regions);   /* vk stage ring */''',
     "vk stage ring levels 2")
