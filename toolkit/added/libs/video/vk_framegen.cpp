/* vk framegen: MihawkGen frame generation (libs/video/framegen/, GPL-3.0-or-later, Copyright (C) 2026 Mihawk,
 * https://github.com/mihawk-99/PS5_MihawkGen commit c57232a9) built into the Vulkan backend: the neural method
 * makes the frame halfway between two finished frames from their colour alone (no motion vectors or depth,
 * which a PS3 game does not give). The four sources are unchanged; their Vulkan calls go through fg_vkshim.h.
 * The network weights are embedded (fg_network_blob.inc). C interface: vk_framegen.h. */
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include "framegen/fg_vkshim.h"
PFN_vkCmdPipelineBarrier fgvk_CmdPipelineBarrier;
PFN_vkUpdateDescriptorSets fgvk_UpdateDescriptorSets;
PFN_vkDestroySampler fgvk_DestroySampler;
PFN_vkDestroyPipeline fgvk_DestroyPipeline;
PFN_vkCreateSampler fgvk_CreateSampler;
PFN_vkFreeMemory fgvk_FreeMemory;
PFN_vkDestroyShaderModule fgvk_DestroyShaderModule;
PFN_vkDestroyPipelineLayout fgvk_DestroyPipelineLayout;
PFN_vkDestroyDescriptorSetLayout fgvk_DestroyDescriptorSetLayout;
PFN_vkDestroyDescriptorPool fgvk_DestroyDescriptorPool;
PFN_vkCreateShaderModule fgvk_CreateShaderModule;
PFN_vkCreatePipelineLayout fgvk_CreatePipelineLayout;
PFN_vkCreateDescriptorSetLayout fgvk_CreateDescriptorSetLayout;
PFN_vkCreateDescriptorPool fgvk_CreateDescriptorPool;
PFN_vkCreateComputePipelines fgvk_CreateComputePipelines;
PFN_vkCmdWriteTimestamp fgvk_CmdWriteTimestamp;
PFN_vkCmdPushConstants fgvk_CmdPushConstants;
PFN_vkCmdDispatch fgvk_CmdDispatch;
PFN_vkCmdBindPipeline fgvk_CmdBindPipeline;
PFN_vkCmdBindDescriptorSets fgvk_CmdBindDescriptorSets;
PFN_vkAllocateMemory fgvk_AllocateMemory;
PFN_vkAllocateDescriptorSets fgvk_AllocateDescriptorSets;
PFN_vkUnmapMemory fgvk_UnmapMemory;
PFN_vkMapMemory fgvk_MapMemory;
PFN_vkGetImageMemoryRequirements fgvk_GetImageMemoryRequirements;
PFN_vkGetBufferMemoryRequirements fgvk_GetBufferMemoryRequirements;
PFN_vkDestroyImageView fgvk_DestroyImageView;
PFN_vkDestroyImage fgvk_DestroyImage;
PFN_vkDestroyBuffer fgvk_DestroyBuffer;
PFN_vkCreateImageView fgvk_CreateImageView;
PFN_vkCreateImage fgvk_CreateImage;
PFN_vkCreateBuffer fgvk_CreateBuffer;
PFN_vkCmdClearColorImage fgvk_CmdClearColorImage;
PFN_vkBindImageMemory fgvk_BindImageMemory;
PFN_vkBindBufferMemory fgvk_BindBufferMemory;
PFN_vkGetPhysicalDeviceMemoryProperties fgvk_GetPhysicalDeviceMemoryProperties;
#include "framegen/framegen.h"
#include <cstdio>
#include "framegen/fg_network_blob.inc"
#include "vk_framegen.h"

static fg_context* s_fgctx;
extern "C" int vkfg_init(VkInstance inst, VkPhysicalDevice phys, VkDevice dev, PFN_vkGetInstanceProcAddr gipa,
                         uint32_t w, uint32_t h, uint32_t slots, char* err, size_t err_size)
{
    if (s_fgctx) return 0;
    PFN_vkGetDeviceProcAddr gdpa = (PFN_vkGetDeviceProcAddr)gipa(inst, "vkGetDeviceProcAddr");
    if (!gdpa) { snprintf(err, err_size, "no vkGetDeviceProcAddr"); return -1; }
#define FGL(f) if (!(fgvk_##f = (PFN_vk##f)gdpa(dev, "vk" #f))) { snprintf(err, err_size, "no vk" #f); return -1; }
    FGL(CmdPipelineBarrier)
    FGL(UpdateDescriptorSets)
    FGL(DestroySampler)
    FGL(DestroyPipeline)
    FGL(CreateSampler)
    FGL(FreeMemory)
    FGL(DestroyShaderModule)
    FGL(DestroyPipelineLayout)
    FGL(DestroyDescriptorSetLayout)
    FGL(DestroyDescriptorPool)
    FGL(CreateShaderModule)
    FGL(CreatePipelineLayout)
    FGL(CreateDescriptorSetLayout)
    FGL(CreateDescriptorPool)
    FGL(CreateComputePipelines)
    FGL(CmdWriteTimestamp)
    FGL(CmdPushConstants)
    FGL(CmdDispatch)
    FGL(CmdBindPipeline)
    FGL(CmdBindDescriptorSets)
    FGL(AllocateMemory)
    FGL(AllocateDescriptorSets)
    FGL(UnmapMemory)
    FGL(MapMemory)
    FGL(GetImageMemoryRequirements)
    FGL(GetBufferMemoryRequirements)
    FGL(DestroyImageView)
    FGL(DestroyImage)
    FGL(DestroyBuffer)
    FGL(CreateImageView)
    FGL(CreateImage)
    FGL(CreateBuffer)
    FGL(CmdClearColorImage)
    FGL(BindImageMemory)
    FGL(BindBufferMemory)
#undef FGL
    if (!(fgvk_GetPhysicalDeviceMemoryProperties = (PFN_vkGetPhysicalDeviceMemoryProperties)gipa(inst, "vkGetPhysicalDeviceMemoryProperties"))) {
        snprintf(err, err_size, "no vkGetPhysicalDeviceMemoryProperties"); return -1; }
    fg_create_info ci{};
    ci.device = dev; ci.physical_device = phys; ci.width = w; ci.height = h; ci.slots = slots;
    ci.output_format = VK_FORMAT_R8G8B8A8_UNORM;
    if (const char* bad = fg_check_create_info(&ci)) { snprintf(err, err_size, "%s", bad); return -1; }
    if (fg_context_create(&ci, &s_fgctx, err, err_size) != VK_SUCCESS) { s_fgctx = nullptr; return -1; }
    if (fg_context_load_network(s_fgctx, s_fg_network_blob, sizeof s_fg_network_blob, err, err_size) != VK_SUCCESS ||
        !fg_method_available(s_fgctx, FG_METHOD_NEURAL)) { fg_context_destroy(s_fgctx); s_fgctx = nullptr; return -1; }
    return 0;
}
extern "C" void vkfg_record(VkCommandBuffer cmd, uint32_t slot, VkImageView prev, VkImageView next, VkImageView out, float t)
{
    if (!s_fgctx) return;
    fg_frame_pair p{};
    p.prev_color = prev; p.next_color = next; p.t = t;
    fg_record_generate(s_fgctx, cmd, slot, FG_METHOD_NEURAL, &p, out);
}
/* vk fg flow: mvwarp along a motion field (backward, uv: next minus previous, any resolution, sampled linearly).
 * The method reads no depth, but every input binding is written: the motion view stands in for the depths. */
extern "C" void vkfg_record_mv(VkCommandBuffer cmd, uint32_t slot, VkImageView prev, VkImageView next, VkImageView motion,
                               VkImageView out, float t)
{
    if (!s_fgctx) return;
    fg_frame_pair p{};
    p.prev_color = prev; p.next_color = next; p.t = t;
    p.prev_depth = motion; p.next_depth = motion; p.next_motion = motion;
    fg_record_generate(s_fgctx, cmd, slot, FG_METHOD_MVWARP, &p, out);
}
