# vk ubo shadow: the engine's shader constants are written into the host-visible uniform buffer
# (s_g.ubo: HOST_COHERENT memory, mapped uncached/write-combined on RADV) and then READ BACK from it
# for every draw (vk_batch_draw_begin copies them into the ring; the GPU light/SSAO passes save and
# restore them). CPU reads of uncached memory are very slow: BC-250 FoB bar scene, the RSX thread was
# ~96% busy, 63% of it in that memmove (perf, DWARF call graphs). Now a CPU copy (s_ubo_cpu) is kept
# next to it: writes go to both, every read comes from the CPU copy.
VKB = "libs/video/rsx_vulkan_backend.c"
edit(VKB, "static int vk_guest_init(void)\n",
     "static u8* s_ubo_cpu;   /* vk ubo shadow: CPU copy of s_g.ubo (reads of the mapping are uncached) */\nstatic int vk_guest_init(void)\n",
     "vk ubo shadow: decl")
edit(VKB,
     '''    s_g.on = 1;
    VK_LOG("guest programs: on (HLSL -> SPIR-V through glslang)\\n");''',
     '''    s_ubo_cpu = (u8*)calloc(1, (size_t)s_g.ubo.size);   /* vk ubo shadow */
    if (!s_ubo_cpu) { VK_LOG("guest programs: no memory for the constants copy\\n"); return -1; }
    s_g.on = 1;
    VK_LOG("guest programs: on (HLSL -> SPIR-V through glslang)\\n");''',
     "vk ubo shadow: alloc")
edit(VKB,
     '''static void vk_eng_bind_vs_constants(void* user, const void* data, u32 bytes)''',
     '''/* vk ubo shadow: writes go to the uniform buffer and its CPU copy; reads use the copy. */
static void vk_ubo_put(size_t off, const void* d, size_t n)
{
    memcpy(s_ubo_cpu + off, d, n);
    memcpy((u8*)s_g.ubo.ptr + off, d, n);
}
static void vk_eng_bind_vs_constants(void* user, const void* data, u32 bytes)''',
     "vk ubo shadow: put")
edit(VKB, '''    memcpy(s_g.ubo.ptr, data, bytes);
    s_e2.vs_bytes = bytes;''', '''    vk_ubo_put(0, data, bytes);
    s_e2.vs_bytes = bytes;''', "vk ubo shadow: vs")
edit(VKB, '''    memcpy((u8*)s_g.ubo.ptr + s_g.ps_off, data, bytes);
    s_e2.ps_bytes = bytes;''', '''    vk_ubo_put(s_g.ps_off, data, bytes);
    s_e2.ps_bytes = bytes;''', "vk ubo shadow: ps")
edit(VKB, '''    memcpy(vk_ring_alloc(vs_bytes, s_ubo_align, &vs_off), s_g.ubo.ptr, vs_bytes);
    memcpy(vk_ring_alloc(ps_bytes, s_ubo_align, &ps_off), (u8*)s_g.ubo.ptr + s_g.ps_off, ps_bytes);''',
     '''    memcpy(vk_ring_alloc(vs_bytes, s_ubo_align, &vs_off), s_ubo_cpu, vs_bytes);
    memcpy(vk_ring_alloc(ps_bytes, s_ubo_align, &ps_off), s_ubo_cpu + s_g.ps_off, ps_bytes);''',
     "vk ubo shadow: ring")
_s = (tk / VKB).read_text()
if "vk ubo shadow: save/restore" not in done:
    _s = _s.replace('''memcpy(vs_save, s_g.ubo.ptr, vsb);''', '''memcpy(vs_save, s_ubo_cpu, vsb);''')
    _s = _s.replace('''memcpy(ps_save, (u8*)s_g.ubo.ptr + s_g.ps_off, psb);''', '''memcpy(ps_save, s_ubo_cpu + s_g.ps_off, psb);''')
    _s = _s.replace('''memcpy(s_g.ubo.ptr, vs_save, vsb);''', '''vk_ubo_put(0, vs_save, vsb);''')
    _s = _s.replace('''memcpy((u8*)s_g.ubo.ptr + s_g.ps_off, ps_save, psb);''', '''vk_ubo_put(s_g.ps_off, ps_save, psb);''')
    (tk / VKB).write_text(_s)
    mark("vk ubo shadow: save/restore")
    print("patched", VKB, "- vk ubo shadow: save/restore")
