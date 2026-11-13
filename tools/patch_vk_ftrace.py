
# PS3_FTRACE on the Vulkan backend: every CPU wait for the GPU (vk_submit_and_wait's fence wait) as
# a GPU_WAIT span -- a = 0 a forced flush (the CPU is about to read what the GPU wrote), 1 an
# ordinary submit; b = the low 32 bits of the caller's address, to name the flush site. Only the
# Metal backend had GPU spans, so a console trace showed the RSX thread's "drain" and nothing of
# the GPU round trips inside it.
edit("libs/video/rsx_vulkan_backend.c", '#include "rsx_draw_engine.h"\n',
     '#include "rsx_draw_engine.h"\n#include "../../include/ps3emu/ps3_ftrace.h"   /* PS3_FTRACE: GPU waits */\n',
     "vk ftrace: include")
edit("libs/video/rsx_vulkan_backend.c",
     '    VK_CHECK(pvkQueueSubmit(s_vk.queue, 1, &si, s_vk.fence), "vkQueueSubmit");\n'
     '    VK_CHECK(pvkWaitForFences(s_vk.device, 1, &s_vk.fence, VK_TRUE, UINT64_MAX), "vkWaitForFences");\n'
     '    vk_batch_after_flush();\n',
     '    VK_CHECK(pvkQueueSubmit(s_vk.queue, 1, &si, s_vk.fence), "vkQueueSubmit");\n'
     '    const uint64_t ft0 = PS3_FT_ON() ? ps3_ft_now() : 0;\n'
     '    VK_CHECK(pvkWaitForFences(s_vk.device, 1, &s_vk.fence, VK_TRUE, UINT64_MAX), "vkWaitForFences");\n'
     '    if (ft0) ps3_ft_span(PS3_FT_GPU_WAIT, 0, s_force ? 0u : 1u,\n'
     '                         (uint32_t)(uintptr_t)__builtin_return_address(0), ft0, ps3_ft_now());\n'
     '    vk_batch_after_flush();\n',
     "vk ftrace: gpu wait")
