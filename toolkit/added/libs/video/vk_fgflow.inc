/* vk fg flow: motion for frame generation (fgflow/*.comp). A PS3 game gives no motion vectors, so the GPU
 * finds them: block matching of the two real frames (16x16 blocks, -48..48 px), a 3x3 median, and MihawkGen's
 * mvwarp interpolates along them; where its two readings disagree (a wrong vector, an occlusion, the HUD over a
 * moving background) it shows the next real frame there instead of a blend -- no doubled images. The warp is
 * fgflow/warp.comp (MihawkGen's mvwarp averaged readings up to a 0.15 difference: dark scenes still doubled).
 * PS3_FG_METHOD=neural: the neural method as before (with the ghost guard). Included after vk_fgguard.inc. */
#include "fgflow/search_spv.h"
#include "fgflow/median_spv.h"
#include "fgflow/warp_spv.h"

typedef struct { int32_t w, h, bw, bh; float lambda, zero_bias; } vk_fgf_pc;
static struct {
    int method;   /* -1 unread, 0 neural, 1 flow + mvwarp */
    int failed;
    VkDescriptorSetLayout dsl; VkPipelineLayout pl; VkDescriptorPool dp; VkSampler samp;
    VkPipeline search, median, warp;
    VkDescriptorSet ds[2];
    vk_image raw, motion;
    u32 bw, bh;
} s_fgf = { .method = -1 };

static int vk_fgf_use(void)
{
    if (s_fgf.method < 0) { const char* e = getenv("PS3_FG_METHOD"); s_fgf.method = !(e && !strcmp(e, "neural")); }
    return s_fgf.method == 1 && !s_fgf.failed;
}

static VkPipeline vk_fgf_pipe(const uint32_t* code, size_t bytes)
{
    VkShaderModuleCreateInfo mi = { .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = bytes, .pCode = code };
    VkShaderModule m = VK_NULL_HANDLE;
    if (pvkCreateShaderModule(s_vk.device, &mi, NULL, &m) != VK_SUCCESS) return VK_NULL_HANDLE;
    VkComputePipelineCreateInfo ci = { .sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
        .stage = { .sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = m, .pName = "main" },
        .layout = s_fgf.pl };
    VkPipeline p = VK_NULL_HANDLE;
    if (pvkCreateComputePipelines(s_vk.device, VK_NULL_HANDLE, 1, &ci, NULL, &p) != VK_SUCCESS) p = VK_NULL_HANDLE;
    pvkDestroyShaderModule(s_vk.device, m, NULL);
    return p;
}

static int vk_fgf_init(VkImageView in0, VkImageView in1, VkImageView out)
{
    s_fgf.bw = (s_vk.width + 15) / 16; s_fgf.bh = (s_vk.height + 15) / 16;
    if (vk_create_image(&s_fgf.raw, VK_FORMAT_R32G32B32A32_SFLOAT, s_fgf.bw, s_fgf.bh, VK_IMAGE_USAGE_STORAGE_BIT, VK_IMAGE_ASPECT_COLOR_BIT) ||
        vk_create_image(&s_fgf.motion, VK_FORMAT_R16G16B16A16_SFLOAT, s_fgf.bw, s_fgf.bh, VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
                        VK_IMAGE_ASPECT_COLOR_BIT)) return -1;
    VkDescriptorSetLayoutBinding b[7] = {
        { 0, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL },
        { 1, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL },
        { 2, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL },
        { 3, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL },
        { 4, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL },
        { 5, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL },
        { 6, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL } };
    VkDescriptorSetLayoutCreateInfo di = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 7, .pBindings = b };
    if (pvkCreateDescriptorSetLayout(s_vk.device, &di, NULL, &s_fgf.dsl) != VK_SUCCESS) return -1;
    VkPushConstantRange pr = { VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(vk_fgf_pc) };
    VkPipelineLayoutCreateInfo pli = { .sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &s_fgf.dsl,
                                       .pushConstantRangeCount = 1, .pPushConstantRanges = &pr };
    if (pvkCreatePipelineLayout(s_vk.device, &pli, NULL, &s_fgf.pl) != VK_SUCCESS) return -1;
    VkDescriptorPoolSize ps[2] = { { VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 6 }, { VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 8 } };
    VkDescriptorPoolCreateInfo pci = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, .maxSets = 2, .poolSizeCount = 2, .pPoolSizes = ps };
    if (pvkCreateDescriptorPool(s_vk.device, &pci, NULL, &s_fgf.dp) != VK_SUCCESS) return -1;
    VkDescriptorSetLayout l2[2] = { s_fgf.dsl, s_fgf.dsl };
    VkDescriptorSetAllocateInfo ai = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, .descriptorPool = s_fgf.dp, .descriptorSetCount = 2, .pSetLayouts = l2 };
    if (pvkAllocateDescriptorSets(s_vk.device, &ai, s_fgf.ds) != VK_SUCCESS) return -1;
    VkSamplerCreateInfo sci = { .sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO, .magFilter = VK_FILTER_LINEAR, .minFilter = VK_FILTER_LINEAR,
        .addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE };
    if (pvkCreateSampler(s_vk.device, &sci, NULL, &s_fgf.samp) != VK_SUCCESS) return -1;
    s_fgf.warp = vk_fgf_pipe(s_fgf_warp_spv, sizeof s_fgf_warp_spv);
    s_fgf.search = vk_fgf_pipe(s_fgf_search_spv, sizeof s_fgf_search_spv);
    s_fgf.median = vk_fgf_pipe(s_fgf_median_spv, sizeof s_fgf_median_spv);
    if (!s_fgf.search || !s_fgf.median || !s_fgf.warp) return -1;
    for (int k = 0; k < 2; k++) {   /* set k: next = in[k], prev = in[k ^ 1] */
        VkDescriptorImageInfo pi = { .sampler = s_fgf.samp, .imageView = k ? in0 : in1, .imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL };
        VkDescriptorImageInfo ni = { .sampler = s_fgf.samp, .imageView = k ? in1 : in0, .imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL };
        VkDescriptorImageInfo ri = { .imageView = s_fgf.raw.view, .imageLayout = VK_IMAGE_LAYOUT_GENERAL };
        VkDescriptorImageInfo mi = { .imageView = s_fgf.motion.view, .imageLayout = VK_IMAGE_LAYOUT_GENERAL };
        VkDescriptorImageInfo msi = { .sampler = s_fgf.samp, .imageView = s_fgf.motion.view, .imageLayout = VK_IMAGE_LAYOUT_GENERAL };
        VkDescriptorImageInfo oi = { .imageView = out, .imageLayout = VK_IMAGE_LAYOUT_GENERAL };
        VkWriteDescriptorSet wr[7] = {
            { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_fgf.ds[k], .dstBinding = 0, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .pImageInfo = &pi },
            { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_fgf.ds[k], .dstBinding = 1, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .pImageInfo = &ni },
            { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_fgf.ds[k], .dstBinding = 2, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .pImageInfo = &ri },
            { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_fgf.ds[k], .dstBinding = 3, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .pImageInfo = &ri },
            { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_fgf.ds[k], .dstBinding = 4, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .pImageInfo = &mi },
            { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_fgf.ds[k], .dstBinding = 5, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .pImageInfo = &msi },
            { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_fgf.ds[k], .dstBinding = 6, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .pImageInfo = &oi } };
        pvkUpdateDescriptorSets(s_vk.device, 7, wr, 0, NULL);
    }
    VK_LOG("framegen: motion search on (%ux%u blocks of 16 px, -48..48 px), warp where the frames agree\n", s_fgf.bw, s_fgf.bh);
    return 0;
}

/* Records the motion search for the pair (in[cur ^ 1], in[cur]) and the mvwarp frame into out (GENERAL).
 * Returns 0 when it recorded, -1 when the caller should use the neural method. */
static int vk_fgf_record(u32 slot, u32 cur, VkImageView in0, VkImageView in1, VkImageView out, float t)
{
    if (!vk_fgf_use()) return -1;
    if (!s_fgf.search && vk_fgf_init(in0, in1, out)) { s_fgf.failed = 1; VK_LOG("framegen: motion search off (setup failed), neural\n"); return -1; }
    static float lambda = -1.0f, zb, agree;
    if (lambda < 0.0f) {
        const char* e = getenv("PS3_FG_LAMBDA"); lambda = e && *e ? (float)atof(e) : 0.0005f;
        e = getenv("PS3_FG_ZERO_BIAS"); zb = e && *e ? (float)atof(e) : 0.92f;
        e = getenv("PS3_FG_AGREE"); agree = e && *e ? (float)atof(e) : 0.06f;
    }
    const vk_fgf_pc pc = { (int32_t)s_vk.width, (int32_t)s_vk.height, (int32_t)s_fgf.bw, (int32_t)s_fgf.bh, lambda, zb };
    const VkDescriptorSet ds = s_fgf.ds[cur & 1u];
    vk_img_barrier(s_fgf.raw.img, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL, 0, VK_ACCESS_SHADER_WRITE_BIT,
                   VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
    vk_img_barrier(s_fgf.motion.img, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL, 0, VK_ACCESS_SHADER_WRITE_BIT,
                   VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
    pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_fgf.pl, 0, 1, &ds, 0, NULL);
    pvkCmdPushConstants(s_vk.cmd, s_fgf.pl, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, &pc);
    pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_fgf.search);
    pvkCmdDispatch(s_vk.cmd, s_fgf.bw, s_fgf.bh, 1);
    vk_img_barrier(s_fgf.raw.img, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_SHADER_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT,
                   VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
    pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_fgf.median);
    pvkCmdDispatch(s_vk.cmd, (s_fgf.bw + 7) / 8, (s_fgf.bh + 7) / 8, 1);
    vk_img_barrier(s_fgf.motion.img, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_SHADER_WRITE_BIT,
                   VK_ACCESS_SHADER_READ_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
    const struct { int32_t w, h, bw, bh; float t, agree; } wpc = { pc.w, pc.h, pc.bw, pc.bh, t, agree };
    pvkCmdPushConstants(s_vk.cmd, s_fgf.pl, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof wpc, &wpc);
    pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_fgf.warp);
    pvkCmdDispatch(s_vk.cmd, (s_vk.width + 7) / 8, (s_vk.height + 7) / 8, 1);
    (void)slot;
    return 0;
}
