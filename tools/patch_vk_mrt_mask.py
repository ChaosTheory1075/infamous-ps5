
# vk mrt mask: targets 1-3 take COLOR_MASK_MRT (0x0370) and BLEND_ENABLE_MRT (0x036C), as the RSX does
# The Vulkan engine pipeline gave every attachment target A's blend and write mask. The real PS3
# (snap_004149, 2026-11-03 PS3MAPI capture) draws inFAMOUS 2's glass/decal materials into its 3-target
# G-buffer with blend on for A (SRC_ALPHA / ONE_MINUS_SRC_ALPHA), BLEND_ENABLE_MRT = 0 and
# COLOR_MASK_MRT = 0: they change the albedo only. Ours blended their output into the normals and
# material planes as well, so whatever lies under a transparent surface (Zeke's sunglass lenses, decals)
# was lit with the glass's normals/gloss. Now the Metal backend's rule (rsx_metal_backend.m, mode 1):
# nibble r of color_mask_mrt (bit 0 A, 1 R, 2 G, 3 B) and bit r of blend_mrt for target r > 0.
# PS3_VK_MRT_MASK=0: target A's state everywhere (old).
edit("libs/video/rsx_vulkan_backend.c",
     '''    VkPipelineColorBlendAttachmentState cba[RSX_BE_MAX_COLOR_TARGETS];
    for (u32 r = 0; r < P->rt_count; r++)
        cba[r] = (VkPipelineColorBlendAttachmentState){
            .blendEnable = rs->blend_enable ? VK_TRUE : VK_FALSE,''',
     '''    VkPipelineColorBlendAttachmentState cba[RSX_BE_MAX_COLOR_TARGETS];
    static int mrt_mask = -1;   /* vk mrt mask */
    if (mrt_mask < 0) { const char* e = getenv("PS3_VK_MRT_MASK"); mrt_mask = !(e && *e == '0'); }
    for (u32 r = 0; r < P->rt_count; r++) {
        VkColorComponentFlags twm = wm; int tblend = rs->blend_enable != 0;
        if (r > 0 && mrt_mask) {
            const u32 nib = (rs->color_mask_mrt >> (r * 4)) & 0xFu;
            twm = 0;
            if (nib & 1u) twm |= VK_COLOR_COMPONENT_A_BIT;
            if (nib & 2u) twm |= VK_COLOR_COMPONENT_R_BIT;
            if (nib & 4u) twm |= VK_COLOR_COMPONENT_G_BIT;
            if (nib & 8u) twm |= VK_COLOR_COMPONENT_B_BIT;
            tblend = (rs->blend_mrt >> r) & 1u;
        }
        cba[r] = (VkPipelineColorBlendAttachmentState){
            .blendEnable = tblend ? VK_TRUE : VK_FALSE,''',
     "vk mrt mask")
edit("libs/video/rsx_vulkan_backend.c",
     '''            .alphaBlendOp = vk_gcm_blend_op(rs->eq_a),
            .colorWriteMask = wm };
    VkPipelineColorBlendStateCreateInfo cb = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,
        .attachmentCount = P->rt_count, .pAttachments = cba };''',
     '''            .alphaBlendOp = vk_gcm_blend_op(rs->eq_a),
            .colorWriteMask = twm };   /* vk mrt mask */
    }
    VkPipelineColorBlendStateCreateInfo cb = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,
        .attachmentCount = P->rt_count, .pAttachments = cba };''',
     "vk mrt mask 2")
