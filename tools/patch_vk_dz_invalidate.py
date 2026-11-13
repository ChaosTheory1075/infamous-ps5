
# vk dz invalidate: drop depth->RGBA8 cache entries whose target or source depth is released (aliasing fix)
# vk_eng_depth_rgba8_gpu keeps one RGBA8 colour target per (depth, w, h) in s_dz_cache and trusts an
# entry while s_eobj[rt] is a colour object with the same VkImage. The engine releases those targets
# itself (eng_zdepth_get / the snapshot refresh: texture_release of the old copy), vk_eng_alloc hands
# out the lowest free index again, and the driver can return the same VkImage pointer for a new image of
# the same size: inFAMOUS 2's 512x288 soft-particle colour target (0xB9E000) took over the slot and
# image of the 512x288 particle-depth copy (0xF770000), so the depth copy and the particles wrote one
# image and the particles' scene-depth test read their own colour (BC-250 capture work/occ1, 2026-11-03:
# unit 0 of the particle program == the particle target, byte for byte) -> the smoke/fire cut into
# blocks. Now releasing any object clears the entries that name it. PS3_VK_DZ_INVALIDATE=0: old.
edit("libs/video/rsx_vulkan_backend.c",
     '''static void vk_eng_release(void* user, u32 handle)
{
    (void)user;
    if (!handle || handle >= VK_ENG_MAX_OBJ || s_eobj[handle].kind == VK_ENG_FREE) return;
''',
     '''static void vk_dz_forget(u32 handle);   /* vk dz invalidate */
static void vk_eng_release(void* user, u32 handle)
{
    (void)user;
    if (!handle || handle >= VK_ENG_MAX_OBJ || s_eobj[handle].kind == VK_ENG_FREE) return;
    vk_dz_forget(handle);
''',
     "vk dz invalidate release")
edit("libs/video/rsx_vulkan_backend.c",
     '''static int vk_dz_ours(int i)
{''',
     '''static void vk_dz_forget(u32 handle)   /* vk dz invalidate */
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3_VK_DZ_INVALIDATE"); on = !(e && *e == '0'); }
    if (!on) return;
    for (int i = 0; i < 32; i++)
        if (s_dz_cache[i].rt == handle || s_dz_cache[i].depth == handle) {
            static unsigned n;
            if (n++ < 8) VK_LOG("depth->RGBA8 cache: entry %d dropped (object %u released)\\n", i, handle);
            memset(&s_dz_cache[i], 0, sizeof s_dz_cache[i]);
        }
}
static int vk_dz_ours(int i)
{''',
     "vk dz invalidate forget")
