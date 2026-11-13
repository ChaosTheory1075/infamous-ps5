# vk tex3d: 3D textures on Vulkan (colour-grading volumes), and a black stand-in cube with a log line
VKF = "libs/video/rsx_vulkan_backend.c"
edit(VKF,
     '''    u32      snap2;                  /* COLOR/DEPTH: colour / RGBA8 snapshot */
} vk_eng_obj;''',
     '''    u32      snap2;                  /* COLOR/DEPTH: colour / RGBA8 snapshot */
    u8       vol;                    /* TEXTURE: a 3D image, 3D view        */
} vk_eng_obj;''',
     "vk tex3d: obj field")
edit(VKF,
     '''    u32                 cube_mask;    /* pixel shader's TextureCube units */
    VkPipeline          variant[VK_ENG_TOPOLOGIES];''',
     '''    u32                 cube_mask;    /* pixel shader's TextureCube units */
    u32                 vol_mask;     /* pixel shader's Texture3D units */
    VkPipeline          variant[VK_ENG_TOPOLOGIES];''',
     "vk tex3d: pipe field")
edit(VKF,
     '''    for (const char* c = ps_hlsl; (c = strstr(c, "TextureCube rsx_tex")) != NULL; c++) {
        const unsigned u = (unsigned)strtoul(c + 19, NULL, 10);
        if (u < RSX_MAX_TEXTURES) P->cube_mask |= 1u << u;
    }''',
     '''    for (const char* c = ps_hlsl; (c = strstr(c, "TextureCube rsx_tex")) != NULL; c++) {
        const unsigned u = (unsigned)strtoul(c + 19, NULL, 10);
        if (u < RSX_MAX_TEXTURES) P->cube_mask |= 1u << u;
    }
    for (const char* c = ps_hlsl; (c = strstr(c, "Texture3D")) != NULL; c++) {
        const char* t = strstr(c, "rsx_tex");
        if (!t || t - c > 8) continue;
        const unsigned u = (unsigned)strtoul(t + 7, NULL, 10);
        if (u < RSX_MAX_TEXTURES) P->vol_mask |= 1u << u;
    }''',
     "vk tex3d: pipe mask")
edit(VKF,
     '''static VkImageView vk_eng_dummy_cube(void)
{
    static u32 hd;''',
     '''/* 3D textures (the engine's texture_create_3d / texture_upload_3d). Without them a volume was
 * created from its first slice and sampled in 2D: a colour-grading volume (red x green x blue)
 * lost its blue axis, which tinted whole areas -- FoB's town green-yellow, inFAMOUS's alleys blue
 * (user's reference footage, 2026-11-01). One VK_IMAGE_TYPE_3D image with a 3D view; each slice
 * of each level is one upload. */
static u32 vk_eng_texture_create_3d(void* user, rsx_be_format fmt, u32 w, u32 h, u32 depth,
                                    u32 mips, u32 remap, u32 rsx_fmt)
{
    (void)user;
    u32 bpp;
    const VkFormat vf = vk_eng_format(fmt, &bpp);
    const int bc = (fmt == RSX_BE_FMT_BC1 || fmt == RSX_BE_FMT_BC2 || fmt == RSX_BE_FMT_BC3);
    if (vf == VK_FORMAT_UNDEFINED || !w || !h || !depth || w > 2048u || h > 2048u || depth > 2048u || bc)
        return 0;
    if (!mips) mips = 1;
    const u32 hd = vk_eng_alloc();
    if (!hd) return 0;
    vk_eng_obj* o = &s_eobj[hd];
    VkImageCreateInfo ici = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_3D,
        .format = vf, .extent = { w, h, depth }, .mipLevels = mips, .arrayLayers = 1,
        .samples = VK_SAMPLE_COUNT_1_BIT, .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,
        .sharingMode = VK_SHARING_MODE_EXCLUSIVE, .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED };
    VkMemoryRequirements req;
    u32 type;
    if (pvkCreateImage(s_vk.device, &ici, NULL, &o->im.img) != VK_SUCCESS) goto fail;
    pvkGetImageMemoryRequirements(s_vk.device, o->im.img, &req);
    if (vk_find_memory_type(req.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, &type) &&
        vk_find_memory_type(req.memoryTypeBits, 0, &type)) goto fail;
    VkMemoryAllocateInfo mai = { .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                                 .allocationSize = req.size, .memoryTypeIndex = type };
    if (pvkAllocateMemory(s_vk.device, &mai, NULL, &o->im.mem) != VK_SUCCESS ||
        pvkBindImageMemory(s_vk.device, o->im.img, o->im.mem, 0) != VK_SUCCESS) goto fail;
    {   VkImageViewCreateInfo vci = {
            .sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = o->im.img,
            .viewType = VK_IMAGE_VIEW_TYPE_3D, .format = vf, .components = vk_remap(remap, rsx_fmt),
            .subresourceRange = { VK_IMAGE_ASPECT_COLOR_BIT, 0, mips, 0, 1 } };
        if (pvkCreateImageView(s_vk.device, &vci, NULL, &o->im.view) != VK_SUCCESS) goto fail; }
    o->kind = VK_ENG_TEXTURE; o->fmt = vf; o->w = w; o->h = h; o->cube = 0; o->vol = 1;
    o->bpp = bpp; o->block = 0;
    if (vk_begin()) goto fail;
    vk_barrier_image(o->im.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_UNDEFINED);
    if (vk_submit_and_wait()) goto fail;
    {   static int told; if (told++ < 8) VK_LOG("engine: 3D texture %ux%ux%u (%u levels, format %d)\\n", w, h, depth, mips, (int)vf); }
    return hd;
fail:
    vk_destroy_image(&o->im);
    memset(o, 0, sizeof *o);
    return 0;
}

static void vk_eng_texture_upload_3d(void* user, u32 texture, u32 z, u32 mip, u32 w, u32 h,
                                     const void* src, u32 row_bytes)
{
    (void)user;
    vk_eng_obj* o = vk_eng_get(texture, VK_ENG_TEXTURE);
    if (!o || !o->vol || !src || !row_bytes || !w || !h) return;
    size_t tight = (size_t)w * o->bpp;
    if (tight > row_bytes) tight = row_bytes;
    vk_buffer st = {0};
    if (vk_create_host_buffer(&st, (VkDeviceSize)tight * h, VK_BUFFER_USAGE_TRANSFER_SRC_BIT) ||
        !st.coherent) { vk_destroy_buffer(&st); return; }
    for (u32 y = 0; y < h; y++)
        memcpy((u8*)st.ptr + (size_t)y * tight, (const u8*)src + (size_t)y * row_bytes, tight);
    if (!vk_begin()) {
        vk_barrier_image(o->im.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);
        VkBufferImageCopy region = {
            .imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, mip, 0, 1 },
            .imageOffset = { 0, 0, (int32_t)z }, .imageExtent = { w, h, 1 } };
        pvkCmdCopyBufferToImage(s_vk.cmd, st.buf, o->im.img, VK_IMAGE_LAYOUT_GENERAL, 1, &region);
        vk_submit_and_wait();
    }
    vk_destroy_buffer(&st);
}

/* A unit declared Texture3D with nothing usable bound: a 1x1x1 black volume. */
static VkImageView vk_eng_dummy_3d(void)
{
    static u32 hd;
    if (hd && s_eobj[hd].kind == VK_ENG_TEXTURE && s_eobj[hd].vol) return s_eobj[hd].im.view;
    hd = vk_eng_texture_create_3d(NULL, RSX_BE_FMT_R8G8B8A8, 1, 1, 1, 1, 0, 0);
    if (!hd) return s_vk.dummy.view;
    /* the identity crossbar: vk_remap(0, 0) is what create used */
    static const u8 black[4] = { 0, 0, 0, 0xFF };
    vk_eng_texture_upload_3d(NULL, hd, 0, 0, 1, 1, black, 4);
    return s_eobj[hd].im.view;
}

static VkImageView vk_eng_dummy_cube(void)
{
    static u32 hd;''',
     "vk tex3d: create upload")
edit(VKF,
     '''    static const u8 magenta[4] = { 0xFF, 0x00, 0xFF, 0xFF };
    for (u32 f = 0; f < 6; f++) vk_eng_texture_upload(NULL, hd, f, 0, 1, 1, magenta, 4, 1);''',
     '''    /* Black, not magenta: a missing reflection cube is no reflection (inFAMOUS 2's metal props
     * were bright purple on the console). Each use is counted in "[vk] stand-in textures". */
    static const u8 black[4] = { 0x00, 0x00, 0x00, 0xFF };
    for (u32 f = 0; f < 6; f++) vk_eng_texture_upload(NULL, hd, f, 0, 1, 1, black, 4, 1);''',
     "vk tex3d: black cube")
edit(VKF,
     '''    const u32 cube_mask = s_e2.pipeline ? s_epipe[s_e2.pipeline - 1].cube_mask : 0;''',
     '''    const u32 cube_mask = s_e2.pipeline ? s_epipe[s_e2.pipeline - 1].cube_mask : 0;
    const u32 vol_mask = s_e2.pipeline ? s_epipe[s_e2.pipeline - 1].vol_mask : 0;
    static unsigned s_sub_cube, s_sub_vol, s_sub_kind; static uint64_t s_sub_t0;''',
     "vk tex3d: masks")
edit(VKF,
     '''        const u32 want_cube = (cube_mask >> u) & 1u;
        VkImageView v = ((s_e2.tex_mask >> u) & 1u) ? vk_eng_sample_view(s_e2.tex[u]) : VK_NULL_HANDLE;
        if (v && (u32)s_eobj[s_e2.tex[u]].cube != want_cube) v = VK_NULL_HANDLE;
        VkSampler smp = v ? vk_eng_sampler(&s_e2.samp[u]) : s_vk.sampler;
        ii[u] = (VkDescriptorImageInfo){ VK_NULL_HANDLE,
                                         v ? v : want_cube ? vk_eng_dummy_cube() : s_vk.dummy.view,
                                         VK_IMAGE_LAYOUT_GENERAL };''',
     '''        const u32 want_cube = (cube_mask >> u) & 1u, want_vol = (vol_mask >> u) & 1u;
        VkImageView v = ((s_e2.tex_mask >> u) & 1u) ? vk_eng_sample_view(s_e2.tex[u]) : VK_NULL_HANDLE;
        if (v && ((u32)s_eobj[s_e2.tex[u]].cube != want_cube || (u32)s_eobj[s_e2.tex[u]].vol != want_vol)) {
            v = VK_NULL_HANDLE; s_sub_kind++;
        }
        if (!v && want_cube) s_sub_cube++;
        if (!v && want_vol) s_sub_vol++;
        VkSampler smp = v ? vk_eng_sampler(&s_e2.samp[u]) : s_vk.sampler;
        ii[u] = (VkDescriptorImageInfo){ VK_NULL_HANDLE,
                                         v ? v : want_cube ? vk_eng_dummy_cube() : want_vol ? vk_eng_dummy_3d() : s_vk.dummy.view,
                                         VK_IMAGE_LAYOUT_GENERAL };''',
     "vk tex3d: descriptors")
edit(VKF,
     '''    if (s_wd_set) for (int i = 0; i < 4; i++) w[i].dstSet = s_wd_set;
    pvkUpdateDescriptorSets(s_vk.device, 4, w, 0, NULL);''',
     '''    if (s_wd_set) for (int i = 0; i < 4; i++) w[i].dstSet = s_wd_set;
    pvkUpdateDescriptorSets(s_vk.device, 4, w, 0, NULL);
    {   const uint64_t now = ps3_ft_now();
        if (!s_sub_t0) s_sub_t0 = now;
        if (now - s_sub_t0 >= 10000000000ull) {
            if (s_sub_cube || s_sub_vol || s_sub_kind)
                fprintf(stderr, "[vk] stand-in textures in %.0f s: %u cube, %u 3D, %u bound texture of the wrong kind\\n",
                        (now - s_sub_t0) / 1e9, s_sub_cube, s_sub_vol, s_sub_kind);
            s_sub_cube = s_sub_vol = s_sub_kind = 0; s_sub_t0 = now;
        } }''',
     "vk tex3d: log")
edit(VKF,
     '''    .texture_upload       = vk_eng_texture_upload,''',
     '''    .texture_upload       = vk_eng_texture_upload,
    .texture_create_3d    = vk_eng_texture_create_3d,
    .texture_upload_3d    = vk_eng_texture_upload_3d,''',
     "vk tex3d: hooks")
