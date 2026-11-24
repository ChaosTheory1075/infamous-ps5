/* vk fg guard: frame generation's ghost guards (shaders: fgguard/diff.comp, state.comp, guard.comp). A generated
 * frame doubles (two views in one picture) when the two real frames are far apart: a low real frame rate, a fast
 * camera swing, a cut. Then the real frame is held instead -- showing a real frame is never wrong.
 *  fg guard (a) interval: no generated frame while the real frame interval is above PS3_FG_MAX_INTERVAL_MS
 *    (default 45 ms = below ~22 real fps; 0 = no interval guard). Hysteresis: back on after 30 presents in a row
 *    at or under 90% of the limit; a lone hitch only holds its own pairs. CPU, one clock read a present; a held
 *    pair is not generated and no second swapchain image is acquired.
 *  fg guard (b) difference: the GPU compares the two real frames as box-downsampled luma (64x64 px cells, about
 *    20x12 at 720p, from every 4th pixel): sum |prev - next| / sum max(prev, next). Above PS3_FG_MAX_DIFF
 *    (default 0.25; 0 = no difference guard) the generated frame becomes the next real frame, until the
 *    difference has been below 75% of it for 4 pairs. Decided in the frame's own command buffer (no readback, no
 *    frame of delay: a cut never shows one doubled frame first); both methods (flow + mvwarp, neural).
 *    Calibration (fg notes on the PS3 footage, 30 fps pairs): play 0.10-0.15, p90 0.20-0.22,
 *    fast swings and cuts 0.30-0.60; pairs two frames apart (15 fps): p50 0.17-0.20, p90 0.31-0.35.
 *  PS3_FG_GUARD=0: both off (the behaviour before the guards). "fg guard:" log line every 600 presents.
 * Before 2026-11-11 the guard was an absolute mean luma difference (0.10: never reached in a night scene) and ran
 * for the neural method only. Included by rsx_vulkan_backend.c after vk_fsr.inc. */
#include "fgguard/diff_spv.h"
#include "fgguard/guard_spv.h"
#include "fgguard/state_spv.h"

typedef struct { int32_t w, h; float hi, lo; int32_t hold; } vk_fgg_pc;
typedef struct { uint32_t sum, lum, count, state, hold, skipped, rel_max, rel_sum; } vk_fgg_buf;   /* the shaders' buffer B */
static struct {
    int on, failed; float hi, lo;
    VkDescriptorSetLayout dsl; VkPipelineLayout pl; VkDescriptorPool dp; VkSampler samp;
    VkPipeline diff, guard, state;
    VkDescriptorSet ds[2];
    vk_buffer buf;
    uint32_t last_count, last_skipped, last_rel_sum;
    /* fg guard (a): the real frame interval */
    uint64_t max_ns, lo_ns, last_ns, prev_d, ema_ns; int held; uint32_t calm, slow_hist;
    /* fg guard log + the counter: presents, generated-frame presents, pairs held by the interval, held pairs seen */
    uint32_t n_present, n_mid, n_interval, seen_skipped, repeats; uint64_t d_sum; uint32_t d_n;
} s_fgg = { .on = -1 };
#define VK_FGG_RESUME 30u        /* presents in a row at or under lo_ns before the interval guard lets go */
#define VK_FGG_DIFF_HOLD 3       /* pairs below lo, after the last one above hi, that are still held (+ 1) */
#define VK_FGG_LOG_EVERY 600u

static void vk_fgg_env(void)
{
    if (s_fgg.on >= 0) return;
    const char* e = getenv("PS3_FG_GUARD"); s_fgg.on = (e && *e == '1');   /* default OFF since 2026-11-11 (t31: pink/purple blinking with the flow method; DONTFLIP) */
    e = getenv("PS3_FG_MAX_DIFF"); s_fgg.hi = e && *e ? (float)atof(e) : 0.25f;
    if (!(s_fgg.hi > 0.0f)) s_fgg.hi = 0.0f;
    s_fgg.lo = s_fgg.hi * 0.75f;
    e = getenv("PS3_FG_MAX_INTERVAL_MS");
    double ms = e && *e ? atof(e) : 62.0;   /* 62 ms = below ~16 real fps (the ghost the user's footage shows was at 16 fps); 45 would switch generation on and off all through inFAMOUS 1's 19-24 fps heavy scenes */ if (!(ms > 0.0)) ms = 0.0; if (ms > 1000.0) ms = 1000.0;
    s_fgg.max_ns = (uint64_t)(ms * 1e6); s_fgg.lo_ns = s_fgg.max_ns * 9u / 10u;
    if (!s_fgg.on) VK_LOG("fg guard: off (PS3_FG_GUARD=0)\n");
    else VK_LOG("fg guard: on (real frame held above a %.1f ms frame interval, back on under %.1f ms; above a frame difference of %.3f, back on under %.3f)\n",
                ms, ms * 0.9, (double)s_fgg.hi, (double)s_fgg.lo);
}

/* fg guard (a). Once a real present with frame generation on, before the generated frame's image is acquired.
 * Returns 1 when the pair that ends at this frame gets no generated frame. */
static int vk_fgg_interval_hold(void)
{
    vk_fgg_env();
    const uint64_t now = ps3_ft_now();
    const uint64_t raw = s_fgg.last_ns ? now - s_fgg.last_ns : 0;
    s_fgg.last_ns = now;
    if (!raw) return 0;
    if (raw > 250000000ull) { s_fgg.prev_d = 0; return s_fgg.on && s_fgg.max_ns; }   /* a pause (movie, load): start over, not this pair */
    s_fgg.d_sum += raw; s_fgg.d_n++;
    if (!s_fgg.on || !s_fgg.max_ns) return 0;
    const uint64_t d2 = s_fgg.prev_d ? (raw + s_fgg.prev_d) / 2u : raw;   /* two intervals: one present's jitter is not a slow frame */
    s_fgg.prev_d = raw;
    const uint64_t dc = raw > s_fgg.max_ns * 2u ? s_fgg.max_ns * 2u : raw;   /* one hitch does not carry the average over */
    s_fgg.ema_ns = s_fgg.ema_ns ? (s_fgg.ema_ns * 7u + dc) / 8u : dc;
    const int slow = d2 > s_fgg.max_ns;
    s_fgg.slow_hist = (s_fgg.slow_hist << 1) | (uint32_t)slow;
    if (!s_fgg.held) {   /* held: the average is over the limit, or 3 slow pairs in the last 16 */
        if (s_fgg.ema_ns > s_fgg.max_ns || __builtin_popcount(s_fgg.slow_hist & 0xFFFFu) >= 3) { s_fgg.held = 1; s_fgg.calm = 0; }
    } else if (d2 <= s_fgg.lo_ns) {
        if (++s_fgg.calm >= VK_FGG_RESUME) { s_fgg.held = 0; s_fgg.slow_hist = 0; }
    } else s_fgg.calm = 0;
    return s_fgg.held || slow;
}

static VkPipeline vk_fgg_pipe(const uint32_t* code, size_t bytes)
{
    VkShaderModuleCreateInfo mi = { .sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = bytes, .pCode = code };
    VkShaderModule m = VK_NULL_HANDLE;
    if (pvkCreateShaderModule(s_vk.device, &mi, NULL, &m) != VK_SUCCESS) return VK_NULL_HANDLE;
    VkComputePipelineCreateInfo ci = { .sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
        .stage = { .sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = m, .pName = "main" },
        .layout = s_fgg.pl };
    VkPipeline p = VK_NULL_HANDLE;
    if (pvkCreateComputePipelines(s_vk.device, VK_NULL_HANDLE, 1, &ci, NULL, &p) != VK_SUCCESS) p = VK_NULL_HANDLE;
    pvkDestroyShaderModule(s_vk.device, m, NULL);
    return p;
}

/* in[0], in[1]: the two real-frame images (SHADER_READ_ONLY_OPTIMAL when used), out: the generated frame (GENERAL) */
static int vk_fgg_init(VkImageView in0, VkImageView in1, VkImageView out)
{
    VkDescriptorSetLayoutBinding b[4] = {
        { 0, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL },
        { 1, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL },
        { 2, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL },
        { 3, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL } };
    VkDescriptorSetLayoutCreateInfo di = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 4, .pBindings = b };
    if (pvkCreateDescriptorSetLayout(s_vk.device, &di, NULL, &s_fgg.dsl) != VK_SUCCESS) return -1;
    VkPushConstantRange pr = { VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(vk_fgg_pc) };
    VkPipelineLayoutCreateInfo pli = { .sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &s_fgg.dsl,
                                       .pushConstantRangeCount = 1, .pPushConstantRanges = &pr };
    if (pvkCreatePipelineLayout(s_vk.device, &pli, NULL, &s_fgg.pl) != VK_SUCCESS) return -1;
    VkDescriptorPoolSize ps[3] = { { VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 4 }, { VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 2 },
                                   { VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 2 } };
    VkDescriptorPoolCreateInfo pci = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, .maxSets = 2, .poolSizeCount = 3, .pPoolSizes = ps };
    if (pvkCreateDescriptorPool(s_vk.device, &pci, NULL, &s_fgg.dp) != VK_SUCCESS) return -1;
    VkDescriptorSetLayout l2[2] = { s_fgg.dsl, s_fgg.dsl };
    VkDescriptorSetAllocateInfo ai = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, .descriptorPool = s_fgg.dp, .descriptorSetCount = 2, .pSetLayouts = l2 };
    if (pvkAllocateDescriptorSets(s_vk.device, &ai, s_fgg.ds) != VK_SUCCESS) return -1;
    VkSamplerCreateInfo sci = { .sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO, .magFilter = VK_FILTER_NEAREST, .minFilter = VK_FILTER_NEAREST,
        .addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE };
    if (pvkCreateSampler(s_vk.device, &sci, NULL, &s_fgg.samp) != VK_SUCCESS) return -1;
    if (vk_create_host_buffer(&s_fgg.buf, sizeof(vk_fgg_buf), VK_BUFFER_USAGE_STORAGE_BUFFER_BIT) || !s_fgg.buf.coherent || !s_fgg.buf.ptr) return -1;
    memset(s_fgg.buf.ptr, 0, sizeof(vk_fgg_buf));
    s_fgg.diff = vk_fgg_pipe(s_fgg_diff_spv, sizeof s_fgg_diff_spv);
    s_fgg.guard = vk_fgg_pipe(s_fgg_guard_spv, sizeof s_fgg_guard_spv);
    s_fgg.state = vk_fgg_pipe(s_fgg_state_spv, sizeof s_fgg_state_spv);
    if (!s_fgg.diff || !s_fgg.guard || !s_fgg.state) return -1;
    for (int k = 0; k < 2; k++) {   /* set k: next = in[k], prev = in[k ^ 1] */
        VkDescriptorImageInfo pi = { .sampler = s_fgg.samp, .imageView = k ? in0 : in1, .imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL };
        VkDescriptorImageInfo ni = { .sampler = s_fgg.samp, .imageView = k ? in1 : in0, .imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL };
        VkDescriptorBufferInfo bi = { s_fgg.buf.buf, 0, sizeof(vk_fgg_buf) };
        VkDescriptorImageInfo oi = { .imageView = out, .imageLayout = VK_IMAGE_LAYOUT_GENERAL };
        VkWriteDescriptorSet wr[4] = {
            { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_fgg.ds[k], .dstBinding = 0, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .pImageInfo = &pi },
            { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_fgg.ds[k], .dstBinding = 1, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, .pImageInfo = &ni },
            { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_fgg.ds[k], .dstBinding = 2, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &bi },
            { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_fgg.ds[k], .dstBinding = 3, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .pImageInfo = &oi } };
        pvkUpdateDescriptorSets(s_vk.device, 4, wr, 0, NULL);
    }
    return 0;
}

/* fg guard (b). After the generator wrote `out` (GENERAL, compute writes) for the pair (in[cur ^ 1], in[cur]):
 * difference -> decision -> the next real frame over `out` when held. Cost at 1280x720: 57,600 invocations with
 * two texel fetches each, one invocation, and 14,400 work groups that read one word and return (a full-frame
 * copy only when held). */
static void vk_fgg_record(u32 cur, VkImageView in0, VkImageView in1, VkImageView out)
{
    vk_fgg_env();
    if (!s_fgg.on || s_fgg.failed || !(s_fgg.hi > 0.0f)) return;
    if (!s_fgg.diff && vk_fgg_init(in0, in1, out)) { s_fgg.failed = 1; VK_LOG("fg guard: no difference guard (setup failed)\n"); return; }
    VkMemoryBarrier mb = { .sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT | VK_ACCESS_SHADER_READ_BIT,
                           .dstAccessMask = VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT };
    const vk_fgg_pc pc = { (int32_t)s_vk.width, (int32_t)s_vk.height, s_fgg.hi, s_fgg.lo, VK_FGG_DIFF_HOLD };
    const VkDescriptorSet ds = s_fgg.ds[cur & 1u];
    pvkCmdPipelineBarrier(s_vk.cmd, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &mb, 0, NULL, 0, NULL);
    pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_fgg.pl, 0, 1, &ds, 0, NULL);
    pvkCmdPushConstants(s_vk.cmd, s_fgg.pl, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, &pc);
    pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_fgg.diff);
    pvkCmdDispatch(s_vk.cmd, ((s_vk.width + 3) / 4 + 15) / 16, ((s_vk.height + 3) / 4 + 15) / 16, 1);
    pvkCmdPipelineBarrier(s_vk.cmd, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &mb, 0, NULL, 0, NULL);
    pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_fgg.state);   /* the decision first, then the copy */
    pvkCmdDispatch(s_vk.cmd, 1, 1, 1);
    pvkCmdPipelineBarrier(s_vk.cmd, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &mb, 0, NULL, 0, NULL);
    pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, s_fgg.guard);
    pvkCmdDispatch(s_vk.cmd, (s_vk.width + 7) / 8, (s_vk.height + 7) / 8, 1);
}

/* A generated-frame present: 1 when it stands for a pair the difference guard held (the same real frame twice,
 * not a new picture: the counter's "shown" rate leaves it out). The GPU's count is read a frame or two late. */
static int vk_fgg_repeat(void)
{
    s_fgg.n_mid++;
    if (!s_fgg.buf.ptr) return 0;
    const uint32_t sk = ((volatile vk_fgg_buf*)s_fgg.buf.ptr)->skipped;
    s_fgg.repeats += sk - s_fgg.seen_skipped; s_fgg.seen_skipped = sk;
    if (!s_fgg.repeats) return 0;
    s_fgg.repeats--;
    return 1;
}

/* Once a real present with frame generation on: the "fg guard:" line every VK_FGG_LOG_EVERY presents.
 * held_interval: vk_fgg_interval_hold() held this present's pair. (The GPU's counters are read while it may be
 * writing them: a window's numbers can be off by the frames in flight.) */
static void vk_fgg_count(int held_interval)
{
    s_fgg.n_present++; s_fgg.n_interval += held_interval ? 1u : 0u;
    if (s_fgg.n_present < VK_FGG_LOG_EVERY) return;
    uint32_t dc = 0, dk = 0, dm = 0, mx = 0;
    if (s_fgg.buf.ptr) {
        volatile vk_fgg_buf* b = (volatile vk_fgg_buf*)s_fgg.buf.ptr;
        const uint32_t c = b->count, sk = b->skipped, ms = b->rel_sum; mx = b->rel_max;
        dc = c - s_fgg.last_count; dk = sk - s_fgg.last_skipped; dm = ms - s_fgg.last_rel_sum;
        s_fgg.last_count = c; s_fgg.last_skipped = sk; s_fgg.last_rel_sum = ms; b->rel_max = 0;
    }
    if (dk > s_fgg.n_mid) dk = s_fgg.n_mid;
    const uint32_t shown = s_fgg.n_mid + s_fgg.n_interval;
    VK_LOG("fg guard: %u presents (%.1f ms a frame): %u generated, %u held by interval (limit %.1f ms, %s), "
           "%u held by diff (mean %.3f, max %.3f, limit %.3f), %u other%s\n",
           s_fgg.n_present, s_fgg.d_n ? (double)s_fgg.d_sum / 1e6 / (double)s_fgg.d_n : 0.0, s_fgg.n_mid - dk,
           s_fgg.n_interval, (double)s_fgg.max_ns / 1e6, s_fgg.held ? "holding" : "open",
           dk, dc ? (double)dm / 10000.0 / (double)dc : 0.0, (double)mx / 10000.0, (double)s_fgg.hi,
           s_fgg.n_present > shown ? s_fgg.n_present - shown : 0u, s_fgg.on ? "" : " (guard off)");
    s_fgg.n_present = s_fgg.n_mid = s_fgg.n_interval = 0; s_fgg.d_sum = 0; s_fgg.d_n = 0;
}
