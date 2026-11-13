# vk dset reuse: the engine's per-draw descriptor set is reused while nothing in it changes.
# Every draw allocated a descriptor set from the frame's pool and wrote 34 descriptors (two uniform
# buffers, 16 images, 16 samplers) although consecutive draws mostly bind the same textures: only
# the two uniform-buffer offsets into the ring differ. The two uniform buffers are now
# UNIFORM_BUFFER_DYNAMIC (offset 0 in the descriptor, the ring offset given at bind time), so a draw
# whose buffer, ranges, image views and samplers equal the previous draw's binds that draw's set
# again with its own offsets: no allocation, no vkUpdateDescriptorSets. The cached set is dropped
# whenever a descriptor pool is reset or swapped. inFAMOUS 1's crater: 13,500 draws per frame on an
# RSX thread at 98% of a core (BC-250, 2026-11-01). PS3RECOMP_VK_DSET_REUSE=0 turns reuse off.
VKB = "libs/video/rsx_vulkan_backend.c"
edit(VKB,
     '''        { RSX_SPIRV_VPCONST_BINDING, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1, both, NULL },
        { RSX_SPIRV_PSCONST_BINDING, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1, both, NULL },''',
     '''        { RSX_SPIRV_VPCONST_BINDING, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, 1, both, NULL },   /* vk dset reuse */
        { RSX_SPIRV_PSCONST_BINDING, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, 1, both, NULL },''',
     "vk dset reuse: layout")
edit(VKB,
     '''    VkDescriptorPoolSize ps[3] = {
        { VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 2 },''',
     '''    VkDescriptorPoolSize ps[3] = {
        { VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, 2 },''',
     "vk dset reuse: guest pool")
edit(VKB,
     '''            { VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 2u * VK_DPOOL_SETS },''',
     '''            { VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, 2u * VK_DPOOL_SETS },''',
     "vk dset reuse: batch pool")
# the old guest-program draw: offsets 0 / ps_off move to the bind
edit(VKB,
     '''    VkDescriptorBufferInfo bi[2] = {
        { s_g.ubo.buf, 0, VK_VPCONST_BYTES },
        { s_g.ubo.buf, s_g.ps_off, fp_len },
    };''',
     '''    VkDescriptorBufferInfo bi[2] = {   /* vk dset reuse: dynamic, offsets at the bind */
        { s_g.ubo.buf, 0, VK_VPCONST_BYTES },
        { s_g.ubo.buf, 0, fp_len },
    };''',
     "vk dset reuse: guest bi")
edit(VKB,
     '''          .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, .pBufferInfo = &bi[0] },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_g.set,
          .dstBinding = RSX_SPIRV_PSCONST_BINDING, .descriptorCount = 1,
          .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, .pBufferInfo = &bi[1] },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_g.set,
          .dstBinding = RSX_SPIRV_TEXTURE_BINDING, .descriptorCount = RSX_MAX_TEXTURES,
          .descriptorType = VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, .pImageInfo = ii },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_g.set,
          .dstBinding = RSX_SPIRV_SAMPLER_BINDING, .descriptorCount = RSX_MAX_TEXTURES,
          .descriptorType = VK_DESCRIPTOR_TYPE_SAMPLER, .pImageInfo = si },
    };
    pvkUpdateDescriptorSets(s_vk.device, 4, w, 0, NULL);''',
     '''          .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, .pBufferInfo = &bi[0] },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_g.set,
          .dstBinding = RSX_SPIRV_PSCONST_BINDING, .descriptorCount = 1,
          .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, .pBufferInfo = &bi[1] },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_g.set,
          .dstBinding = RSX_SPIRV_TEXTURE_BINDING, .descriptorCount = RSX_MAX_TEXTURES,
          .descriptorType = VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, .pImageInfo = ii },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_g.set,
          .dstBinding = RSX_SPIRV_SAMPLER_BINDING, .descriptorCount = RSX_MAX_TEXTURES,
          .descriptorType = VK_DESCRIPTOR_TYPE_SAMPLER, .pImageInfo = si },
    };
    pvkUpdateDescriptorSets(s_vk.device, 4, w, 0, NULL);''',
     "vk dset reuse: guest writes")
edit(VKB,
     '''    pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_g.pipe_layout,
                             0, 1, &s_g.set, 0, NULL);''',
     '''    {   const uint32_t dyn[2] = { 0u, (uint32_t)s_g.ps_off };   /* vk dset reuse */
        pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_g.pipe_layout,
                                 0, 1, &s_g.set, 2, dyn); }''',
     "vk dset reuse: guest bind")
edit(VKB,
     '''static VkDescriptorSet  s_wd_set;''',
     '''static unsigned s_dpool_epoch;                  /* vk dset reuse: bumped when a descriptor pool is reset/swapped */
static VkDescriptorSet  s_wd_set;''',
     "vk dset reuse: epoch decl")
# the engine's writes: offsets become the dynamic ones; reuse when unchanged
edit(VKB,
     '''static void vk_eng_write_descriptors(void)
{''',
     '''/* vk dset reuse (tools/patch_vk_dset_reuse.py) */
static uint32_t s_dyn[2];                       /* dynamic offsets of the set being bound */
static int vk_dset_reuse_on(void)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3RECOMP_VK_DSET_REUSE"); on = !(e && e[0] == '0'); }
    return on;
}
static struct {
    VkDescriptorSet set; VkDescriptorPool pool; unsigned epoch;
    VkBuffer buf; VkDeviceSize r0, r1;
    VkImageView view[RSX_MAX_TEXTURES]; VkSampler smp[RSX_MAX_TEXTURES];
} s_dlast;
static unsigned long s_dreuse_n, s_dwrite_n;
static int vk_eng_write_descriptors_ex(int may_reuse);
static void vk_eng_write_descriptors(void) { (void)vk_eng_write_descriptors_ex(0); }
static int vk_eng_write_descriptors_ex(int may_reuse)
{''',
     "vk dset reuse: state")
edit(VKB,
     '''    VkDescriptorBufferInfo bi[2] = {
        { s_wd_buf ? s_wd_buf : s_g.ubo.buf, s_wd_buf ? s_wd_vs : 0, s_e2.vs_bytes ? s_e2.vs_bytes : 16u },
        { s_wd_buf ? s_wd_buf : s_g.ubo.buf, s_wd_buf ? s_wd_ps : s_g.ps_off, s_e2.ps_bytes ? s_e2.ps_bytes : 16u },
    };''',
     '''    VkDescriptorBufferInfo bi[2] = {   /* vk dset reuse: offset 0, the real one is dynamic */
        { s_wd_buf ? s_wd_buf : s_g.ubo.buf, 0, s_e2.vs_bytes ? s_e2.vs_bytes : 16u },
        { s_wd_buf ? s_wd_buf : s_g.ubo.buf, 0, s_e2.ps_bytes ? s_e2.ps_bytes : 16u },
    };
    s_dyn[0] = (uint32_t)(s_wd_buf ? s_wd_vs : 0);
    s_dyn[1] = (uint32_t)(s_wd_buf ? s_wd_ps : s_g.ps_off);''',
     "vk dset reuse: offsets")
edit(VKB,
     '''          .dstBinding = RSX_SPIRV_VPCONST_BINDING, .descriptorCount = 1,
          .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, .pBufferInfo = &bi[0] },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_g.set,
          .dstBinding = RSX_SPIRV_PSCONST_BINDING, .descriptorCount = 1,
          .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, .pBufferInfo = &bi[1] },''',
     '''          .dstBinding = RSX_SPIRV_VPCONST_BINDING, .descriptorCount = 1,   /* vk dset reuse: engine */
          .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, .pBufferInfo = &bi[0] },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_g.set,
          .dstBinding = RSX_SPIRV_PSCONST_BINDING, .descriptorCount = 1,
          .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, .pBufferInfo = &bi[1] },''',
     "vk dset reuse: engine ubo types")
edit(VKB,
     '''    if (s_wd_set) for (int i = 0; i < 4; i++) w[i].dstSet = s_wd_set;
    pvkUpdateDescriptorSets(s_vk.device, 4, w, 0, NULL);''',
     '''    if (may_reuse) {
        /* the previous set fits when it lives in this pool epoch and every descriptor is the same */
        int same = s_dlast.set && s_dlast.pool == s_dpool && s_dlast.epoch == s_dpool_epoch &&
                   s_dlast.buf == bi[0].buffer && s_dlast.r0 == bi[0].range && s_dlast.r1 == bi[1].range;
        for (u32 u = 0; same && u < RSX_MAX_TEXTURES; u++)
            same = s_dlast.view[u] == ii[u].imageView && s_dlast.smp[u] == si[u].sampler;
        if (same) { s_wd_set = s_dlast.set; s_dreuse_n++; return 1; }
        return 0;   /* the caller allocates a set and calls again with may_reuse = 2 */
    }
    if (s_wd_set) for (int i = 0; i < 4; i++) w[i].dstSet = s_wd_set;
    pvkUpdateDescriptorSets(s_vk.device, 4, w, 0, NULL);
    s_dwrite_n++;
    if (s_wd_set) {
        s_dlast.set = s_wd_set; s_dlast.pool = s_dpool; s_dlast.epoch = s_dpool_epoch;
        s_dlast.buf = bi[0].buffer; s_dlast.r0 = bi[0].range; s_dlast.r1 = bi[1].range;
        for (u32 u = 0; u < RSX_MAX_TEXTURES; u++) { s_dlast.view[u] = ii[u].imageView; s_dlast.smp[u] = si[u].sampler; }
    }''',
     "vk dset reuse: compare + remember")
edit(VKB,
     '''            s_sub_cube = s_sub_vol = s_sub_kind = 0; s_sub_t0 = now;
        } }
}''',
     '''            s_sub_cube = s_sub_vol = s_sub_kind = 0; s_sub_t0 = now;
            { static int lg = -1; if (lg < 0) lg = getenv("PS3RECOMP_VK_DSET_LOG") ? 1 : 0;
              if (lg) fprintf(stderr, "[vk] descriptor sets: %lu reused, %lu written\\n", s_dreuse_n, s_dwrite_n); }
            s_dreuse_n = s_dwrite_n = 0;
        } }
    return 0;
}''',
     "vk dset reuse: report")
edit(VKB,
     '''    memcpy(vk_ring_alloc(ps_bytes, s_ubo_align, &ps_off), s_ubo_cpu + s_g.ps_off, ps_bytes);
    VkDescriptorSetAllocateInfo dai''',
     '''    memcpy(vk_ring_alloc(ps_bytes, s_ubo_align, &ps_off), s_ubo_cpu + s_g.ps_off, ps_bytes);
    /* vk dset reuse: the previous draw's set when nothing in it differs (offsets are dynamic) */
    s_wd_buf = s_ring.buf; s_wd_vs = vs_off; s_wd_ps = ps_off;
    if (vk_dset_reuse_on() && vk_eng_write_descriptors_ex(1)) return 0;
    VkDescriptorSetAllocateInfo dai''',
     "vk dset reuse: try reuse")
edit(VKB,
     '''    if (s_dpool && s_dsets) { pvkResetDescriptorPool(s_vk.device, s_dpool, 0); s_dsets = 0; }''',
     '''    if (s_dpool && s_dsets) { pvkResetDescriptorPool(s_vk.device, s_dpool, 0); s_dsets = 0; }
    s_dpool_epoch++;   /* vk dset reuse */''',
     "vk dset reuse: epoch 1")
edit(VKB,
     '''    if (s_dpool) pvkResetDescriptorPool(s_vk.device, s_dpool, 0);
    s_dsets = 0;''',
     '''    if (s_dpool) pvkResetDescriptorPool(s_vk.device, s_dpool, 0);
    s_dsets = 0;
    s_dpool_epoch++;   /* vk dset reuse */''',
     "vk dset reuse: epoch 2")
edit(VKB,
     '''    pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_g.pipe_layout,
                             0, 1, &dset, 0, NULL);''',
     '''    pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_g.pipe_layout,
                             0, 1, &dset, 2, s_dyn);   /* vk dset reuse: dynamic offsets */''',
     "vk dset reuse: engine bind")
# A destroyed image view's (or sampler's) handle value can come back for a new object, and the set
# holds the OLD descriptor bytes: every destroy ends reuse (first try: device lost on the crater).
edit(VKB,
     '''        memset(im, 0, sizeof *im);
        return;
    }
    if (im->view) pvkDestroyImageView(s_vk.device, im->view, NULL);''',
     '''        memset(im, 0, sizeof *im);
        return;
    }
    s_dpool_epoch++;   /* vk dset reuse: handles may come back */
    if (im->view) pvkDestroyImageView(s_vk.device, im->view, NULL);''',
     "vk dset reuse: destroy image")
edit(VKB,
     '''        vk_image* im = &s_gimg[i];
        if (im->view) pvkDestroyImageView(s_vk.device, im->view, NULL);''',
     '''        vk_image* im = &s_gimg[i];
        s_dpool_epoch++;   /* vk dset reuse */
        if (im->view) pvkDestroyImageView(s_vk.device, im->view, NULL);''',
     "vk dset reuse: garbage 1")
edit(VKB,
     '''        vk_image* im = &S->gimg[i];
        if (im->view) pvkDestroyImageView(s_vk.device, im->view, NULL);''',
     '''        vk_image* im = &S->gimg[i];
        s_dpool_epoch++;   /* vk dset reuse */
        if (im->view) pvkDestroyImageView(s_vk.device, im->view, NULL);''',
     "vk dset reuse: garbage 2")
edit(VKB,
     '''    pvkDestroyImageView(s_vk.device, o->im.view, NULL);
    if (vk_eng_make_view_layers(o->im.img, o->fmt, 1, id, 6, &o->im.view))''',
     '''    s_dpool_epoch++;   /* vk dset reuse */
    pvkDestroyImageView(s_vk.device, o->im.view, NULL);
    if (vk_eng_make_view_layers(o->im.img, o->fmt, 1, id, 6, &o->im.view))''',
     "vk dset reuse: dummy cube")
edit(VKB,
     '''    for (u32 i = 0; i < s_esamp_count; i++) pvkDestroySampler(s_vk.device, s_esamp[i].s, NULL);''',
     '''    s_dpool_epoch++;   /* vk dset reuse */
    for (u32 i = 0; i < s_esamp_count; i++) pvkDestroySampler(s_vk.device, s_esamp[i].s, NULL);''',
     "vk dset reuse: samplers")
