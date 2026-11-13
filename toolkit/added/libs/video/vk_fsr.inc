/* vk fsr: AMD FidelityFX FSR 1 (EASU upscale + RCAS sharpen, MIT; fsr1/easu.comp, fsr1/rcas.comp) from the
 * guest frame (1280x720) to the swapchain size, in place of the bilinear blit. Included by
 * rsx_vulkan_backend.c after vk_img_barrier. PS3_UPSCALER: 0 = the old bilinear blit, 1 = FSR 1 (default);
 * PS3_FSR_SHARP: RCAS sharpness in stops, 0 = sharpest (default). The shaders are rebuilt with
 * glslangValidator -V --target-env vulkan1.0 fsr1/<name>.comp and dumped into fsr1/<name>_spv.h. */
#include "fsr1/easu_spv.h"
#include "fsr1/rcas_spv.h"
#include "fsr1/look_spv.h"   /* vk look */
#include "fsr1/fxaa_spv.h"   /* vk aa */
/* vk smaa: SMAA 1x (MIT, smaa/LICENSE.txt) as three compute passes (smaa/smaa_<pass>.comp, rebuilt into
 * smaa/smaa_<pass>_spv.h by smaa/build.sh) with SMAA's area and search lookup textures (third_party/smaa). */
#include "smaa/smaa_edges_spv.h"
#include "smaa/smaa_weights_spv.h"
#include "smaa/smaa_blend_spv.h"
#include "../../third_party/smaa/AreaTex.h"
#include "../../third_party/smaa/SearchTex.h"

typedef struct { int32_t in_w, in_h, out_w, out_h; float con0[4]; float sharp; } vk_fsr_pc;
static struct {
    int on, failed;
    float sharp;
    VkDescriptorSetLayout dsl; VkPipelineLayout pl; VkDescriptorPool dp; VkSampler samp;
    VkPipeline easu, rcas, look, fxaa;
    int aa; VkSampler lin; VkDescriptorSet ds_aa[2], ds_easu_pre; VkImageView ds_aa_view[2]; vk_image pre; u32 pw, ph;   /* vk aa: PS3_AA 1 = FXAA before EASU (default), 2 = SMAA 1x (vk smaa), 0 off */
    int look_mode; float look_k; float gamma;   /* vk gamma: PS3_VK_GAMMA (1 = off) */   /* vk look: PS3_LOOK 0 original, 1 remaster, 2 comic; PS3_LOOK_STRENGTH 0..1 */
    VkDescriptorSet ds_in[2], ds_rcas, ds_look;   /* EASU from colour (0) or the generated frame (1); RCAS from mid */
    VkImageView ds_in_view[2];
    vk_image mid, out;
    u32 w, h;
    unsigned frames;
} s_fsr = { .on = -1 };

static int vk_fsr_enabled(void)
{
    if (s_fsr.on < 0) {
        const char* e = getenv("PS3_UPSCALER"); s_fsr.on = !(e && *e == '0');
        const char* s = getenv("PS3_FSR_SHARP"); s_fsr.sharp = s && *s ? (float)atof(s) : 0.0f;
        if (s_fsr.sharp < 0.0f) s_fsr.sharp = 0.0f;
        const char* aa = getenv("PS3_AA"); s_fsr.aa = aa && *aa == '0' ? 0 : aa && *aa == '2' ? 2 : 1;   /* vk smaa: 2 */
        const char* lk = getenv("PS3_LOOK"); s_fsr.look_mode = lk && *lk ? atoi(lk) : 0;
        if (s_fsr.look_mode < 0 || s_fsr.look_mode > 11) s_fsr.look_mode = 0;   /* vk looks: 12 */
        const char* ls = getenv("PS3_LOOK_STRENGTH"); s_fsr.look_k = ls && *ls ? (float)atof(ls) : 1.0f;
        const char* vg = getenv("PS3_VK_GAMMA"); s_fsr.gamma = vg && *vg ? (float)atof(vg) : 1.0f;   /* vk gamma */
        if (!(s_fsr.gamma >= 0.5f && s_fsr.gamma <= 2.0f)) s_fsr.gamma = 1.0f;
    }
    return s_fsr.on && !s_fsr.failed;
}

static VkPipeline vk_fsr_pipe_l(const uint32_t* code, size_t bytes, const char* what, VkPipelineLayout layout);
static VkPipeline vk_fsr_pipe(const uint32_t* code, size_t bytes, const char* what)
{ return vk_fsr_pipe_l(code, bytes, what, s_fsr.pl); }
static VkPipeline vk_fsr_pipe_l(const uint32_t* code, size_t bytes, const char* what, VkPipelineLayout layout)
{
    VkShaderModuleCreateInfo mi = { .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = bytes, .pCode = code };
    VkShaderModule m = VK_NULL_HANDLE;
    if (pvkCreateShaderModule(s_vk.device, &mi, NULL, &m) != VK_SUCCESS) { VK_LOG("upscaler: %s module failed\n", what); return VK_NULL_HANDLE; }
    VkComputePipelineCreateInfo ci = { .sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
        .stage = { .sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = m, .pName = "main" },
        .layout = layout };
    VkPipeline p = VK_NULL_HANDLE;
    const VkResult r = pvkCreateComputePipelines(s_vk.device, VK_NULL_HANDLE, 1, &ci, NULL, &p);
    pvkDestroyShaderModule(s_vk.device, m, NULL);
    if (r != VK_SUCCESS) { VK_LOG("upscaler: %s pipeline failed (%d)\n", what, (int)r); return VK_NULL_HANDLE; }
    return p;
}

static int vk_fsr_init(void)
{
    if (s_fsr.easu) return 0;
    VkDescriptorSetLayoutBinding b[2] = {
        { 0, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL },
        { 1, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL } };
    VkDescriptorSetLayoutCreateInfo di = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 2, .pBindings = b };
    if (pvkCreateDescriptorSetLayout(s_vk.device, &di, NULL, &s_fsr.dsl) != VK_SUCCESS) return -1;
    VkPushConstantRange pr = { VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(vk_fsr_pc) };
    VkPipelineLayoutCreateInfo pli = { .sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &s_fsr.dsl,
                                       .pushConstantRangeCount = 1, .pPushConstantRanges = &pr };
    if (pvkCreatePipelineLayout(s_vk.device, &pli, NULL, &s_fsr.pl) != VK_SUCCESS) return -1;
    VkDescriptorPoolSize ps[2] = { { VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 7 }, { VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 7 } };
    VkDescriptorPoolCreateInfo pci = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, .maxSets = 7, .poolSizeCount = 2, .pPoolSizes = ps };
    if (pvkCreateDescriptorPool(s_vk.device, &pci, NULL, &s_fsr.dp) != VK_SUCCESS) return -1;
    VkDescriptorSetLayout l3[7] = { s_fsr.dsl, s_fsr.dsl, s_fsr.dsl, s_fsr.dsl, s_fsr.dsl, s_fsr.dsl, s_fsr.dsl };
    VkDescriptorSet sets[7];
    VkDescriptorSetAllocateInfo ai = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, .descriptorPool = s_fsr.dp, .descriptorSetCount = 7, .pSetLayouts = l3 };
    if (pvkAllocateDescriptorSets(s_vk.device, &ai, sets) != VK_SUCCESS) return -1;
    s_fsr.ds_in[0] = sets[0]; s_fsr.ds_in[1] = sets[1]; s_fsr.ds_rcas = sets[2]; s_fsr.ds_look = sets[3];
    s_fsr.ds_aa[0] = sets[4]; s_fsr.ds_aa[1] = sets[5]; s_fsr.ds_easu_pre = sets[6];
    VkSamplerCreateInfo sci = { .sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO, .magFilter = VK_FILTER_NEAREST, .minFilter = VK_FILTER_NEAREST,
        .addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE };
    if (pvkCreateSampler(s_vk.device, &sci, NULL, &s_fsr.samp) != VK_SUCCESS) return -1;
    sci.magFilter = sci.minFilter = VK_FILTER_LINEAR;   /* vk aa: FXAA samples between texels */
    if (pvkCreateSampler(s_vk.device, &sci, NULL, &s_fsr.lin) != VK_SUCCESS) return -1;
    s_fsr.easu = vk_fsr_pipe(s_fsr_easu_spv, sizeof s_fsr_easu_spv, "EASU");
    s_fsr.rcas = vk_fsr_pipe(s_fsr_rcas_spv, sizeof s_fsr_rcas_spv, "RCAS");
    if (!s_fsr.easu || !s_fsr.rcas) return -1;
    if (s_fsr.aa == 1) {
        s_fsr.fxaa = vk_fsr_pipe(s_fsr_fxaa_spv, sizeof s_fsr_fxaa_spv, "FXAA");
        VK_LOG("anti-aliasing: FXAA before the upscale%s\n", s_fsr.fxaa ? "" : " FAILED, off");
    }
    if (s_fsr.look_mode || s_fsr.gamma != 1.0f) {   /* vk gamma */
        s_fsr.look = vk_fsr_pipe(s_fsr_look_spv, sizeof s_fsr_look_spv, "look");
        VK_LOG("look: %d (strength %.2f)%s\n", s_fsr.look_mode, (double)s_fsr.look_k, s_fsr.look ? "" : " FAILED, off");
    }
    VK_LOG("upscaler: FSR 1 (EASU + RCAS, sharpness %.2f) %ux%u -> %ux%u\n", (double)s_fsr.sharp,
           s_vk.width, s_vk.height, s_vk.sc_extent.width, s_vk.sc_extent.height);
    return 0;
}

static void vk_fsr_write_set_s(VkDescriptorSet ds, VkSampler smp, VkImageView in, VkImageLayout in_layout, VkImageView out);
static void vk_fsr_write_set(VkDescriptorSet ds, VkImageView in, VkImageLayout in_layout, VkImageView out)
{ vk_fsr_write_set_s(ds, s_fsr.samp, in, in_layout, out); }
static void vk_fsr_write_set_s(VkDescriptorSet ds, VkSampler smp, VkImageView in, VkImageLayout in_layout, VkImageView out)
{
    VkDescriptorImageInfo ii = { .sampler = smp, .imageView = in, .imageLayout = in_layout };
    VkDescriptorImageInfo oi = { .imageView = out, .imageLayout = VK_IMAGE_LAYOUT_GENERAL };
    VkWriteDescriptorSet wr[2] = {
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = ds, .dstBinding = 0, .descriptorCount = 1,
          .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .pImageInfo = &ii },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = ds, .dstBinding = 1, .descriptorCount = 1,
          .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .pImageInfo = &oi } };
    pvkUpdateDescriptorSets(s_vk.device, 2, wr, 0, NULL);
}

/* vk smaa: SMAA 1x on the guest-size frame, in place of FXAA's pass: src -> edges (e) -> blending weights (w) ->
 * neighbourhood blending into pre, which EASU reads. One set layout for the three passes (bindings 0..2 sampled,
 * 3 the storage output); e and w are RGBA8 at guest size; the lookup textures are uploaded on first use. */
static struct {
    int failed, uploaded;
    VkDescriptorSetLayout dsl; VkPipelineLayout pl; VkDescriptorPool dp;
    VkPipeline edges, weights, blend;
    VkDescriptorSet ds_edges[2], ds_weights, ds_blend[2]; VkImageView ds_view[2];
    vk_image area, search, e, w; vk_buffer up; u32 iw, ih;
} s_smaa;

static int vk_smaa_init(void)
{
    VkDescriptorSetLayoutBinding b[4];
    for (u32 i = 0; i < 4; i++)
        b[i] = (VkDescriptorSetLayoutBinding){ i, i < 3 ? VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER : VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                               1, VK_SHADER_STAGE_COMPUTE_BIT, NULL };
    VkDescriptorSetLayoutCreateInfo di = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 4, .pBindings = b };
    if (pvkCreateDescriptorSetLayout(s_vk.device, &di, NULL, &s_smaa.dsl) != VK_SUCCESS) return -1;
    VkPushConstantRange pr = { VK_SHADER_STAGE_COMPUTE_BIT, 0, 16 };
    VkPipelineLayoutCreateInfo pli = { .sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &s_smaa.dsl,
                                       .pushConstantRangeCount = 1, .pPushConstantRanges = &pr };
    if (pvkCreatePipelineLayout(s_vk.device, &pli, NULL, &s_smaa.pl) != VK_SUCCESS) return -1;
    VkDescriptorPoolSize ps[2] = { { VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 15 }, { VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 5 } };
    VkDescriptorPoolCreateInfo pci = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, .maxSets = 5, .poolSizeCount = 2, .pPoolSizes = ps };
    if (pvkCreateDescriptorPool(s_vk.device, &pci, NULL, &s_smaa.dp) != VK_SUCCESS) return -1;
    VkDescriptorSetLayout l5[5] = { s_smaa.dsl, s_smaa.dsl, s_smaa.dsl, s_smaa.dsl, s_smaa.dsl };
    VkDescriptorSet sets[5];
    VkDescriptorSetAllocateInfo ai = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, .descriptorPool = s_smaa.dp, .descriptorSetCount = 5, .pSetLayouts = l5 };
    if (pvkAllocateDescriptorSets(s_vk.device, &ai, sets) != VK_SUCCESS) return -1;
    s_smaa.ds_edges[0] = sets[0]; s_smaa.ds_edges[1] = sets[1]; s_smaa.ds_weights = sets[2]; s_smaa.ds_blend[0] = sets[3]; s_smaa.ds_blend[1] = sets[4];
    s_smaa.edges = vk_fsr_pipe_l(s_smaa_edges_spv, sizeof s_smaa_edges_spv, "SMAA edges", s_smaa.pl);
    s_smaa.weights = vk_fsr_pipe_l(s_smaa_weights_spv, sizeof s_smaa_weights_spv, "SMAA weights", s_smaa.pl);
    s_smaa.blend = vk_fsr_pipe_l(s_smaa_blend_spv, sizeof s_smaa_blend_spv, "SMAA blend", s_smaa.pl);
    if (!s_smaa.edges || !s_smaa.weights || !s_smaa.blend) return -1;
    if (vk_create_image(&s_smaa.area, VK_FORMAT_R8G8_UNORM, AREATEX_WIDTH, AREATEX_HEIGHT, VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, VK_IMAGE_ASPECT_COLOR_BIT) ||
        vk_create_image(&s_smaa.search, VK_FORMAT_R8_UNORM, SEARCHTEX_WIDTH, SEARCHTEX_HEIGHT, VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, VK_IMAGE_ASPECT_COLOR_BIT) ||
        vk_create_host_buffer(&s_smaa.up, AREATEX_SIZE + SEARCHTEX_SIZE, VK_BUFFER_USAGE_TRANSFER_SRC_BIT) || !s_smaa.up.coherent)
        return -1;
    memcpy(s_smaa.up.ptr, areaTexBytes, AREATEX_SIZE);
    memcpy((unsigned char*)s_smaa.up.ptr + AREATEX_SIZE, searchTexBytes, SEARCHTEX_SIZE);
    return 0;
}

/* Bindings 0..2 sampled (NULL views left out), 3 the storage output. */
static void vk_smaa_write_set(VkDescriptorSet ds, VkImageView v0, VkImageView v1, VkImageView v2, VkImageView out)
{
    const VkImageView in[3] = { v0, v1, v2 };
    VkDescriptorImageInfo ii[4]; VkWriteDescriptorSet wr[4]; u32 n = 0;
    for (u32 i = 0; i < 4; i++) {
        const VkImageView v = i < 3 ? in[i] : out;
        if (!v) continue;
        ii[n] = (VkDescriptorImageInfo){ .sampler = i < 3 ? (i == 2 ? s_fsr.samp : s_fsr.lin) : VK_NULL_HANDLE,
                                         .imageView = v, .imageLayout = VK_IMAGE_LAYOUT_GENERAL };   /* search: point, the rest linear */
        wr[n] = (VkWriteDescriptorSet){ .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = ds, .dstBinding = i, .descriptorCount = 1,
            .descriptorType = i < 3 ? VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER : VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .pImageInfo = &ii[n] };
        n++;
    }
    pvkUpdateDescriptorSets(s_vk.device, n, wr, 0, NULL);
}

/* Records the three passes, src (slot's set) -> s_fsr.pre; pre is left written (the caller's barrier follows). */
static void vk_smaa_record(int slot)
{
    if (!s_smaa.uploaded) {
        vk_img_barrier(s_smaa.area.img, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL, 0, VK_ACCESS_TRANSFER_WRITE_BIT,
                       VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT);
        vk_img_barrier(s_smaa.search.img, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL, 0, VK_ACCESS_TRANSFER_WRITE_BIT,
                       VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT);
        VkBufferImageCopy c = { .imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 }, .imageExtent = { AREATEX_WIDTH, AREATEX_HEIGHT, 1 } };
        pvkCmdCopyBufferToImage(s_vk.cmd, s_smaa.up.buf, s_smaa.area.img, VK_IMAGE_LAYOUT_GENERAL, 1, &c);
        c.bufferOffset = AREATEX_SIZE; c.imageExtent = (VkExtent3D){ SEARCHTEX_WIDTH, SEARCHTEX_HEIGHT, 1 };
        pvkCmdCopyBufferToImage(s_vk.cmd, s_smaa.up.buf, s_smaa.search.img, VK_IMAGE_LAYOUT_GENERAL, 1, &c);
        vk_img_barrier(s_smaa.area.img, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT,
                       VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
        vk_img_barrier(s_smaa.search.img, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT,
                       VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
        s_smaa.uploaded = 1;
    }
    /* e/w: fresh contents every frame (the previous frame's passes may still read them) */
    vk_img_barrier(s_smaa.e.img, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL, 0, VK_ACCESS_SHADER_WRITE_BIT,
                   VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
    vk_img_barrier(s_smaa.w.img, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL, 0, VK_ACCESS_SHADER_WRITE_BIT,
                   VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
    const float m[4] = { 1.0f / (float)s_vk.width, 1.0f / (float)s_vk.height, (float)s_vk.width, (float)s_vk.height };
    const u32 gx = (s_vk.width + 7) / 8, gy = (s_vk.height + 7) / 8;
    const VkPipeline pipe[3] = { s_smaa.edges, s_smaa.weights, s_smaa.blend };
    const VkDescriptorSet set[3] = { s_smaa.ds_edges[slot], s_smaa.ds_weights, s_smaa.ds_blend[slot] };
    for (int p = 0; p < 3; p++) {
        if (p) {   /* the previous pass's output, read by this one */
            vk_img_barrier(p == 1 ? s_smaa.e.img : s_smaa.w.img, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_SHADER_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT,
                           VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
        }
        pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pipe[p]);
        pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_smaa.pl, 0, 1, &set[p], 0, NULL);
        pvkCmdPushConstants(s_vk.cmd, s_smaa.pl, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof m, m);
        pvkCmdDispatch(s_vk.cmd, gx, gy, 1);
    }
}

/* vk smaa dump (debug, BC-250): PS3_AA_DUMP=<prefix> writes the guest-size frame before (<prefix>.<n>.src.ppm) and
 * after (<prefix>.<n>.aa.ppm) the anti-aliasing pass, full size, every 300 frames (the PS3RECOMP_VK_DUMP frames are
 * taken from the colour target, before any of this). */
static vk_buffer s_aa_rb; static int s_aa_pending; static unsigned s_aa_n; static u32 s_aa_w, s_aa_h;
static void vk_aa_dump_collect(void)
{
    if (!s_aa_pending) return;
    s_aa_pending = 0;
    pvkDeviceWaitIdle(s_vk.device);
    vk_invalidate(&s_aa_rb);
    for (int k = 0; k < 2; k++) {
        char path[512]; snprintf(path, sizeof path, "%s.%03u.%s.ppm", getenv("PS3_AA_DUMP"), s_aa_n, k ? "aa" : "src");
        FILE* f = fopen(path, "wb"); if (!f) continue;
        fprintf(f, "P6\n%u %u\n255\n", s_aa_w, s_aa_h);
        const unsigned char* px = (const unsigned char*)s_aa_rb.ptr + (size_t)k * s_aa_w * s_aa_h * 4;
        for (size_t i = 0; i < (size_t)s_aa_w * s_aa_h; i++) fwrite(px + i * 4, 1, 3, f);
        fclose(f);
    }
    s_aa_n++;
}

/* Records the upscale of `src` (guest size, layout GENERAL, `slot` 0 = the colour target, 1 = the generated
 * frame) into swapchain image `dst`, which the caller has put in TRANSFER_DST_OPTIMAL; leaves it there.
 * Returns 0 when it recorded, -1 when the caller should blit as before. */
/* vk look dump (debug, BC-250): PS3_LOOK_DUMP=<prefix> writes the final upscaled+look frame as <prefix>.<n>.ppm
 * (half size) every 300 frames: the only way to see the look pass's real GPU output on the host. */
static vk_buffer s_look_rb; static int s_look_pending; static unsigned s_look_n; static u32 s_look_w, s_look_h;
static void vk_look_dump_collect(void)
{
    if (!s_look_pending) return;
    s_look_pending = 0;
    pvkDeviceWaitIdle(s_vk.device);
    vk_invalidate(&s_look_rb);
    char path[512]; snprintf(path, sizeof path, "%s.%03u.ppm", getenv("PS3_LOOK_DUMP"), s_look_n++);
    FILE* f = fopen(path, "wb"); if (!f) return;
    const u32 w = s_look_w / 2, h = s_look_h / 2;
    fprintf(f, "P6\n%u %u\n255\n", w, h);
    const unsigned char* px = (const unsigned char*)s_look_rb.ptr;
    for (u32 y = 0; y < h; y++) for (u32 x = 0; x < w; x++) fwrite(px + ((size_t)(y * 2) * s_look_w + x * 2) * 4, 1, 3, f);
    fclose(f);
}

static int vk_fsr_apply(int slot, VkImage src, VkImageView src_view, VkImage dst)
{
    if (!vk_fsr_enabled()) return -1;
    if (s_look_pending) vk_look_dump_collect();
    if (s_aa_pending) vk_aa_dump_collect();   /* vk smaa dump */
    {   /* PS3_LOOK_CYCLE=1 (debug): every look in turn, 90 frames each (with PS3_LOOK_DUMP: one dump of each) */
        static int cyc = -1; if (cyc < 0) { const char* e = getenv("PS3_LOOK_CYCLE"); cyc = e && *e == '1'; }
        if (cyc) s_fsr.look_mode = (int)((s_fsr.frames / 90u) % 12u);
    }
    const u32 W = s_vk.sc_extent.width, H = s_vk.sc_extent.height;
    if (W <= s_vk.width && H <= s_vk.height) return -1;   /* no upscale to do */
    if (!s_fsr.easu && vk_fsr_init()) { s_fsr.failed = 1; VK_LOG("upscaler: off (setup failed), bilinear\n"); return -1; }
    /* vk quickmenu: LOOK and ANTI-ALIASING can be switched on in game; their pipelines are made on first use */
    if ((s_fsr.look_mode || s_fsr.gamma != 1.0f) && !s_fsr.look) {   /* vk gamma */
        static int tried; if (!tried++) { s_fsr.look = vk_fsr_pipe(s_fsr_look_spv, sizeof s_fsr_look_spv, "look");
            if (s_fsr.look && s_fsr.mid.img) vk_fsr_write_set(s_fsr.ds_look, s_fsr.out.view, VK_IMAGE_LAYOUT_GENERAL, s_fsr.mid.view); }
    }
    if (s_fsr.aa == 2 && !s_smaa.blend && !s_smaa.failed) {   /* vk smaa: made on first use; FXAA if it fails */
        if (vk_smaa_init()) { s_smaa.failed = 1; s_fsr.aa = 1; VK_LOG("anti-aliasing: SMAA setup failed, FXAA instead\n"); }
        else VK_LOG("anti-aliasing: SMAA 1x before the upscale\n");
    }
    if (s_fsr.aa == 2 && s_smaa.failed) s_fsr.aa = 1;
    if (s_fsr.aa == 1 && !s_fsr.fxaa) {
        static int tried; if (!tried++) { s_fsr.fxaa = vk_fsr_pipe(s_fsr_fxaa_spv, sizeof s_fsr_fxaa_spv, "FXAA"); s_fsr.pw = 0; }
    }
    if (!s_fsr.mid.img || s_fsr.w != W || s_fsr.h != H) {
        if (s_fsr.mid.img) { pvkDeviceWaitIdle(s_vk.device); vk_destroy_image(&s_fsr.mid); vk_destroy_image(&s_fsr.out); }
        if (vk_create_image(&s_fsr.mid, VK_FORMAT_R8G8B8A8_UNORM, W, H, VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT, VK_IMAGE_ASPECT_COLOR_BIT) ||
            vk_create_image(&s_fsr.out, VK_FORMAT_R8G8B8A8_UNORM, W, H, VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_SAMPLED_BIT, VK_IMAGE_ASPECT_COLOR_BIT)) {
            s_fsr.failed = 1; VK_LOG("upscaler: off (images failed), bilinear\n"); return -1; }
        s_fsr.w = W; s_fsr.h = H;
        s_fsr.ds_in_view[0] = s_fsr.ds_in_view[1] = VK_NULL_HANDLE;
        s_fsr.pw = 0;   /* vk aa: ds_easu_pre names the old mid */
        vk_fsr_write_set(s_fsr.ds_rcas, s_fsr.mid.view, VK_IMAGE_LAYOUT_GENERAL, s_fsr.out.view);
        if (s_fsr.look) vk_fsr_write_set(s_fsr.ds_look, s_fsr.out.view, VK_IMAGE_LAYOUT_GENERAL, s_fsr.mid.view);   /* vk look: out -> mid */
    }
    if (s_fsr.ds_in_view[slot] != src_view) {
        vk_fsr_write_set(s_fsr.ds_in[slot], src_view, VK_IMAGE_LAYOUT_GENERAL, s_fsr.mid.view);
        s_fsr.ds_in_view[slot] = src_view;
    }
    /* vk aa: src -> FXAA (1) or SMAA (2, vk smaa) -> pre (guest size) -> EASU */
    int use_aa = s_fsr.aa == 2 && s_smaa.blend ? 2 : s_fsr.aa == 1 && s_fsr.fxaa ? 1 : 0;
    if (use_aa) {
        if (!s_fsr.pre.img || s_fsr.pw != s_vk.width || s_fsr.ph != s_vk.height) {
            if (s_fsr.pre.img) { pvkDeviceWaitIdle(s_vk.device); vk_destroy_image(&s_fsr.pre); }
            if (vk_create_image(&s_fsr.pre, VK_FORMAT_R8G8B8A8_UNORM, s_vk.width, s_vk.height, VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT, VK_IMAGE_ASPECT_COLOR_BIT)) {
                s_fsr.aa = 0; use_aa = 0; VK_LOG("anti-aliasing: off (image failed)\n");
            } else {
                s_fsr.pw = s_vk.width; s_fsr.ph = s_vk.height; s_fsr.ds_aa_view[0] = s_fsr.ds_aa_view[1] = VK_NULL_HANDLE;
                s_smaa.ds_view[0] = s_smaa.ds_view[1] = VK_NULL_HANDLE;   /* vk smaa: ds_blend names the old pre */
                vk_fsr_write_set(s_fsr.ds_easu_pre, s_fsr.pre.view, VK_IMAGE_LAYOUT_GENERAL, s_fsr.mid.view);
            }
        }
    }
    if (use_aa == 2 && (!s_smaa.e.img || s_smaa.iw != s_vk.width || s_smaa.ih != s_vk.height)) {   /* vk smaa: e/w at guest size */
        if (s_smaa.e.img) { pvkDeviceWaitIdle(s_vk.device); vk_destroy_image(&s_smaa.e); vk_destroy_image(&s_smaa.w); }
        if (vk_create_image(&s_smaa.e, VK_FORMAT_R8G8B8A8_UNORM, s_vk.width, s_vk.height, VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT, VK_IMAGE_ASPECT_COLOR_BIT) ||
            vk_create_image(&s_smaa.w, VK_FORMAT_R8G8B8A8_UNORM, s_vk.width, s_vk.height, VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT, VK_IMAGE_ASPECT_COLOR_BIT)) {
            s_smaa.failed = 1; s_fsr.aa = 1; use_aa = 0; VK_LOG("anti-aliasing: SMAA images failed, FXAA instead\n");
        } else {
            s_smaa.iw = s_vk.width; s_smaa.ih = s_vk.height; s_smaa.ds_view[0] = s_smaa.ds_view[1] = VK_NULL_HANDLE;
            vk_smaa_write_set(s_smaa.ds_weights, s_smaa.e.view, s_smaa.area.view, s_smaa.search.view, s_smaa.w.view);
        }
    }
    if (use_aa == 1 && s_fsr.ds_aa_view[slot] != src_view) {
        vk_fsr_write_set_s(s_fsr.ds_aa[slot], s_fsr.lin, src_view, VK_IMAGE_LAYOUT_GENERAL, s_fsr.pre.view);
        s_fsr.ds_aa_view[slot] = src_view;
    }
    if (use_aa == 2 && s_smaa.ds_view[slot] != src_view) {
        vk_smaa_write_set(s_smaa.ds_edges[slot], src_view, VK_NULL_HANDLE, VK_NULL_HANDLE, s_smaa.e.view);
        vk_smaa_write_set(s_smaa.ds_blend[slot], src_view, s_smaa.w.view, VK_NULL_HANDLE, s_fsr.pre.view);
        s_smaa.ds_view[slot] = src_view;
    }
    vk_rp_close();
    /* src: earlier writes (draws, copies, the generator) visible to the compute reads */
    vk_img_barrier(src, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_MEMORY_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT,
                   VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
    /* mid/out: fresh contents (an earlier frame in this command buffer may still read them) */
    vk_img_barrier(s_fsr.mid.img, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL, 0, VK_ACCESS_SHADER_WRITE_BIT,
                   VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
    vk_img_barrier(s_fsr.out.img, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL, 0, VK_ACCESS_SHADER_WRITE_BIT,
                   VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
    const float sx = (float)s_vk.width / (float)W, sy = (float)s_vk.height / (float)H;
    vk_fsr_pc pc = { (int32_t)s_vk.width, (int32_t)s_vk.height, (int32_t)W, (int32_t)H,
                     { sx, sy, 0.5f * sx - 0.5f, 0.5f * sy - 0.5f }, exp2f(-s_fsr.sharp) };
    if (use_aa) {
        vk_img_barrier(s_fsr.pre.img, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL, 0, VK_ACCESS_SHADER_WRITE_BIT,
                       VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
        if (use_aa == 2) vk_smaa_record(slot);   /* vk smaa */
        else {
            pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_fsr.fxaa);
            pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_fsr.pl, 0, 1, &s_fsr.ds_aa[slot], 0, NULL);
            pvkCmdPushConstants(s_vk.cmd, s_fsr.pl, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, &pc);
            pvkCmdDispatch(s_vk.cmd, (s_vk.width + 7) / 8, (s_vk.height + 7) / 8, 1);
        }
        vk_img_barrier(s_fsr.pre.img, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_SHADER_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT,
                       VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
    }
    pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_fsr.easu);
    pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_fsr.pl, 0, 1, use_aa ? &s_fsr.ds_easu_pre : &s_fsr.ds_in[slot], 0, NULL);
    pvkCmdPushConstants(s_vk.cmd, s_fsr.pl, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, &pc);
    pvkCmdDispatch(s_vk.cmd, (W + 7) / 8, (H + 7) / 8, 1);
    vk_img_barrier(s_fsr.mid.img, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_SHADER_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT,
                   VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
    pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_fsr.rcas);
    pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_fsr.pl, 0, 1, &s_fsr.ds_rcas, 0, NULL);
    pvkCmdPushConstants(s_vk.cmd, s_fsr.pl, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, &pc);
    pvkCmdDispatch(s_vk.cmd, (W + 7) / 8, (H + 7) / 8, 1);
    VkImage fin = s_fsr.out.img;
    if (s_fsr.look && (s_fsr.look_mode || s_fsr.gamma != 1.0f)) {   /* vk gamma; vk look: RCAS result (out) -> look -> mid, which is then the blit source */
        vk_img_barrier(s_fsr.out.img, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_SHADER_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT,
                       VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
        vk_img_barrier(s_fsr.mid.img, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_SHADER_READ_BIT, VK_ACCESS_SHADER_WRITE_BIT,
                       VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
        vk_fsr_pc lp = pc; lp.con0[0] = (float)s_fsr.look_mode; lp.con0[1] = s_fsr.look_k; lp.con0[2] = s_fsr.gamma;   /* vk gamma */
        pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_fsr.look);
        pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_fsr.pl, 0, 1, &s_fsr.ds_look, 0, NULL);
        pvkCmdPushConstants(s_vk.cmd, s_fsr.pl, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof lp, &lp);
        pvkCmdDispatch(s_vk.cmd, (W + 7) / 8, (H + 7) / 8, 1);
        fin = s_fsr.mid.img;
    }
    vk_img_barrier(fin, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_ACCESS_SHADER_WRITE_BIT, VK_ACCESS_TRANSFER_READ_BIT,
                   VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT);
    VkImageBlit bl = { .srcSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 },
        .srcOffsets = { { 0, 0, 0 }, { (int32_t)W, (int32_t)H, 1 } },
        .dstSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 },
        .dstOffsets = { { 0, 0, 0 }, { (int32_t)W, (int32_t)H, 1 } } };
    pvkCmdBlitImage(s_vk.cmd, fin, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, dst, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &bl, VK_FILTER_NEAREST);
    if (getenv("PS3_LOOK_DUMP") && s_fsr.frames % (getenv("PS3_LOOK_CYCLE") ? 90u : 300u) == (getenv("PS3_LOOK_CYCLE") ? 89u : 299u) && !s_look_pending) {   /* vk look dump */
        const VkDeviceSize need = (VkDeviceSize)W * H * 4u;
        if (s_look_rb.size < need) { if (s_look_rb.buf) vk_destroy_buffer(&s_look_rb); vk_create_host_buffer(&s_look_rb, need, VK_BUFFER_USAGE_TRANSFER_DST_BIT); }
        if (s_look_rb.buf) {
            VkBufferImageCopy rg = { .imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 }, .imageExtent = { W, H, 1 } };
            pvkCmdCopyImageToBuffer(s_vk.cmd, fin, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, s_look_rb.buf, 1, &rg);
            s_look_pending = 1; s_look_w = W; s_look_h = H;
        }
    }
    if (use_aa && getenv("PS3_AA_DUMP") && s_fsr.frames % 300u == 299u && !s_aa_pending) {   /* vk smaa dump */
        const VkDeviceSize one = (VkDeviceSize)s_vk.width * s_vk.height * 4u;
        if (s_aa_rb.size < 2 * one) { if (s_aa_rb.buf) vk_destroy_buffer(&s_aa_rb); vk_create_host_buffer(&s_aa_rb, 2 * one, VK_BUFFER_USAGE_TRANSFER_DST_BIT); }
        if (s_aa_rb.buf) {
            vk_img_barrier(s_fsr.pre.img, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_SHADER_WRITE_BIT, VK_ACCESS_TRANSFER_READ_BIT,
                           VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT);
            vk_img_barrier(src, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_MEMORY_WRITE_BIT, VK_ACCESS_TRANSFER_READ_BIT,
                           VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT);
            VkBufferImageCopy rg = { .imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 }, .imageExtent = { s_vk.width, s_vk.height, 1 } };
            pvkCmdCopyImageToBuffer(s_vk.cmd, src, VK_IMAGE_LAYOUT_GENERAL, s_aa_rb.buf, 1, &rg);
            rg.bufferOffset = one;
            pvkCmdCopyImageToBuffer(s_vk.cmd, s_fsr.pre.img, VK_IMAGE_LAYOUT_GENERAL, s_aa_rb.buf, 1, &rg);
            s_aa_pending = 1; s_aa_w = s_vk.width; s_aa_h = s_vk.height;
        }
    }
    s_fsr.frames++;
    return 0;
}
