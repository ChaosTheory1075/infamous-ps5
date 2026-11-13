# fps counter: a frame-rate counter in the top-left corner of the PS5 picture (all three games), like the
# other recomps. Presented frames are counted over 0.5 s; the number is drawn with a 5x7 font, scaled to
# the output (8x at 4K), into the swapchain image right after the frame's blit (a buffer->image copy, no
# pipeline). Green >= 30, yellow >= 20, red below. PS3_FPS_COUNTER=0 turns it off.
import sys
C = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_vulkan_backend.c"
c = open(C).read()
if "fps counter" in c: print("already"); sys.exit(0)
def edit(s, old, new):
    if s.count(old) != 1: print("NOT FOUND/UNIQUE:", old[:80]); sys.exit(1)
    return s.replace(old, new)

c = edit(c, '''/* Blit the offscreen target into the next swapchain image and present it. */
static void vk_present_window(void)
{''', '''/* fps counter: presented frames per 0.5 s, drawn top-left into the swapchain image. */
static const unsigned char s_fps_font[13][7] = {   /* 0-9, 'F', 'P', 'S'; 5 bits a row, MSB left */
    {14,17,19,21,25,17,14},{4,12,4,4,4,4,14},{14,17,1,2,4,8,31},{31,2,4,2,1,17,14},{2,6,10,18,31,2,2},
    {31,16,30,1,1,17,14},{6,8,16,30,17,17,14},{31,1,2,4,8,8,8},{14,17,17,14,17,17,14},{14,17,17,15,1,2,12},
    {31,16,16,30,16,16,16},{30,17,17,30,16,16,16},{15,16,16,14,1,1,30} };
static void vk_fps_counter(VkImage img)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3_FPS_COUNTER"); on = !(e && *e == '0'); }
    if (!on || (s_sc_fmt != VK_FORMAT_B8G8R8A8_UNORM && s_sc_fmt != VK_FORMAT_B8G8R8A8_SRGB &&
                s_sc_fmt != VK_FORMAT_R8G8B8A8_UNORM && s_sc_fmt != VK_FORMAT_R8G8B8A8_SRGB)) return;
    static uint64_t t0; static u32 n; static int fps = -1;
    const uint64_t t = ps3_ft_now();   /* ns */
    n++;
    if (!t0) t0 = t;
    else if (t - t0 >= 500000000ull) { fps = (int)((n * 1000000000ull + (t - t0) / 2) / (t - t0)); n = 0; t0 = t; }
    if (fps < 0) return;
    int g[8], ng = 0, v = fps > 999 ? 999 : fps;
    char d[4]; const int nd = snprintf(d, sizeof d, "%d", v);
    for (int i = 0; i < nd; i++) g[ng++] = d[i] - '0';
    g[ng++] = -1; g[ng++] = 10; g[ng++] = 11; g[ng++] = 12;   /* space, F, P, S */
    u32 sc = s_vk.sc_extent.height / 270u; if (sc < 2) sc = 2;   /* 8x at 2160 lines */
    const u32 pad = sc, w = (u32)ng * 6u * sc + pad, h = 9u * sc;
    const u32 x0 = s_vk.sc_extent.height / 54u, y0 = x0;
    if (x0 + w > s_vk.sc_extent.width || y0 + h > s_vk.sc_extent.height) return;
    vk_buffer own; VkBuffer sb; VkDeviceSize so;
    u8* p = (u8*)vk_stage_alloc((VkDeviceSize)w * h * 4u, &own, &sb, &so);
    if (!p) return;
    if (own.buf) { vk_destroy_buffer(&own); return; }   /* only from the frame's ring (freed with the frame) */
    const int bgr = s_sc_fmt == VK_FORMAT_B8G8R8A8_UNORM || s_sc_fmt == VK_FORMAT_B8G8R8A8_SRGB;
    u8 fg[4] = { 255, 80, 70, 255 };                      /* RGBA: red */
    if (fps >= 30) { fg[0] = 120; fg[1] = 255; fg[2] = 120; } else if (fps >= 20) { fg[0] = 255; fg[1] = 225; fg[2] = 90; }
    if (bgr) { const u8 r = fg[0]; fg[0] = fg[2]; fg[2] = r; }
    for (u32 y = 0; y < h; y++)
        for (u32 x = 0; x < w; x++) {
            u8* q = p + ((size_t)y * w + x) * 4u;
            q[0] = q[1] = q[2] = 0; q[3] = 255;
            if (x < pad || y < sc || y >= 8u * sc) continue;
            const u32 cx = (x - pad) / sc, gi = cx / 6u, col = cx % 6u, row = y / sc - 1u;
            if (gi >= (u32)ng || col >= 5u || g[gi] < 0) continue;
            if (s_fps_font[g[gi]][row] & (16u >> col)) memcpy(q, fg, 4);
        }
    VkBufferImageCopy rg = { .bufferOffset = so, .imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 },
                             .imageOffset = { (int32_t)x0, (int32_t)y0, 0 }, .imageExtent = { w, h, 1 } };
    VkMemoryBarrier mb = { .sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
                           .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT };
    pvkCmdPipelineBarrier(s_vk.cmd, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 1, &mb, 0, NULL, 0, NULL);
    pvkCmdCopyBufferToImage(s_vk.cmd, sb, img, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &rg);
}

/* Blit the offscreen target into the next swapchain image and present it. */
static void vk_present_window(void)
{''')

c = edit(c, '''                    s_vk.sc_images[idx], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                    1, &blit, VK_FILTER_LINEAR);
    b.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;''', '''                    s_vk.sc_images[idx], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                    1, &blit, VK_FILTER_LINEAR);
    vk_fps_counter(s_vk.sc_images[idx]);   /* fps counter */
    b.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;''')

c = edit(c, '''    s_vk.sc_extent = ext;
    s_vk.sc_count = n;''', '''    s_vk.sc_extent = ext;
    s_vk.sc_count = n;
    s_sc_fmt = fmt.format;   /* fps counter */''')
c = edit(c, '''static vk_buffer        s_ring;                 /* per-frame vertices, indices, constants */''',
'''static VkFormat s_sc_fmt;                       /* fps counter: the swapchain's format */
static vk_buffer        s_ring;                 /* per-frame vertices, indices, constants */''')
open(C, "w").write(c); print("patched")
