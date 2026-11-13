
# vk sampler limit: the engine sampler cache held 64 and then handed every new sampler state the default
# A long session meets more than 64 (filter x wrap x LOD) combinations; from the 65th on, textures were
# sampled with the default wrap/filter. 1024 is far under maxSamplerAllocationCount (>= 4000); full says so.
edit("libs/video/rsx_vulkan_backend.c",
     '''#define VK_ENG_SAMP_CACHE 64''',
     '''#define VK_ENG_SAMP_CACHE 1024   /* was 64 */''',
     "vk samp limit size")
edit("libs/video/rsx_vulkan_backend.c",
     '''    if (s_esamp_count >= VK_ENG_SAMP_CACHE) return s_vk.sampler;''',
     '''    if (s_esamp_count >= VK_ENG_SAMP_CACHE) {
        static int told; if (!told++) VK_LOG("engine: sampler cache full (%u): new sampler states use the default\\n", VK_ENG_SAMP_CACHE);
        return s_vk.sampler;
    }''',
     "vk samp limit log")
