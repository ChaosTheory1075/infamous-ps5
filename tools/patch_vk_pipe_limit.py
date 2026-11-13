
# vk pipe limit: the Vulkan engine pipeline table held 512 while the engine allows 8192
# Once a session had built 512 pipelines (FoB on the console: the cutscenes, then the level), every
# new one failed with no log and its draws were dropped ("pipeline") -- Cole's body and a roof went
# invisible while everything built earlier still drew. The table now matches the engine's limit,
# and running out or failing to translate says so.
edit("libs/video/rsx_vulkan_backend.c",
     '''#define VK_ENG_MAX_PIPE   512''',
     '''#define VK_ENG_MAX_PIPE   8192   /* = ENG_MAX_PIPELINES (rsx_draw_engine.c); was 512 */''',
     "vk pipe limit size")
edit("libs/video/rsx_vulkan_backend.c",
     '''    if (slot == VK_ENG_MAX_PIPE) return 0;
    vk_eng_pipe* P = &s_epipe[slot];
    memset(P, 0, sizeof *P);
    if (vk_eng_translate(vs_hlsl, RSX_SHADER_STAGE_VERTEX, &P->vs)) return 0;
    if (vk_eng_translate(ps_hlsl, RSX_SHADER_STAGE_FRAGMENT, &P->fs)) {
        pvkDestroyShaderModule(s_vk.device, P->vs, NULL); memset(P, 0, sizeof *P); return 0;
    }''',
     '''    if (slot == VK_ENG_MAX_PIPE) {
        static int told; if (!told++) VK_LOG("engine: pipeline table full (%u): new pipelines fail and their draws are dropped\\n", VK_ENG_MAX_PIPE);
        return 0;
    }
    vk_eng_pipe* P = &s_epipe[slot];
    memset(P, 0, sizeof *P);
    if (vk_eng_translate(vs_hlsl, RSX_SHADER_STAGE_VERTEX, &P->vs)) {
        static int told; if (told++ < 8) VK_LOG("engine: vertex program failed to translate: its draws are dropped\\n");
        return 0;
    }
    if (vk_eng_translate(ps_hlsl, RSX_SHADER_STAGE_FRAGMENT, &P->fs)) {
        static int told; if (told++ < 8) VK_LOG("engine: fragment program failed to translate: its draws are dropped\\n");
        pvkDestroyShaderModule(s_vk.device, P->vs, NULL); memset(P, 0, sizeof *P); return 0;
    }''',
     "vk pipe limit log")
