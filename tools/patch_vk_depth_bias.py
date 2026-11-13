# vk depth bias: the Vulkan engine backend applies the guest's polygon offset (POLYGON_OFFSET_FILL / SCALE /
# BIAS, rsx_draw_engine.c eng_apply_depth_bias -> set_depth_bias). Only the Metal backend implemented the
# hook, so on Linux and the PS5 every shadow map was drawn with no offset: shadow acne -- the swirling
# dot grids on shadowed walls in inFAMOUS 1 (2026-11-05, console shot 112649 vs the real PS3). Engine
# pipelines get depthBiasEnable + VK_DYNAMIC_STATE_DEPTH_BIAS; each draw sets (constant, slope), re-set on
# every pipeline change (a pipeline bind can reset dynamic state). The engine's depth targets are
# D32_SFLOAT, whose constant unit is 2^(e-23): the D24 unit for depths in [0.5, 1), as Metal does.
# On by default (PS3RECOMP_VK_DEPTH_BIAS=0 = old). inFAMOUS 1 draws its shadow maps with polygon offset off (no change there); inFAMOUS 2 / FoB draw theirs with slope 1, bias 2000 (rsx_draw_engine.c notes).
import sys
F = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/video/rsx_vulkan_backend.c"
s = open(F).read()
if "vk depth bias" in s: print("already"); sys.exit(0)
def edit(old, new, n=1):
    global s
    if s.count(old) != n: print("NOT FOUND/UNIQUE (%d):" % s.count(old), old[:80]); sys.exit(1)
    s = s.replace(old, new)
edit('''    u32 sref;
    VkDescriptorSet dset; uint32_t dyn[2];''',
     '''    u32 sref;
    float zbias[2];   /* vk depth bias */
    VkDescriptorSet dset; uint32_t dyn[2];''')
edit('''    X(vkCmdSetStencilReference) X(vkCmdBindIndexBuffer)''',
     '''    X(vkCmdSetStencilReference) X(vkCmdSetDepthBias) X(vkCmdBindIndexBuffer)''')
edit('''    u32          stencil_ref;
    vk_buffer    indices;''',
     '''    u32          stencil_ref;
    float        zbias[2];   /* vk depth bias: constant (D24 units), slope */
    vk_buffer    indices;''')
edit('''static void vk_eng_set_stencil_ref(void* user, u32 ref) { (void)user; s_e2.stencil_ref = ref; }''',
     '''static void vk_eng_set_stencil_ref(void* user, u32 ref) { (void)user; s_e2.stencil_ref = ref; }
static void vk_eng_set_depth_bias(void* user, float constant, float slope)
{ (void)user; s_e2.zbias[0] = constant; s_e2.zbias[1] = slope; }''')
edit('''        .frontFace = (rs->front_face == 0x0901u) ? VK_FRONT_FACE_COUNTER_CLOCKWISE
                                                 : VK_FRONT_FACE_CLOCKWISE,
        .lineWidth = 1.0f };
    VkPipelineMultisampleStateCreateInfo ms = {''',
     '''        .frontFace = (rs->front_face == 0x0901u) ? VK_FRONT_FACE_COUNTER_CLOCKWISE
                                                 : VK_FRONT_FACE_CLOCKWISE,
        .depthBiasEnable = vk_depth_bias_on() ? VK_TRUE : VK_FALSE,   /* vk depth bias */
        .lineWidth = 1.0f };
    VkPipelineMultisampleStateCreateInfo ms = {''')
edit('''    VkDynamicState dyn[3] = { VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR,
                              VK_DYNAMIC_STATE_STENCIL_REFERENCE };
    VkPipelineDynamicStateCreateInfo dy = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO,
        .dynamicStateCount = 3, .pDynamicStates = dyn };''',
     '''    VkDynamicState dyn[4] = { VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR,
                              VK_DYNAMIC_STATE_STENCIL_REFERENCE, VK_DYNAMIC_STATE_DEPTH_BIAS };
    VkPipelineDynamicStateCreateInfo dy = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO,
        .dynamicStateCount = vk_depth_bias_on() ? 4u : 3u, .pDynamicStates = dyn };''')
edit('''    if (!dd || s_dd.sref != sref) pvkCmdSetStencilReference(s_vk.cmd, VK_STENCIL_FACE_FRONT_AND_BACK, sref);''',
     '''    if (!dd || s_dd.sref != sref) pvkCmdSetStencilReference(s_vk.cmd, VK_STENCIL_FACE_FRONT_AND_BACK, sref);
    if (vk_depth_bias_on() && (!dd || s_dd.pipe != pipe || memcmp(s_dd.zbias, s_e2.zbias, sizeof s_dd.zbias))) {
        pvkCmdSetDepthBias(s_vk.cmd, s_e2.zbias[0], 0.0f, s_e2.zbias[1]);   /* vk depth bias */
        memcpy(s_dd.zbias, s_e2.zbias, sizeof s_dd.zbias); }''')
edit('''    .set_stencil_ref      = vk_eng_set_stencil_ref,''',
     '''    .set_stencil_ref      = vk_eng_set_stencil_ref,
    .set_depth_bias       = vk_eng_set_depth_bias,   /* vk depth bias */''')
edit('''static void vk_dd_reset(void) { s_dd.valid = 0; s_dd.ib = VK_NULL_HANDLE; }''',
     '''static void vk_dd_reset(void) { s_dd.valid = 0; s_dd.ib = VK_NULL_HANDLE; }
static int vk_depth_bias_on(void)   /* vk depth bias */
{ static int on = -1; if (on < 0) { const char* e = getenv("PS3RECOMP_VK_DEPTH_BIAS"); on = !(e && *e == '0'); } return on; }''')
open(F, "w").write(s); print("patched")
