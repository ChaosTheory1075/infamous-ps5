/* vk framegen (vk_framegen.cpp): MihawkGen's neural frame generation for the Vulkan backend. */
#pragma once
#ifdef __cplusplus
extern "C" {
#endif
int  vkfg_init(VkInstance inst, VkPhysicalDevice phys, VkDevice dev, PFN_vkGetInstanceProcAddr gipa,
               uint32_t w, uint32_t h, uint32_t slots, char* err, size_t err_size);
void vkfg_record(VkCommandBuffer cmd, uint32_t slot, VkImageView prev, VkImageView next, VkImageView out, float t);
void vkfg_record_mv(VkCommandBuffer cmd, uint32_t slot, VkImageView prev, VkImageView next, VkImageView motion,
                    VkImageView out, float t);   /* vk fg flow */
#ifdef __cplusplus
}
#endif
