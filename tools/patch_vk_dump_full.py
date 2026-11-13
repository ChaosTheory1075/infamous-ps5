
# vk dump full: PS3RECOMP_VK_DUMP_FULL=1 writes the periodic frame dumps at full size (default: half, point-sampled)
# The half-size dumps (every 2nd pixel of every 2nd row) hide the stair steps and edges a visual
# comparison against the real PS3 needs (inFAMOUS 2 effects, 2026-11-03).
edit("libs/video/rsx_vulkan_backend.c",
     '''        const u32 w = s_vk.width / 2, h = s_vk.height / 2;
        unsigned char* buf = (unsigned char*)malloc((size_t)w * h * 3 + 32);''',
     '''        static int full = -1;   /* vk dump full */
        if (full < 0) { const char* e = getenv("PS3RECOMP_VK_DUMP_FULL"); full = e && *e == '1'; }
        const u32 sc = full ? 1u : 2u;
        const u32 w = s_vk.width / sc, h = s_vk.height / sc;
        unsigned char* buf = (unsigned char*)malloc((size_t)w * h * 3 + 32);''',
     "vk dump full")
edit("libs/video/rsx_vulkan_backend.c",
     '''                const unsigned char* s = rgba + ((size_t)(y * 2) * s_vk.width + x * 2) * 4;''',
     '''                const unsigned char* s = rgba + ((size_t)(y * sc) * s_vk.width + x * sc) * 4;   /* vk dump full */''',
     "vk dump full 2")
