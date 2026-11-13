# vk nodraw: PS3RECOMP_VK_NODRAW=1 records every engine draw's state but not the draw itself (PC measuring aid)
# The PC test runs on lavapipe (software Vulkan), which makes PC fps a measure of the CPU rasterizer,
# not of the game's own CPU path (PPU code, SPU jobs, RSX command processing) that limits the console.
# With this set the picture is empty but everything up to the GPU still runs, so a PC run measures
# what the PS5 build has to do per frame. Off unless the variable is set.
VKF = "libs/video/rsx_vulkan_backend.c"
edit(VKF,
     '''    if (indices && index_count) {
        pvkCmdBindIndexBuffer(s_vk.cmd, ibuf, ioff, VK_INDEX_TYPE_UINT32);
        pvkCmdDrawIndexed(s_vk.cmd, index_count, 1, 0, 0, 0);
    } else {
        pvkCmdDraw(s_vk.cmd, vertex_count, 1, 0, 0);
    }''',
     '''    static int s_nodraw = -1;
    if (s_nodraw < 0) { const char* e = getenv("PS3RECOMP_VK_NODRAW"); s_nodraw = e && e[0] == '1'; }
    if (s_nodraw) {
    } else if (indices && index_count) {
        pvkCmdBindIndexBuffer(s_vk.cmd, ibuf, ioff, VK_INDEX_TYPE_UINT32);
        pvkCmdDrawIndexed(s_vk.cmd, index_count, 1, 0, 0, 0);
    } else {
        pvkCmdDraw(s_vk.cmd, vertex_count, 1, 0, 0);
    }''',
     "vk nodraw: skip")
