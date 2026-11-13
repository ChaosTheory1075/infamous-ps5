
# depth->RGBA8 targets: an entry counts as ours only while its slot still holds the VkImage we made.
# The engine releases a snapshot it stops using and the slot goes to the next object created (the
# Metal backend's note: a reused slot became a 3D LUT); checked by handle and kind alone, a reused
# slot could be one of the game's render targets -- drawn over, or released a second time.
edit("libs/video/rsx_vulkan_backend.c", "static struct { u32 depth, w, h, rt; } s_dz_cache[32];\n",
     "static struct { u32 depth, w, h, rt; VkImage img; } s_dz_cache[32];\n"
     "static int vk_dz_ours(int i)\n"
     "{\n"
     "    return s_dz_cache[i].rt && vk_eng_get(s_dz_cache[i].rt, VK_ENG_COLOR) &&\n"
     "           s_eobj[s_dz_cache[i].rt].im.img == s_dz_cache[i].img;\n"
     "}\n", "vk depth8 guard: struct")
edit("libs/video/rsx_vulkan_backend.c",
     "        if (s_dz_cache[i].rt && s_dz_cache[i].depth == depth && s_dz_cache[i].w == w && s_dz_cache[i].h == h\n"
     "            && vk_eng_get(s_dz_cache[i].rt, VK_ENG_COLOR)) { slot = i; break; }\n",
     "        if (vk_dz_ours(i) && s_dz_cache[i].depth == depth && s_dz_cache[i].w == w && s_dz_cache[i].h == h)\n"
     "            { slot = i; break; }\n", "vk depth8 guard: lookup")
edit("libs/video/rsx_vulkan_backend.c",
     "        if (s_dz_cache[slot].rt) vk_eng_release(user, s_dz_cache[slot].rt);\n"
     "        s_dz_cache[slot].rt = vk_eng_color_target_create(user, RSX_BE_FMT_R8G8B8A8, w, h, NULL, 0);\n"
     "        if (!s_dz_cache[slot].rt) { s_dz_cache[slot].depth = 0; return 0; }\n",
     "        if (vk_dz_ours(slot)) vk_eng_release(user, s_dz_cache[slot].rt);\n"
     "        s_dz_cache[slot].rt = vk_eng_color_target_create(user, RSX_BE_FMT_R8G8B8A8, w, h, NULL, 0);\n"
     "        if (!s_dz_cache[slot].rt) { s_dz_cache[slot].depth = 0; return 0; }\n"
     "        s_dz_cache[slot].img = s_eobj[s_dz_cache[slot].rt].im.img;\n", "vk depth8 guard: create")
