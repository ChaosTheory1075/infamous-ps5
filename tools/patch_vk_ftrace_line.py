
# PS3_FTRACE GPU waits name the SOURCE LINE that forced them (b = __LINE__ of the
# vk_submit_and_wait() / vk_flush() call in rsx_vulkan_backend.c): the caller's address named only
# vk_flush, the small helper most forced flushes come through.
edit("libs/video/rsx_vulkan_backend.c", "static int vk_submit_and_wait(void)\n{\n    if (!s_rec) return 0;\n",
     "static int vk_submit_and_wait_at(int line)\n{\n    if (!s_rec) return 0;\n", "vk ftrace line: def")
edit("libs/video/rsx_vulkan_backend.c",
     "                         (uint32_t)(uintptr_t)__builtin_return_address(0), ft0, ps3_ft_now());\n",
     "                         (uint32_t)line, ft0, ps3_ft_now());\n", "vk ftrace line: span")
edit("libs/video/rsx_vulkan_backend.c",
     "static int vk_flush(void)\n{\n    s_force = 1;\n    const int r = vk_submit_and_wait();\n    s_force = 0;\n    return r;\n}\n",
     "#define vk_submit_and_wait() vk_submit_and_wait_at(__LINE__)\n"
     "static int vk_flush_at(int line)\n{\n    s_force = 1;\n    const int r = vk_submit_and_wait_at(line);\n    s_force = 0;\n    return r;\n}\n"
     "#define vk_flush() vk_flush_at(__LINE__)\n", "vk ftrace line: flush")
