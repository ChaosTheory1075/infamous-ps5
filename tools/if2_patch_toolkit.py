"""Local changes to the inFamous 2 toolkit (Noah's ps3recomp fork + erikomis's patch), re-runnable.

usage: if2_patch_toolkit.py <toolkit dir>
"""
import sys
from pathlib import Path

tk = Path(sys.argv[1])


# Edits already applied to this toolkit, by tag: later edits may change text an earlier one
# inserted, so "is the new text there?" alone would re-apply it.
DONE = tk / ".if2_patches_applied"
done = set(DONE.read_text().split("\n")) if DONE.exists() else set()


def mark(tag):
    done.add(tag)
    DONE.write_text("\n".join(sorted(t for t in done if t)) + "\n")


def edit(rel, old, new, tag, optional=False):
    if tag in done:
        return
    p = tk / rel
    s = p.read_text()
    if new in s:
        mark(tag)
        return
    if old not in s:
        if optional:
            return
        sys.exit(f"{rel}: anchor for '{tag}' not found")
    p.write_text(s.replace(old, new, 1))
    mark(tag)
    print("patched", rel, "-", tag)


# Vulkan: robustBufferAccess. A guest draw whose vertex/index range runs past the buffer the engine
# uploaded crashed lavapipe's JIT (inFamous 2, Bink splash); with robustness an out-of-range read
# returns zeros, as on the RSX. RADV (PS5) supports it at no measurable cost.
edit("libs/video/rsx_vulkan_backend.c",
     "    want.textureCompressionBC = have.textureCompressionBC;\n",
     "    want.textureCompressionBC = have.textureCompressionBC;\n"
     "    want.robustBufferAccess = have.robustBufferAccess;\n",
     "robustBufferAccess")

# (The samplers stay one 16-element array: the decompilers declare `SamplerState rsx_samp[16] :
# register(s0)`. A first version of this edit split them per unit too; migrate it.)
PER_UNIT_LAYOUT = (
    "    VkDescriptorSetLayoutBinding b[3 + RSX_MAX_TEXTURES] = {\n"
    "        { RSX_SPIRV_VPCONST_BINDING, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1, both, NULL },\n"
    "        { RSX_SPIRV_PSCONST_BINDING, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1, both, NULL },\n"
    "        { RSX_SPIRV_SAMPLER_BINDING, VK_DESCRIPTOR_TYPE_SAMPLER, RSX_MAX_TEXTURES,\n"
    "          VK_SHADER_STAGE_FRAGMENT_BIT, NULL },\n"
    "    };\n"
    "    for (u32 u = 0; u < RSX_MAX_TEXTURES; u++)\n"
    "        b[3 + u] = (VkDescriptorSetLayoutBinding){ RSX_SPIRV_TEXTURE_BINDING + u,\n"
    "            VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, 1, VK_SHADER_STAGE_FRAGMENT_BIT, NULL };\n"
    "    VkDescriptorSetLayoutCreateInfo lci = {\n"
    "        .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,\n"
    "        .bindingCount = 3 + RSX_MAX_TEXTURES, .pBindings = b };\n")
edit("libs/video/rsx_vulkan_backend.c",
     "    VkDescriptorSetLayoutBinding b[2 + 2 * RSX_MAX_TEXTURES] = {\n"
     "        { RSX_SPIRV_VPCONST_BINDING, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1, both, NULL },\n"
     "        { RSX_SPIRV_PSCONST_BINDING, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1, both, NULL },\n"
     "    };\n"
     "    for (u32 u = 0; u < RSX_MAX_TEXTURES; u++) {\n"
     "        b[2 + u] = (VkDescriptorSetLayoutBinding){ RSX_SPIRV_TEXTURE_BINDING + u,\n"
     "            VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, 1, VK_SHADER_STAGE_FRAGMENT_BIT, NULL };\n"
     "        b[2 + RSX_MAX_TEXTURES + u] = (VkDescriptorSetLayoutBinding){ RSX_SPIRV_SAMPLER_BINDING + u,\n"
     "            VK_DESCRIPTOR_TYPE_SAMPLER, 1, VK_SHADER_STAGE_FRAGMENT_BIT, NULL };\n"
     "    }\n"
     "    VkDescriptorSetLayoutCreateInfo lci = {\n"
     "        .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,\n"
     "        .bindingCount = 2 + 2 * RSX_MAX_TEXTURES, .pBindings = b };\n",
     PER_UNIT_LAYOUT, "samplers back to one array", optional=True)

# Vulkan: one binding per texture unit. The decompilers declare `Texture2D rsx_texN : register(tN)`
# (and sN) per unit, which glslang maps to bindings 16+N / 48+N, but the layout declared bindings 16
# and 48 as 16-element arrays, so every unit above 0 used an undeclared binding (validation:
# VUID-VkGraphicsPipelineCreateInfo-layout-07988; lavapipe crashed in the shader). The per-draw
# writes of 16 descriptors starting at 16 / 48 roll over across the consecutive bindings unchanged.
edit("libs/video/rsx_vulkan_backend.c",
     "    VkDescriptorSetLayoutBinding b[4] = {\n"
     "        { RSX_SPIRV_VPCONST_BINDING, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1, both, NULL },\n"
     "        { RSX_SPIRV_PSCONST_BINDING, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1, both, NULL },\n"
     "        { RSX_SPIRV_TEXTURE_BINDING, VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, RSX_MAX_TEXTURES,\n"
     "          VK_SHADER_STAGE_FRAGMENT_BIT, NULL },\n"
     "        { RSX_SPIRV_SAMPLER_BINDING, VK_DESCRIPTOR_TYPE_SAMPLER, RSX_MAX_TEXTURES,\n"
     "          VK_SHADER_STAGE_FRAGMENT_BIT, NULL },\n"
     "    };\n"
     "    VkDescriptorSetLayoutCreateInfo lci = {\n"
     "        .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,\n"
     "        .bindingCount = 4, .pBindings = b };\n",
     PER_UNIT_LAYOUT,
     "per-unit texture bindings")

# ---------------------------------------------------------------------------------------------------
# Vulkan: cube maps on the draw-engine path. texture_create(faces == 6) used to report 0 and every
# cube unit sampled the 2D dummy (validation VUID-vkCmdDrawIndexed-viewType-07752: the shader's
# TextureCube got a 2D view). Now: 6-layer cube-compatible images with a CUBE view, uploads per
# face, barriers over every layer, and each pipeline records its pixel shader's TextureCube units so
# an unbound or mismatched one gets a 1x1 magenta dummy cube instead of the 2D dummy.
# ---------------------------------------------------------------------------------------------------
edit(VK0 := "libs/video/rsx_vulkan_backend.c",
     "        .image = img, .subresourceRange = { aspect, 0, VK_REMAINING_MIP_LEVELS, 0, 1 },\n",
     "        .image = img, .subresourceRange = { aspect, 0, VK_REMAINING_MIP_LEVELS, 0, VK_REMAINING_ARRAY_LAYERS },\n",
     "barriers over every layer")
edit(VK0,
     "typedef struct vk_eng_obj {\n    u8       kind;\n",
     "typedef struct vk_eng_obj {\n    u8       kind;\n    u8       cube;                   /* TEXTURE: 6 layers, CUBE view    */\n",
     "cube flag")
edit(VK0,
     "static int vk_eng_make_view(VkImage img, VkFormat fmt, u32 levels, VkComponentMapping map,\n"
     "                            VkImageView* out)\n",
     "static int vk_eng_make_view_layers(VkImage img, VkFormat fmt, u32 levels, VkComponentMapping map,\n"
     "                                   u32 layers, VkImageView* out)\n"
     "{\n"
     "    VkImageViewCreateInfo vci = {\n"
     "        .sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = img,\n"
     "        .viewType = layers == 6 ? VK_IMAGE_VIEW_TYPE_CUBE : VK_IMAGE_VIEW_TYPE_2D,\n"
     "        .format = fmt, .components = map,\n"
     "        .subresourceRange = { VK_IMAGE_ASPECT_COLOR_BIT, 0, levels ? levels : 1, 0, layers },\n"
     "    };\n"
     "    return pvkCreateImageView(s_vk.device, &vci, NULL, out) == VK_SUCCESS ? 0 : -1;\n"
     "}\n"
     "static int vk_eng_make_view(VkImage img, VkFormat fmt, u32 levels, VkComponentMapping map,\n"
     "                            VkImageView* out)\n",
     "layered views")
edit(VK0,
     "    if (faces == 6) {\n"
     "        static int warned_cube;\n"
     "        if (!warned_cube) { VK_LOG(\"engine: cube textures not supported yet\\n\"); warned_cube = 1; }\n"
     "        return 0;\n"
     "    }\n",
     "    const u32 layers = faces == 6 ? 6u : 1u;\n",
     "cube create: layers")
edit(VK0,
     "        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D,\n"
     "        .format = vf, .extent = { w, h, 1 }, .mipLevels = mips, .arrayLayers = 1,\n"
     "        .samples = VK_SAMPLE_COUNT_1_BIT, .tiling = VK_IMAGE_TILING_OPTIMAL,\n"
     "        .usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,\n",
     "        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D,\n"
     "        .flags = layers == 6 ? VK_IMAGE_CREATE_CUBE_COMPATIBLE_BIT : 0,\n"
     "        .format = vf, .extent = { w, h, 1 }, .mipLevels = mips, .arrayLayers = layers,\n"
     "        .samples = VK_SAMPLE_COUNT_1_BIT, .tiling = VK_IMAGE_TILING_OPTIMAL,\n"
     "        .usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,\n",
     "cube create: image")
edit(VK0,
     "        vk_eng_make_view(o->im.img, vf, mips, vk_remap(remap, rsx_fmt), &o->im.view))\n"
     "        goto fail;\n"
     "    o->kind = VK_ENG_TEXTURE; o->fmt = vf; o->w = w; o->h = h;\n",
     "        vk_eng_make_view_layers(o->im.img, vf, mips, vk_remap(remap, rsx_fmt), layers, &o->im.view))\n"
     "        goto fail;\n"
     "    o->kind = VK_ENG_TEXTURE; o->fmt = vf; o->w = w; o->h = h; o->cube = layers == 6;\n",
     "cube create: view")
edit(VK0,
     "    if (!o || !src || !row_bytes || !rows || face) return;\n",
     "    if (!o || !src || !row_bytes || !rows || face >= (o->cube ? 6u : 1u)) return;\n",
     "cube upload: faces")
edit(VK0,
     "    vk_eng_upload_rows(o->im.img, 0, mip, w, h, tight, rows, src, row_bytes);\n",
     "    vk_eng_upload_rows(o->im.img, face, mip, w, h, tight, rows, src, row_bytes);\n",
     "cube upload: layer")
edit(VK0,
     "    u32                 nslots, stride, rt_count;\n    VkPipeline          variant[VK_ENG_TOPOLOGIES];\n} vk_eng_pipe;\n",
     "    u32                 nslots, stride, rt_count;\n    u32                 cube_mask;    /* pixel shader's TextureCube units */\n"
     "    VkPipeline          variant[VK_ENG_TOPOLOGIES];\n} vk_eng_pipe;\n",
     "pipeline cube mask field")
edit(VK0,
     "    P->rs = *rs;\n    P->nslots = layout->count;\n",
     "    P->rs = *rs;\n"
     "    for (const char* c = ps_hlsl; (c = strstr(c, \"TextureCube rsx_tex\")) != NULL; c++) {\n"
     "        const unsigned u = (unsigned)strtoul(c + 19, NULL, 10);\n"
     "        if (u < RSX_MAX_TEXTURES) P->cube_mask |= 1u << u;\n"
     "    }\n"
     "    P->nslots = layout->count;\n",
     "pipeline cube mask")
edit(VK0,
     "static void vk_eng_write_descriptors(void)\n{\n",
     "/* A 1x1 magenta cube for TextureCube units with nothing (or a 2D texture) bound. */\n"
     "static VkImageView vk_eng_dummy_cube(void)\n"
     "{\n"
     "    static u32 hd;\n"
     "    if (hd && s_eobj[hd].kind == VK_ENG_TEXTURE && s_eobj[hd].cube) return s_eobj[hd].im.view;\n"
     "    hd = vk_eng_texture_create(NULL, RSX_BE_FMT_R8G8B8A8, 1, 1, 1, 6, 0, 0);\n"
     "    if (!hd) return s_vk.dummy.view;\n"
     "    vk_eng_obj* o = &s_eobj[hd];\n"
     "    const VkComponentMapping id = { VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY,\n"
     "                                    VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY };\n"
     "    pvkDestroyImageView(s_vk.device, o->im.view, NULL);\n"
     "    if (vk_eng_make_view_layers(o->im.img, o->fmt, 1, id, 6, &o->im.view)) { o->im.view = VK_NULL_HANDLE; return s_vk.dummy.view; }\n"
     "    static const u8 magenta[4] = { 0xFF, 0x00, 0xFF, 0xFF };\n"
     "    for (u32 f = 0; f < 6; f++) vk_eng_texture_upload(NULL, hd, f, 0, 1, 1, magenta, 4, 1);\n"
     "    return o->im.view;\n"
     "}\n"
     "\n"
     "static void vk_eng_write_descriptors(void)\n{\n"
     "    const u32 cube_mask = s_e2.pipeline ? s_epipe[s_e2.pipeline - 1].cube_mask : 0;\n",
     "dummy cube")
edit(VK0,
     "        VkImageView v = ((s_e2.tex_mask >> u) & 1u) ? vk_eng_sample_view(s_e2.tex[u]) : VK_NULL_HANDLE;\n"
     "        VkSampler smp = v ? vk_eng_sampler(&s_e2.samp[u]) : s_vk.sampler;\n"
     "        ii[u] = (VkDescriptorImageInfo){ VK_NULL_HANDLE, v ? v : s_vk.dummy.view, VK_IMAGE_LAYOUT_GENERAL };\n",
     "        const u32 want_cube = (cube_mask >> u) & 1u;\n"
     "        VkImageView v = ((s_e2.tex_mask >> u) & 1u) ? vk_eng_sample_view(s_e2.tex[u]) : VK_NULL_HANDLE;\n"
     "        if (v && (u32)s_eobj[s_e2.tex[u]].cube != want_cube) v = VK_NULL_HANDLE;\n"
     "        VkSampler smp = v ? vk_eng_sampler(&s_e2.samp[u]) : s_vk.sampler;\n"
     "        ii[u] = (VkDescriptorImageInfo){ VK_NULL_HANDLE,\n"
     "                                         v ? v : want_cube ? vk_eng_dummy_cube() : s_vk.dummy.view,\n"
     "                                         VK_IMAGE_LAYOUT_GENERAL };\n",
     "cube descriptors")

# ---------------------------------------------------------------------------------------------------
# Vulkan on the PS5 (__PROSPERO__): RADV is linked statically (libvulkan_radeon.ps5.a), so the entry
# point is its ICD vk_icdGetInstanceProcAddr instead of a dlopen'd loader, and the screen is a
# VK_KHR_display plane surface instead of an SDL window. Same approach as plume-ps5 (MIT).
# ---------------------------------------------------------------------------------------------------
VK = "libs/video/rsx_vulkan_backend.c"

edit(VK,
     "static int vk_load_library(void)\n{\n",
     "#if defined(__PROSPERO__)\n"
     "extern VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL\n"
     "    vk_icdGetInstanceProcAddr(VkInstance instance, const char* name) __attribute__((weak));\n"
     "extern int sceSystemServiceHideSplashScreen(void);\n"
     "\n"
     "/* RADV's ICD entry point, with the core-1.1 names it only exports as KHR aliases. */\n"
     "static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL ps5_vk_gipa(VkInstance inst, const char* name)\n"
     "{\n"
     "    if (!vk_icdGetInstanceProcAddr || !name) return NULL;\n"
     "    PFN_vkVoidFunction f = vk_icdGetInstanceProcAddr(inst, name);\n"
     "    if (f) return f;\n"
     "    if (!strcmp(name, \"vkGetPhysicalDeviceProperties2\"))\n"
     "        return vk_icdGetInstanceProcAddr(inst, \"vkGetPhysicalDeviceProperties2KHR\");\n"
     "    if (!strcmp(name, \"vkGetPhysicalDeviceFeatures2\"))\n"
     "        return vk_icdGetInstanceProcAddr(inst, \"vkGetPhysicalDeviceFeatures2KHR\");\n"
     "    return NULL;\n"
     "}\n"
     "\n"
     "/* The TV: the first display with a mode (3840x2160 when offered), the plane on it. */\n"
     "static int ps5_vk_display_surface(void)\n"
     "{\n"
     "    PFN_vkGetPhysicalDeviceDisplayPropertiesKHR gdp = (PFN_vkGetPhysicalDeviceDisplayPropertiesKHR)\n"
     "        pvkGetInstanceProcAddr(s_vk.instance, \"vkGetPhysicalDeviceDisplayPropertiesKHR\");\n"
     "    PFN_vkGetPhysicalDeviceDisplayPlanePropertiesKHR gpp = (PFN_vkGetPhysicalDeviceDisplayPlanePropertiesKHR)\n"
     "        pvkGetInstanceProcAddr(s_vk.instance, \"vkGetPhysicalDeviceDisplayPlanePropertiesKHR\");\n"
     "    PFN_vkGetDisplayModePropertiesKHR gmp = (PFN_vkGetDisplayModePropertiesKHR)\n"
     "        pvkGetInstanceProcAddr(s_vk.instance, \"vkGetDisplayModePropertiesKHR\");\n"
     "    PFN_vkCreateDisplayPlaneSurfaceKHR cps = (PFN_vkCreateDisplayPlaneSurfaceKHR)\n"
     "        pvkGetInstanceProcAddr(s_vk.instance, \"vkCreateDisplayPlaneSurfaceKHR\");\n"
     "    if (!gdp || !gpp || !gmp || !cps) { VK_LOG(\"VK_KHR_display is not available\\n\"); return -1; }\n"
     "    u32 n = 1;\n"
     "    VkPhysicalDevice phys = VK_NULL_HANDLE;\n"
     "    VkResult r = pvkEnumeratePhysicalDevices(s_vk.instance, &n, &phys);\n"
     "    if ((r != VK_SUCCESS && r != VK_INCOMPLETE) || !phys) { VK_LOG(\"no GPU\\n\"); return -1; }\n"
     "    VkDisplayPropertiesKHR disp[8];\n"
     "    VkDisplayPlanePropertiesKHR planes[16];\n"
     "    u32 nd = 8, np = 16;\n"
     "    if (gdp(phys, &nd, disp) < 0 || !nd) { VK_LOG(\"no display\\n\"); return -1; }\n"
     "    if (gpp(phys, &np, planes) < 0 || !np) { VK_LOG(\"no display plane\\n\"); return -1; }\n"
     "    VkDisplayKHR dsp = VK_NULL_HANDLE;\n"
     "    VkDisplayModeKHR mode = VK_NULL_HANDLE;\n"
     "    VkExtent2D ext = { 3840, 2160 };\n"
     "    for (u32 i = 0; i < nd && !mode; i++) {\n"
     "        VkDisplayModePropertiesKHR modes[32];\n"
     "        u32 nm = 32;\n"
     "        if (gmp(phys, disp[i].display, &nm, modes) < 0 || !nm) continue;\n"
     "        dsp = disp[i].display;\n"
     "        mode = modes[0].displayMode;\n"
     "        ext = modes[0].parameters.visibleRegion;\n"
     "        for (u32 m = 0; m < nm; m++)\n"
     "            if (modes[m].parameters.visibleRegion.width == 3840 &&\n"
     "                modes[m].parameters.visibleRegion.height == 2160) {\n"
     "                mode = modes[m].displayMode; ext = modes[m].parameters.visibleRegion; break;\n"
     "            }\n"
     "    }\n"
     "    if (!mode) { VK_LOG(\"no display mode\\n\"); return -1; }\n"
     "    u32 plane = 0;\n"
     "    for (u32 i = 0; i < np; i++)\n"
     "        if (planes[i].currentDisplay == VK_NULL_HANDLE || planes[i].currentDisplay == dsp) { plane = i; break; }\n"
     "    VkDisplaySurfaceCreateInfoKHR si = {\n"
     "        .sType = VK_STRUCTURE_TYPE_DISPLAY_SURFACE_CREATE_INFO_KHR,\n"
     "        .displayMode = mode, .planeIndex = plane,\n"
     "        .planeStackIndex = planes[plane].currentStackIndex,\n"
     "        .transform = VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR, .globalAlpha = 1.0f,\n"
     "        .alphaMode = VK_DISPLAY_PLANE_ALPHA_OPAQUE_BIT_KHR, .imageExtent = ext,\n"
     "    };\n"
     "    if (cps(s_vk.instance, &si, NULL, &s_vk.surface) != VK_SUCCESS) { VK_LOG(\"display surface failed\\n\"); return -1; }\n"
     "    VK_LOG(\"PS5 display %ux%u, plane %u\\n\", ext.width, ext.height, plane);\n"
     "    return 0;\n"
     "}\n"
     "#endif\n"
     "\n"
     "static int vk_load_library(void)\n{\n"
     "#if defined(__PROSPERO__)\n"
     "    if (!vk_icdGetInstanceProcAddr) { VK_LOG(\"RADV is not linked in (no vk_icdGetInstanceProcAddr)\\n\"); return -1; }\n"
     "    pvkGetInstanceProcAddr = ps5_vk_gipa;\n"
     "    VK_GLOBAL_FNS(PS5_LOAD_G)\n"
     "    return 0;\n"
     "#endif\n",
     "PS5 loader")

# The loader's per-function macro, usable before vk_load_library's own LOAD_G is defined.
edit(VK,
     "static vk_state s_vk;\n",
     "static vk_state s_vk;\n"
     "#define PS5_LOAD_G(name) \\\n"
     "    if (!(p##name = (PFN_##name)pvkGetInstanceProcAddr(VK_NULL_HANDLE, #name))) \\\n"
     "        { fprintf(stderr, \"[RSX vulkan] missing global function \" #name \"\\n\"); return -1; }\n",
     "PS5 load macro")

edit(VK,
     "static void vk_window_open(const char* title)\n{\n",
     "static void vk_window_open(const char* title)\n{\n"
     "#if defined(__PROSPERO__)\n"
     "    /* Always on screen: the VK_KHR_display surface is made once the instance exists. */\n"
     "    (void)title;\n"
     "    s_vk.inst_exts[0] = VK_KHR_SURFACE_EXTENSION_NAME;\n"
     "    s_vk.inst_exts[1] = VK_KHR_DISPLAY_EXTENSION_NAME;\n"
     "    s_vk.inst_ext_count = 2;\n"
     "    s_vk.windowed = 1;\n"
     "    return;\n"
     "#endif\n",
     "PS5 window")

edit(VK,
     "        } else if (!SDL_Vulkan_CreateSurface(s_vk.window, s_vk.instance, &s_vk.surface)) {\n",
     "#if defined(__PROSPERO__)\n"
     "        } else if (ps5_vk_display_surface() != 0) {\n"
     "            vk_window_drop(\"no PS5 display surface\");\n"
     "        }\n"
     "    }\n"
     "    if (0) {\n"
     "        if (0) {\n"
     "#endif\n"
     "        } else if (!SDL_Vulkan_CreateSurface(s_vk.window, s_vk.instance, &s_vk.surface)) {\n",
     "PS5 surface")

edit(VK,
     "    if (s_vk.lib) dlclose(s_vk.lib);\n",
     "#if !defined(__PROSPERO__)\n"
     "    if (s_vk.lib) dlclose(s_vk.lib);\n"
     "#endif\n",
     "PS5 no dlclose")

edit(VK,
     "    VkExtent2D ext = caps.currentExtent;\n"
     "    if (ext.width == 0xFFFFFFFFu) {\n",
     "    VkExtent2D ext = caps.currentExtent;\n"
     "#if defined(__PROSPERO__)\n"
     "    (void)sceSystemServiceHideSplashScreen();\n"
     "    if (ext.width == 0xFFFFFFFFu) { ext.width = 3840; ext.height = 2160; }\n"
     "#endif\n"
     "    if (ext.width == 0xFFFFFFFFu) {\n",
     "PS5 swapchain extent")

# SPU non-local exits on the PS5: the SDK's libc has setjmp/longjmp but not _setjmp/_longjmp; use
# ps5_setjmp/ps5_longjmp (tools/ps5/ps5_shims.c), which skip the signal mask like _setjmp does.
edit("runtime/spu/spu_context.h",
     "#else\n#  define SPU_SETJMP(env)     _setjmp(env)\n",
     "#elif defined(__PROSPERO__)\n"
     "#  define SPU_SETJMP(env)     ps5_setjmp(env)\n"
     "#  define SPU_LONGJMP(env, v) ps5_longjmp(env, v)\n"
     "#else\n#  define SPU_SETJMP(env)     _setjmp(env)\n",
     "PS5 SPU setjmp")

# vm_commit / vm_protect on the PS5: the guest space is one read-write direct-memory mapping
# (tools/ps5/ps5_app.c), so there is nothing to commit, and mprotect does not apply to it.
edit("runtime/memory/vm.h",
     "static inline int vm__mprotect_pages(uint32_t addr, uint32_t size, int prot)\n{\n",
     "static inline int vm__mprotect_pages(uint32_t addr, uint32_t size, int prot)\n{\n"
     "#if defined(__PROSPERO__)\n"
     "    (void)addr; (void)size; (void)prot;\n"
     "    return 0;\n"
     "#endif\n",
     "PS5 vm commit no-op")

# Vulkan: the fragment decompiler declares textures either one per unit (`Texture2D rsx_texN :
# register(tN)`) or, when no unit is a cube, as `Texture2D rsx_tex[16] : register(t0)` indexed with
# constants. The set layout has one binding per unit, so the array form is rewritten to per-unit
# declarations before glslang (validation VUID-VkGraphicsPipelineCreateInfo-layout-07991).
edit(VK0,
     "static int vk_eng_translate(const char* hlsl, int stage, VkShaderModule* out)\n{\n"
     "    u32 words = 0;\n",
     "static char* vk_split_tex_array(const char* hlsl)\n"
     "{\n"
     "    static const char decl[] = \"Texture2D    rsx_tex[16] : register(t0);\\n\";\n"
     "    const char* d = strstr(hlsl, decl);\n"
     "    if (!d) return NULL;\n"
     "    char* out = (char*)malloc(strlen(hlsl) + 16u * 48u + 64u);\n"
     "    if (!out) return NULL;\n"
     "    char* o = out;\n"
     "    memcpy(o, hlsl, (size_t)(d - hlsl));\n"
     "    o += d - hlsl;\n"
     "    for (u32 u = 0; u < 16u; u++) o += sprintf(o, \"Texture2D rsx_tex%u : register(t%u);\\n\", u, u);\n"
     "    for (const char* s = d + sizeof decl - 1; *s;) {\n"
     "        if (!strncmp(s, \"rsx_tex[\", 8)) {\n"
     "            char* end;\n"
     "            const unsigned long u = strtoul(s + 8, &end, 10);\n"
     "            if (end != s + 8 && *end == ']') { o += sprintf(o, \"rsx_tex%lu\", u); s = end + 1; continue; }\n"
     "        }\n"
     "        *o++ = *s++;\n"
     "    }\n"
     "    *o = 0;\n"
     "    return out;\n"
     "}\n"
     "\n"
     "static int vk_eng_translate(const char* hlsl, int stage, VkShaderModule* out)\n{\n"
     "    char* split = stage == RSX_SHADER_STAGE_FRAGMENT ? vk_split_tex_array(hlsl) : NULL;\n"
     "    if (split) hlsl = split;\n"
     "    u32 words = 0;\n",
     "texture array -> per-unit (1)")
edit(VK0,
     "    if (rsx_hlsl_to_spirv(hlsl, stage, s_g.spv, VK_SPV_WORDS, &words, s_g.log, sizeof s_g.log) || !words) {\n"
     "        VK_LOG(\"engine: %s translation failed: %s\\n\",\n"
     "               stage == RSX_SHADER_STAGE_VERTEX ? \"vertex\" : \"fragment\", s_g.log);\n"
     "        return -1;\n"
     "    }\n",
     "    const int bad = rsx_hlsl_to_spirv(hlsl, stage, s_g.spv, VK_SPV_WORDS, &words, s_g.log, sizeof s_g.log) || !words;\n"
     "    free(split);\n"
     "    if (bad) {\n"
     "        VK_LOG(\"engine: %s translation failed: %s\\n\",\n"
     "               stage == RSX_SHADER_STAGE_VERTEX ? \"vertex\" : \"fragment\", s_g.log);\n"
     "        return -1;\n"
     "    }\n",
     "texture array -> per-unit (2)")

# ---------------------------------------------------------------------------------------------------
# Vulkan: color_snapshot and depth_snapshot_rgba8, two of the Metal-only draw-engine hooks. inFamous 2
# reached gameplay with only additive effects visible (no opaque world): its deferred passes sample
# their own targets (read-modify-write) and read the Z24S8 depth buffer through A8R8G8B8, both of
# which came back as nothing on Vulkan. Each target keeps one snapshot texture (snap2), refilled per
# request and released with the target, like the existing depth_snapshot.
#   color_snapshot: vkCmdCopyImage of the target into an RGBA8 texture.
#   depth_snapshot_rgba8: the D32_SFLOAT depth copied out, packed on the CPU as the RSX returns
#     Z24S8 through a colour format (RPCS3 decode_depth24): a = D[23:16], r = D[15:8], g = D[7:0],
#     b = stencil (0: no stencil aspect yet), uploaded as RGBA8. Exact but slow; a GPU pass is next.
# ---------------------------------------------------------------------------------------------------
edit(VK0,
     "    u32      surface, remap, rsx_fmt;/* VIEW: what it is a view of          */\n} vk_eng_obj;\n",
     "    u32      surface, remap, rsx_fmt;/* VIEW: what it is a view of          */\n"
     "    u32      snap2;                  /* COLOR/DEPTH: colour / RGBA8 snapshot */\n} vk_eng_obj;\n",
     "snap2 field")
edit(VK0,
     "    if (s_eobj[handle].kind == VK_ENG_COLOR || s_eobj[handle].kind == VK_ENG_DEPTH)\n"
     "        vk_eng_drop_framebuffers();\n",
     "    if (s_eobj[handle].snap2) {\n"
     "        const u32 snap = s_eobj[handle].snap2;\n"
     "        s_eobj[handle].snap2 = 0;\n"
     "        if (vk_eng_get(snap, VK_ENG_TEXTURE)) vk_eng_release(user, snap);\n"
     "    }\n"
     "    if (s_eobj[handle].kind == VK_ENG_COLOR || s_eobj[handle].kind == VK_ENG_DEPTH)\n"
     "        vk_eng_drop_framebuffers();\n",
     "snap2 release")
edit(VK0,
     "/* ---- E2: pipelines and draws ---------------------------------------------\n",
     "/* The snapshot texture a target keeps in snap2: RGBA8, w x h, made or remade as needed. */\n"
     "static vk_eng_obj* vk_eng_snap2(void* user, u32 owner, u32 w, u32 h)\n"
     "{\n"
     "    u32 snap = s_eobj[owner].snap2;\n"
     "    vk_eng_obj* t = vk_eng_get(snap, VK_ENG_TEXTURE);\n"
     "    if (t && t->w == w && t->h == h) return t;\n"
     "    if (t) vk_eng_release(user, snap);\n"
     "    s_eobj[owner].snap2 = 0;\n"
     "    snap = vk_eng_alloc();\n"
     "    if (!snap) return NULL;\n"
     "    t = &s_eobj[snap];\n"
     "    if (vk_create_image(&t->im, VK_FORMAT_R8G8B8A8_UNORM, w, h,\n"
     "                        VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,\n"
     "                        VK_IMAGE_ASPECT_COLOR_BIT)) {\n"
     "        vk_destroy_image(&t->im); memset(t, 0, sizeof *t); return NULL;\n"
     "    }\n"
     "    t->kind = VK_ENG_TEXTURE; t->fmt = VK_FORMAT_R8G8B8A8_UNORM; t->bpp = 4; t->w = w; t->h = h;\n"
     "    s_eobj[owner].snap2 = snap;\n"
     "    if (vk_begin()) return NULL;\n"
     "    vk_barrier_image(t->im.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_UNDEFINED);\n"
     "    if (vk_submit_and_wait()) return NULL;\n"
     "    return t;\n"
     "}\n"
     "\n"
     "static u32 vk_eng_color_snapshot(void* user, u32 surface)\n"
     "{\n"
     "    vk_eng_obj* c = vk_eng_get(surface, VK_ENG_COLOR);\n"
     "    if (!c || c->fmt != VK_FORMAT_R8G8B8A8_UNORM || !c->w || !c->h) return 0;\n"
     "    const u32 w = c->w, h = c->h;\n"
     "    vk_eng_obj* t = vk_eng_snap2(user, surface, w, h);\n"
     "    if (!t) return 0;\n"
     "    c = vk_eng_get(surface, VK_ENG_COLOR);\n"
     "    if (vk_begin()) return 0;\n"
     "    vk_barrier_image(c->im.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);\n"
     "    vk_barrier_image(t->im.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);\n"
     "    VkImageCopy cp = { .srcSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 },\n"
     "                       .dstSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 },\n"
     "                       .extent = { w, h, 1 } };\n"
     "    pvkCmdCopyImage(s_vk.cmd, c->im.img, VK_IMAGE_LAYOUT_GENERAL, t->im.img, VK_IMAGE_LAYOUT_GENERAL, 1, &cp);\n"
     "    if (vk_submit_and_wait()) return 0;\n"
     "    return s_eobj[surface].snap2;\n"
     "}\n"
     "\n"
     "static u32 vk_eng_depth_snapshot_rgba8(void* user, u32 depth, u32 w, u32 h)\n"
     "{\n"
     "    vk_eng_obj* z = vk_eng_get(depth, VK_ENG_DEPTH);\n"
     "    if (!z || s_vk.depth_format != VK_FORMAT_D32_SFLOAT) return 0;\n"
     "    if (w > z->w) w = z->w;\n"
     "    if (h > z->h) h = z->h;\n"
     "    if (!w || !h) return 0;\n"
     "    vk_eng_obj* t = vk_eng_snap2(user, depth, w, h);\n"
     "    if (!t) return 0;\n"
     "    z = vk_eng_get(depth, VK_ENG_DEPTH);\n"
     "    vk_buffer st = {0};\n"
     "    if (vk_create_host_buffer(&st, (VkDeviceSize)w * h * 4u,\n"
     "                              VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT) || !st.coherent) {\n"
     "        vk_destroy_buffer(&st); return 0;\n"
     "    }\n"
     "    int rc = vk_begin();\n"
     "    if (!rc) {\n"
     "        vk_barrier_image(z->im.img, VK_IMAGE_ASPECT_DEPTH_BIT, VK_IMAGE_LAYOUT_GENERAL);\n"
     "        VkBufferImageCopy out = { .imageSubresource = { VK_IMAGE_ASPECT_DEPTH_BIT, 0, 0, 1 },\n"
     "                                  .imageExtent = { w, h, 1 } };\n"
     "        pvkCmdCopyImageToBuffer(s_vk.cmd, z->im.img, VK_IMAGE_LAYOUT_GENERAL, st.buf, 1, &out);\n"
     "        rc = vk_submit_and_wait();\n"
     "    }\n"
     "    if (!rc) {\n"
     "        vk_invalidate(&st);\n"
     "        u32* px = (u32*)st.ptr;\n"
     "        const float* d = (const float*)st.ptr;\n"
     "        for (size_t i = 0, n = (size_t)w * h; i < n; i++) {\n"
     "            float v = d[i];\n"
     "            v = v < 0.0f ? 0.0f : v > 1.0f ? 1.0f : v;\n"
     "            const u32 d24 = (u32)(v * 16777215.0f + 0.5f);\n"
     "            /* bytes R, G, B, A = D[15:8], D[7:0], stencil, D[23:16] */\n"
     "            px[i] = ((d24 >> 8) & 0xFFu) | ((d24 & 0xFFu) << 8) | (((d24 >> 16) & 0xFFu) << 24);\n"
     "        }\n"
     "        rc = vk_begin();\n"
     "        if (!rc) {\n"
     "            vk_barrier_image(t->im.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);\n"
     "            VkBufferImageCopy in = { .imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 },\n"
     "                                     .imageExtent = { w, h, 1 } };\n"
     "            pvkCmdCopyBufferToImage(s_vk.cmd, st.buf, t->im.img, VK_IMAGE_LAYOUT_GENERAL, 1, &in);\n"
     "            rc = vk_submit_and_wait();\n"
     "        }\n"
     "    }\n"
     "    vk_destroy_buffer(&st);\n"
     "    return rc ? 0 : s_eobj[depth].snap2;\n"
     "}\n"
     "\n"
     "/* ---- E2: pipelines and draws ---------------------------------------------\n",
     "snapshot hooks")
edit(VK0,
     "    X(vkCmdCopyImageToBuffer) X(vkCmdCopyBufferToImage) \\\n",
     "    X(vkCmdCopyImageToBuffer) X(vkCmdCopyBufferToImage) X(vkCmdCopyImage) \\\n",
     "load vkCmdCopyImage")
edit(VK0,
     "    .depth_snapshot       = vk_eng_depth_snapshot,\n",
     "    .depth_snapshot       = vk_eng_depth_snapshot,\n"
     "    .color_snapshot       = vk_eng_color_snapshot,\n"
     "    .depth_snapshot_rgba8 = vk_eng_depth_snapshot_rgba8,\n",
     "snapshot hooks in the table")

# ---------------------------------------------------------------------------------------------------
# Vulkan: batched submission on the draw-engine path (PS3RECOMP_VK_BATCH=0 turns it off). Every
# clear/draw/upload used to be its own command buffer, submitted and waited on. Now one command
# buffer stays open: vk_begin() keeps recording, vk_submit_and_wait() is a no-op until vk_flush(),
# which happens where the CPU needs the GPU's results (present + its readback, readbacks, the CPU
# depth packing, the engine's submit_and_wait = guest references and shutdown) or when the per-frame
# ring / descriptor pool is full. Each draw takes its vertices, indices and constants from a ring
# buffer and its own descriptor set from a pool, both reset at a flush; buffers and images released
# while recording are freed after the flush.
# ---------------------------------------------------------------------------------------------------
edit(VK0,
     "    X(vkCreateDescriptorPool) X(vkDestroyDescriptorPool) \\\n",
     "    X(vkCreateDescriptorPool) X(vkDestroyDescriptorPool) X(vkResetDescriptorPool) \\\n",
     "batch: load vkResetDescriptorPool")
edit(VK0, r'''static vk_state s_vk;
''', r'''static vk_state s_vk;

/* Batching state (see vk_flush). */
static int              s_rec, s_force;
#define VK_GARBAGE_MAX  8192
static vk_buffer        s_gbuf[VK_GARBAGE_MAX];
static u32              s_ngbuf;
static vk_image         s_gimg[VK_GARBAGE_MAX];
static u32              s_ngimg;
static vk_buffer        s_ring;                 /* per-frame vertices, indices, constants */
static VkDeviceSize     s_ring_off, s_ubo_align;
static VkDescriptorPool s_dpool;                /* per-draw descriptor sets               */
static u32              s_dsets;
#define VK_RING_BYTES   (128u << 20)
#define VK_DPOOL_SETS   4096u
static VkDescriptorSet  s_wd_set;               /* this draw's set / ring slice, or 0      */
static VkBuffer         s_wd_buf;
static VkDeviceSize     s_wd_vs, s_wd_ps;
static int vk_batching(void)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3RECOMP_VK_BATCH"); on = !(e && e[0] == '0'); }
    return on && s_vk.eng_active;
}
''', "batch: state")
edit(VK0, r'''static void vk_destroy_image(vk_image* im)
{
''', r'''static void vk_destroy_image(vk_image* im)
{
    if (s_rec && vk_batching() && s_ngimg < VK_GARBAGE_MAX && (im->img || im->view)) {
        s_gimg[s_ngimg++] = *im;                /* still used by the open command buffer */
        memset(im, 0, sizeof *im);
        return;
    }
''', "batch: deferred image destroy")
edit(VK0, r'''static void vk_destroy_buffer(vk_buffer* b)
{
''', r'''static void vk_destroy_buffer(vk_buffer* b)
{
    if (s_rec && vk_batching() && s_ngbuf < VK_GARBAGE_MAX && b->buf) {
        s_gbuf[s_ngbuf++] = *b;
        memset(b, 0, sizeof *b);
        return;
    }
''', "batch: deferred buffer destroy")
edit(VK0, r'''static int vk_begin(void)
{
    VK_CHECK(pvkResetCommandBuffer(s_vk.cmd, 0), "vkResetCommandBuffer");
    VkCommandBufferBeginInfo bi = { .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
                                    .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT };
    VK_CHECK(pvkBeginCommandBuffer(s_vk.cmd, &bi), "vkBeginCommandBuffer");
    return 0;
}

static int vk_submit_and_wait(void)
{
    VK_CHECK(pvkEndCommandBuffer(s_vk.cmd), "vkEndCommandBuffer");
''', r'''static int vk_begin(void)
{
    if (s_rec) return 0;                        /* batching: keep recording */
    VK_CHECK(pvkResetCommandBuffer(s_vk.cmd, 0), "vkResetCommandBuffer");
    VkCommandBufferBeginInfo bi = { .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
                                    .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT };
    VK_CHECK(pvkBeginCommandBuffer(s_vk.cmd, &bi), "vkBeginCommandBuffer");
    s_rec = 1;
    return 0;
}

/* After a real submission: free what was released while recording, restart the ring and pool. */
static void vk_batch_after_flush(void)
{
    for (u32 i = 0; i < s_ngbuf; i++) {
        vk_buffer* b = &s_gbuf[i];
        if (b->ptr) pvkUnmapMemory(s_vk.device, b->mem);
        if (b->buf) pvkDestroyBuffer(s_vk.device, b->buf, NULL);
        if (b->mem) pvkFreeMemory(s_vk.device, b->mem, NULL);
    }
    s_ngbuf = 0;
    for (u32 i = 0; i < s_ngimg; i++) {
        vk_image* im = &s_gimg[i];
        if (im->view) pvkDestroyImageView(s_vk.device, im->view, NULL);
        if (im->img)  pvkDestroyImage(s_vk.device, im->img, NULL);
        if (im->mem)  pvkFreeMemory(s_vk.device, im->mem, NULL);
    }
    s_ngimg = 0;
    s_ring_off = 0;
    if (s_dpool && s_dsets) { pvkResetDescriptorPool(s_vk.device, s_dpool, 0); s_dsets = 0; }
}

static int vk_submit_and_wait(void)
{
    if (!s_rec) return 0;
    if (vk_batching() && !s_force) return 0;   /* recorded; submitted at the next vk_flush */
    s_rec = 0;
    VK_CHECK(pvkEndCommandBuffer(s_vk.cmd), "vkEndCommandBuffer");
''', "batch: begin/submit")
edit(VK0, r'''    VK_CHECK(pvkWaitForFences(s_vk.device, 1, &s_vk.fence, VK_TRUE, UINT64_MAX), "vkWaitForFences");
    return 0;
}
''', r'''    VK_CHECK(pvkWaitForFences(s_vk.device, 1, &s_vk.fence, VK_TRUE, UINT64_MAX), "vkWaitForFences");
    vk_batch_after_flush();
    return 0;
}

/* Submit everything recorded so far and wait: the CPU is about to read what the GPU wrote. */
static int vk_flush(void)
{
    s_force = 1;
    const int r = vk_submit_and_wait();
    s_force = 0;
    return r;
}
''', "batch: flush")
edit(VK0, r'''    if (vk_submit_and_wait()) return;

    vk_invalidate(&s_vk.readback);''', r'''    if (vk_flush()) return;

    vk_invalidate(&s_vk.readback);''', "batch: present readback flushes")
edit(VK0, r'''    if (vk_begin()) return;
    vk_barrier_image(s_vk.color.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);
    VkImageMemoryBarrier b = {''', r'''    vk_flush();
    if (vk_begin()) return;
    vk_barrier_image(s_vk.color.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);
    VkImageMemoryBarrier b = {''', "batch: window present starts clean")
edit(VK0, r'''    if (pvkEndCommandBuffer(s_vk.cmd) != VK_SUCCESS) { VK_LOG("vkEndCommandBuffer failed\n"); return; }
''', r'''    s_rec = 0;                                  /* ended here, submitted with the semaphores */
    if (pvkEndCommandBuffer(s_vk.cmd) != VK_SUCCESS) { VK_LOG("vkEndCommandBuffer failed\n"); return; }
''', "batch: window present ends the buffer")
edit(VK0, r'''        if (!vk_submit_and_wait()) {
            vk_invalidate(&st);''', r'''        if (!vk_flush()) {
            vk_invalidate(&st);''', "batch: readback flushes")
edit(VK0, r'''        rc = vk_submit_and_wait();
    }
    if (!rc) {
        vk_invalidate(&st);''', r'''        rc = vk_flush();
    }
    if (!rc) {
        vk_invalidate(&st);''', "batch: depth rgba8 flushes")
edit(VK0, r'''    (void)user; (void)reason;      /* every submission has already completed */
''', r'''    (void)user; (void)reason;
    vk_flush();                    /* guest references and shutdown read the results */
''', "batch: engine submit_and_wait flushes")
edit(VK0, r'''        { s_g.ubo.buf, 0, s_e2.vs_bytes ? s_e2.vs_bytes : 16u },
        { s_g.ubo.buf, s_g.ps_off, s_e2.ps_bytes ? s_e2.ps_bytes : 16u },''',
     r'''        { s_wd_buf ? s_wd_buf : s_g.ubo.buf, s_wd_buf ? s_wd_vs : 0, s_e2.vs_bytes ? s_e2.vs_bytes : 16u },
        { s_wd_buf ? s_wd_buf : s_g.ubo.buf, s_wd_buf ? s_wd_ps : s_g.ps_off, s_e2.ps_bytes ? s_e2.ps_bytes : 16u },''',
     "batch: descriptors from the ring")
edit(VK0, r'''    pvkUpdateDescriptorSets(s_vk.device, 4, w, 0, NULL);
}

static void vk_eng_draw(''', r'''    if (s_wd_set) for (int i = 0; i < 4; i++) w[i].dstSet = s_wd_set;
    pvkUpdateDescriptorSets(s_vk.device, 4, w, 0, NULL);
}

/* Batching: this draw's vertices, indices and constants into the ring, its own descriptor set. */
static void* vk_ring_alloc(VkDeviceSize bytes, VkDeviceSize align, VkDeviceSize* off)
{
    VkDeviceSize o = (s_ring_off + align - 1u) / align * align;
    if (o + bytes > s_ring.size) return NULL;
    s_ring_off = o + bytes;
    *off = o;
    return (u8*)s_ring.ptr + o;
}

static int vk_batch_draw_begin(const void* vertices, VkDeviceSize vbytes, const u32* indices,
                               VkDeviceSize ibytes, VkDeviceSize* voff, VkDeviceSize* ioff)
{
    if (!s_ring.buf) {
        if (vk_create_host_buffer(&s_ring, VK_RING_BYTES, VK_BUFFER_USAGE_VERTEX_BUFFER_BIT |
                                  VK_BUFFER_USAGE_INDEX_BUFFER_BIT | VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT) ||
            !s_ring.coherent) { VK_LOG("batch: no ring buffer\n"); return -1; }
        VkPhysicalDeviceProperties p;
        pvkGetPhysicalDeviceProperties(s_vk.phys, &p);
        s_ubo_align = p.limits.minUniformBufferOffsetAlignment ? p.limits.minUniformBufferOffsetAlignment : 256;
        VkDescriptorPoolSize ps[3] = {
            { VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 2u * VK_DPOOL_SETS },
            { VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, RSX_MAX_TEXTURES * VK_DPOOL_SETS },
            { VK_DESCRIPTOR_TYPE_SAMPLER, RSX_MAX_TEXTURES * VK_DPOOL_SETS },
        };
        VkDescriptorPoolCreateInfo pci = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,
                                           .maxSets = VK_DPOOL_SETS, .poolSizeCount = 3, .pPoolSizes = ps };
        if (pvkCreateDescriptorPool(s_vk.device, &pci, NULL, &s_dpool) != VK_SUCCESS) {
            VK_LOG("batch: no descriptor pool\n"); return -1;
        }
    }
    const u32 vs_bytes = s_e2.vs_bytes ? s_e2.vs_bytes : 16u, ps_bytes = s_e2.ps_bytes ? s_e2.ps_bytes : 16u;
    const VkDeviceSize need = vbytes + ibytes + vs_bytes + ps_bytes + 4u * s_ubo_align + 64u;
    if (need > s_ring.size) return -1;
    if (s_ring_off + need > s_ring.size || s_dsets >= VK_DPOOL_SETS) vk_flush();
    VkDeviceSize vs_off, ps_off;
    void* v = vk_ring_alloc(vbytes, 16, voff);
    memcpy(v, vertices, (size_t)vbytes);
    if (ibytes) memcpy(vk_ring_alloc(ibytes, 4, ioff), indices, (size_t)ibytes);
    memcpy(vk_ring_alloc(vs_bytes, s_ubo_align, &vs_off), s_g.ubo.ptr, vs_bytes);
    memcpy(vk_ring_alloc(ps_bytes, s_ubo_align, &ps_off), (u8*)s_g.ubo.ptr + s_g.ps_off, ps_bytes);
    VkDescriptorSetAllocateInfo dai = { .sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
                                        .descriptorPool = s_dpool, .descriptorSetCount = 1,
                                        .pSetLayouts = &s_g.set_layout };
    if (pvkAllocateDescriptorSets(s_vk.device, &dai, &s_wd_set) != VK_SUCCESS) {
        vk_flush();
        if (pvkAllocateDescriptorSets(s_vk.device, &dai, &s_wd_set) != VK_SUCCESS) { s_wd_set = VK_NULL_HANDLE; return -1; }
    }
    s_dsets++;
    s_wd_buf = s_ring.buf; s_wd_vs = vs_off; s_wd_ps = ps_off;
    vk_eng_write_descriptors();
    return 0;
}

static void vk_eng_draw(''', "batch: ring + per-draw sets")
edit(VK0, r'''    const VkDeviceSize vbytes = (VkDeviceSize)vertex_count * stride;
    if (vk_ensure_vertex_buffer(vbytes)) return;
    memcpy(s_vk.vertices.ptr, vertices, (size_t)vbytes);
    if (indices && index_count) {
        if (vk_eng_ensure_indices((VkDeviceSize)index_count * 4u)) return;
        memcpy(s_e2.indices.ptr, indices, (size_t)index_count * 4u);
    }
    vk_eng_write_descriptors();
''', r'''    const VkDeviceSize vbytes = (VkDeviceSize)vertex_count * stride;
    VkBuffer vbuf, ibuf;
    VkDeviceSize voff = 0, ioff = 0;
    if (vk_batching()) {
        if (vk_batch_draw_begin(vertices, vbytes, indices,
                                (indices && index_count) ? (VkDeviceSize)index_count * 4u : 0, &voff, &ioff))
            return;
        vbuf = ibuf = s_ring.buf;
    } else {
        if (vk_ensure_vertex_buffer(vbytes)) return;
        memcpy(s_vk.vertices.ptr, vertices, (size_t)vbytes);
        if (indices && index_count) {
            if (vk_eng_ensure_indices((VkDeviceSize)index_count * 4u)) return;
            memcpy(s_e2.indices.ptr, indices, (size_t)index_count * 4u);
        }
        vk_eng_write_descriptors();
        vbuf = s_vk.vertices.buf; ibuf = s_e2.indices.buf;
    }
    const VkDescriptorSet dset = s_wd_set ? s_wd_set : s_g.set;
    s_wd_set = VK_NULL_HANDLE; s_wd_buf = VK_NULL_HANDLE;
''', "batch: draw data")
edit(VK0, r'''                             0, 1, &s_g.set, 0, NULL);
    VkDeviceSize off = 0;
    pvkCmdBindVertexBuffers(s_vk.cmd, 0, 1, &s_vk.vertices.buf, &off);
    if (indices && index_count) {
        pvkCmdBindIndexBuffer(s_vk.cmd, s_e2.indices.buf, 0, VK_INDEX_TYPE_UINT32);''', r'''                             0, 1, &dset, 0, NULL);
    pvkCmdBindVertexBuffers(s_vk.cmd, 0, 1, &vbuf, &voff);
    if (indices && index_count) {
        pvkCmdBindIndexBuffer(s_vk.cmd, ibuf, ioff, VK_INDEX_TYPE_UINT32);''', "batch: draw binds")

# ---------------------------------------------------------------------------------------------------
# sys_memory_allocate reuses freed blocks. It was a bump allocator over the 256 MB window and
# sys_memory_free never gave anything back, so a title that allocates and frees 1 MB blocks while
# streaming (inFamous 1) walked to the window's end and then got ENOMEM forever (216,000 retries a
# run). First fit among freed blocks of the same page size, the tail of a larger one split into a
# free slot, cleared (fresh guest memory reads 0, as the bump path's new commits do).
# ---------------------------------------------------------------------------------------------------
edit("runtime/syscalls/sys_memory.c", r'''    /* Check if we have room */
    if (g_sys_mem_bump_ptr + size > SYS_MEM_ALLOC_END) {
''', r'''    /* A freed block first (first fit, same page size), the rest of a larger one kept free. */
    for (int i = 0; i < SYS_MEMORY_ALLOC_MAX; i++) {
        sys_mem_alloc_info* f = &g_sys_mem_allocs[i];
        if (f->active || !f->addr || f->size < size || f->page_size != alignment) continue;
        const uint32_t at = f->addr, rest = f->size - size;
        if (rest) {
            int spare = -1;
            for (int j = 0; j < SYS_MEMORY_ALLOC_MAX; j++)
                if (!g_sys_mem_allocs[j].active && !g_sys_mem_allocs[j].addr) { spare = j; break; }
            if (spare < 0) continue;            /* no slot to keep the tail in: try another block */
            g_sys_mem_allocs[spare].addr = at + size;
            g_sys_mem_allocs[spare].size = rest;
            g_sys_mem_allocs[spare].page_size = alignment;
            g_sys_mem_allocs[spare].container_id = 0;
        }
        f->active = 1;
        f->size = size;
        f->container_id = 0;
        s_total_allocated += size;
        bump_unlock();
        memset(vm_to_host(at), 0, size);
        fprintf(stderr, "[sys_memory] allocate -> 0x%08X (reused)\n", at);
        if (addr_out != 0) write_be32(addr_out, at);
        return CELL_OK;
    }

    /* Check if we have room */
    if (g_sys_mem_bump_ptr + size > SYS_MEM_ALLOC_END) {
''', "sys_memory: reuse freed blocks")

# The PS3's user memory is 213 MB however big the guest window: refuse past it (as lv2 does), and
# never report a negative "available" (u32 wrap: a title sizing its heap from it would keep going).
edit("runtime/syscalls/sys_memory.c", r'''    /* A freed block first (first fit, same page size), the rest of a larger one kept free. */
''', r'''    if (s_total_allocated + size > SYS_MEM_USER_TOTAL && !getenv("PS3_MEM_NO_LIMIT")) {
        bump_unlock();
        return (int64_t)(int32_t)CELL_ENOMEM;
    }
    /* A freed block first (first fit, same page size), the rest of a larger one kept free. */
''', "sys_memory: 213 MB limit")
edit("runtime/syscalls/sys_memory.c", r'''        uint32_t avail = total - s_total_allocated;
''', r'''        uint32_t avail = s_total_allocated < total ? total - s_total_allocated : 0;
''', "sys_memory: available never wraps")

# ---------------------------------------------------------------------------------------------------
# PS5 (__PROSPERO__): the controller and the sound through the console's own scePad / sceAudioOut, as
# the PS5 apps that already run on the console do (gta4-ps5's ps5_input_driver / ps5_audio_driver,
# plume-triangle's pad), instead of the PS5 SDL2 build's game controller and audio subsystems.
# ---------------------------------------------------------------------------------------------------
edit("libs/input/cellPad.c", r'''static void pad_poll_sdl2(void)
{
''', r'''#if defined(__PROSPERO__)
/* The DualSense through scePad. Its button bits are the PS3's CELL_PAD_CTRL_* bits (L3 0x2, R3 0x4,
 * OPTIONS = START 0x8, the d-pad 0x10-0x80, L1/R1 0x400/0x800, triangle..square 0x1000-0x8000);
 * the touchpad click stands in for SELECT, and L2/R2 come from the analog triggers. */
int sceUserServiceInitialize(void* params);
int sceUserServiceGetForegroundUser(int32_t* user_id);
int sceUserServiceGetInitialUser(int32_t* user_id);
int scePadInit(void);
int scePadOpen(int32_t user_id, int32_t type, int32_t index, const void* param);
int scePadGetHandle(int32_t user_id, int32_t type, int32_t index);
int scePadReadState(int32_t handle, void* data);
typedef struct { uint8_t large_motor, small_motor; } ps5_pad_vibration;
int scePadSetVibration(int32_t handle, const ps5_pad_vibration* param);
int scePadSetVibrationMode(int32_t handle, int32_t mode);
typedef struct {
    uint32_t buttons;
    uint8_t lx, ly, rx, ry, l2, r2;
    uint16_t pad;
    uint8_t rest[240];                    /* the rest of ScePadData */
} ps5_pad_data;
static int32_t s_ps5_pad = -1;
static unsigned long long s_ps5_pad_retry;

static void pad_ps5_open(void)
{
    int32_t user = -1;
    if (sceUserServiceGetForegroundUser(&user) != 0 || user < 0) sceUserServiceGetInitialUser(&user);
    if (user < 0) return;
    int32_t h = scePadOpen(user, 0, 0, NULL);
    if (h < 0) h = scePadGetHandle(user, 0, 0);
    if (h >= 0) {
        s_ps5_pad = h;
        scePadSetVibrationMode(h, 2);     /* the compatible dual-motor rumble */
        printf("[cellPad] PS5 controller: user %d, handle %d\n", user, h);
    }
}

static void pad_poll_ps5(void)
{
    for (int i = 1; i < PAD_MAX_HOST_PORTS; i++) s_host_state[i].connected = 0;
    if (s_ps5_pad < 0) {
        const unsigned long long now = pad_now_ms();
        if (now - s_ps5_pad_retry > 1000) { s_ps5_pad_retry = now; pad_ps5_open(); }
        if (s_ps5_pad < 0) { s_host_state[0].connected = 0; return; }
    }
    ps5_pad_data d;
    memset(&d, 0, sizeof d);
    if (scePadReadState(s_ps5_pad, &d) != 0) { s_host_state[0].connected = 0; return; }
    PadHostState* hs = &s_host_state[0];
    hs->connected = 1;
    u16 b = (u16)(d.buttons & 0xFCFEu);
    if (d.buttons & 0x00100000u) b |= CELL_PAD_CTRL_SELECT;
    if (d.l2 > 32) b |= CELL_PAD_CTRL_L2;
    if (d.r2 > 32) b |= CELL_PAD_CTRL_R2;
    hs->buttons = b;
    hs->analog_lx = d.lx; hs->analog_ly = d.ly;
    hs->analog_rx = d.rx; hs->analog_ry = d.ry;
    hs->trigger_l2 = d.l2; hs->trigger_r2 = d.r2;
    hs->press_up       = (b & CELL_PAD_CTRL_UP)       ? 255 : 0;
    hs->press_down     = (b & CELL_PAD_CTRL_DOWN)     ? 255 : 0;
    hs->press_left     = (b & CELL_PAD_CTRL_LEFT)     ? 255 : 0;
    hs->press_right    = (b & CELL_PAD_CTRL_RIGHT)    ? 255 : 0;
    hs->press_triangle = (b & CELL_PAD_CTRL_TRIANGLE) ? 255 : 0;
    hs->press_circle   = (b & CELL_PAD_CTRL_CIRCLE)   ? 255 : 0;
    hs->press_cross    = (b & CELL_PAD_CTRL_CROSS)    ? 255 : 0;
    hs->press_square   = (b & CELL_PAD_CTRL_SQUARE)   ? 255 : 0;
    hs->press_l1       = (b & CELL_PAD_CTRL_L1)       ? 255 : 0;
    hs->press_r1       = (b & CELL_PAD_CTRL_R1)       ? 255 : 0;
    g_pad_overlay_raw = 0;
}
#endif

static void pad_poll_sdl2(void)
{
#if defined(__PROSPERO__)
    pad_poll_ps5();
    return;
#endif
''', "PS5 pad: scePad poll")
edit("libs/input/cellPad.c", r'''static void pad_init_backend(void)
{
    if (pad_sdl_off()) return;
''', r'''static void pad_init_backend(void)
{
#if defined(__PROSPERO__)
    sceUserServiceInitialize(NULL);
    const int rc = scePadInit();
    if (rc != 0) printf("[cellPad] scePadInit: 0x%08X\n", (unsigned)rc);
    pad_ps5_open();
    return;
#endif
    if (pad_sdl_off()) return;
''', "PS5 pad: scePad init")
edit("libs/audio/cellAudio.c", r'''static int audio_backend_init(void)
{
    if (SDL_WasInit(SDL_INIT_AUDIO) == 0) {
''', r'''#if defined(__PROSPERO__)
/* The PS5: one sceAudioOut port (the system user's main output, 256-sample frames, 48 kHz, s16
 * stereo), fed from a ring by a thread that sceAudioOutOutput paces. */
#include <pthread.h>
#include <unistd.h>
int32_t sceAudioOutInit(void);
int32_t sceAudioOutOpen(int32_t user_id, int32_t type, int32_t index, uint32_t len, uint32_t freq, uint32_t param);
int32_t sceAudioOutOutput(int32_t handle, const void* ptr);
int32_t sceAudioOutClose(int32_t handle);
#define PS5A_FRAME 256u
#define PS5A_RING  (CELL_AUDIO_BLOCK_SAMPLES * 32u)   /* stereo samples */
static float s_ps5a_ring[PS5A_RING * 2];
static u32 s_ps5a_rd, s_ps5a_wr;                      /* monotonic sample counters */
static int32_t s_ps5a_port = -1;
static volatile int s_ps5a_run;
static pthread_t s_ps5a_thread;

static void* ps5a_main(void* arg)
{
    (void)arg;
    int16_t pcm[PS5A_FRAME * 2];
    while (s_ps5a_run) {
        u32 rd = __atomic_load_n(&s_ps5a_rd, __ATOMIC_ACQUIRE);
        const u32 wr = __atomic_load_n(&s_ps5a_wr, __ATOMIC_ACQUIRE);
        for (u32 i = 0; i < PS5A_FRAME; i++) {
            float l = 0.0f, r = 0.0f;
            if (rd != wr) { const u32 k = (rd % PS5A_RING) * 2u; l = s_ps5a_ring[k]; r = s_ps5a_ring[k + 1]; rd++; }
            l = l > 1.0f ? 1.0f : l < -1.0f ? -1.0f : l;
            r = r > 1.0f ? 1.0f : r < -1.0f ? -1.0f : r;
            pcm[2 * i] = (int16_t)(l * 32767.0f);
            pcm[2 * i + 1] = (int16_t)(r * 32767.0f);
        }
        __atomic_store_n(&s_ps5a_rd, rd, __ATOMIC_RELEASE);
        sceAudioOutOutput(s_ps5a_port, pcm);           /* blocks until the frame is taken */
    }
    return NULL;
}

static int audio_backend_init(void)
{
    sceAudioOutInit();
    s_ps5a_port = sceAudioOutOpen(0xFF, 0, 0, PS5A_FRAME, 48000, 1);
    if (s_ps5a_port < 0) {
        printf("[cellAudio] sceAudioOutOpen failed: 0x%08X\n", (unsigned)s_ps5a_port);
        return -1;
    }
    s_ps5a_run = 1;
    if (pthread_create(&s_ps5a_thread, NULL, ps5a_main, NULL) != 0) { s_ps5a_run = 0; return -1; }
    printf("[cellAudio] output: PS5 sceAudioOut port %d\n", s_ps5a_port);
    return 0;
}

static void audio_backend_shutdown(void)
{
    if (s_ps5a_run) { s_ps5a_run = 0; pthread_join(s_ps5a_thread, NULL); }
    if (s_ps5a_port >= 0) { sceAudioOutClose(s_ps5a_port); s_ps5a_port = -1; }
}

static void audio_backend_submit(const float* stereo_samples, u32 num_samples)
{
    if (s_ps5a_port < 0) return;
    u32 wr = __atomic_load_n(&s_ps5a_wr, __ATOMIC_ACQUIRE);
    const u32 rd = __atomic_load_n(&s_ps5a_rd, __ATOMIC_ACQUIRE);
    if (wr - rd + num_samples > PS5A_RING) return;    /* full: drop (room() keeps this from happening) */
    for (u32 i = 0; i < num_samples; i++, wr++) {
        const u32 k = (wr % PS5A_RING) * 2u;
        s_ps5a_ring[k] = stereo_samples[2 * i];
        s_ps5a_ring[k + 1] = stereo_samples[2 * i + 1];
    }
    __atomic_store_n(&s_ps5a_wr, wr, __ATOMIC_RELEASE);
}

static int audio_backend_room(void)
{
    if (s_ps5a_port < 0) return -1;
    const u32 queued = __atomic_load_n(&s_ps5a_wr, __ATOMIC_ACQUIRE) - __atomic_load_n(&s_ps5a_rd, __ATOMIC_ACQUIRE);
    return queued < CELL_AUDIO_BLOCK_SAMPLES * 4 ? CELL_AUDIO_BLOCK_SAMPLES : 0;
}

static void audio_backend_wait(void) { usleep(1000); }

static u32 audio_backend_queued_samples(void)
{
    return __atomic_load_n(&s_ps5a_wr, __ATOMIC_ACQUIRE) - __atomic_load_n(&s_ps5a_rd, __ATOMIC_ACQUIRE);
}
#else
static int audio_backend_init(void)
{
    if (SDL_WasInit(SDL_INIT_AUDIO) == 0) {
''', "PS5 audio: sceAudioOut backend")
edit("libs/audio/cellAudio.c", r'''static u32 audio_backend_queued_samples(void)
{
    if (s_sdl_audio_dev) {
        return SDL_GetQueuedAudioSize(s_sdl_audio_dev) / (2 * sizeof(float));
    }
    return 0;
}
''', r'''static u32 audio_backend_queued_samples(void)
{
    if (s_sdl_audio_dev) {
        return SDL_GetQueuedAudioSize(s_sdl_audio_dev) / (2 * sizeof(float));
    }
    return 0;
}
#endif /* __PROSPERO__ */
''', "PS5 audio: end of the SDL functions")

# ---------------------------------------------------------------------------------------------------
# SPIR-V disk cache (PS3RECOMP_SPIRV_CACHE=<dir>). This fork's translator had none, so every session
# translated every guest shader again on the thread walking the FIFO (20-150 ms each: a hitch the
# first time each effect appears, every session). Keyed by FNV-1a 64 of the stage, the FragCoord-w
# switch and the whole HLSL text; a file holds the raw SPIR-V words. SPIR-V is portable, so a cache
# filled on one machine (Linux, where glslang also has its legalization optimizer) serves the PS5.
# ---------------------------------------------------------------------------------------------------
edit("libs/video/rsx_shader_spirv.cpp", r'''extern "C" int rsx_hlsl_to_spirv(const char* hlsl, int stage,
                                 u32* words, u32 max_words, u32* out_words,
                                 char* log, u32 log_size)
{
    if (out_words) *out_words = 0;
    if (!hlsl || !words || !out_words || max_words == 0) {''', r'''static int rsx_hlsl_to_spirv_compile(const char* hlsl, int stage,
                                     u32* words, u32 max_words, u32* out_words,
                                     char* log, u32 log_size);

static unsigned long long spv_cache_key(const char* hlsl, int stage, int rcp)
{
    unsigned long long h = 1469598103934665603ull;
    const unsigned char pre[3] = { (unsigned char)stage, (unsigned char)rcp, 1 /* format */ };
    for (int i = 0; i < 3; i++) { h ^= pre[i]; h *= 1099511628211ull; }
    for (const unsigned char* p = (const unsigned char*)hlsl; *p; p++) { h ^= *p; h *= 1099511628211ull; }
    return h;
}

extern "C" int rsx_hlsl_to_spirv(const char* hlsl, int stage,
                                 u32* words, u32 max_words, u32* out_words,
                                 char* log, u32 log_size)
{
    static const char* dir = (const char*)-1;
    if (dir == (const char*)-1) { dir = getenv("PS3RECOMP_SPIRV_CACHE"); if (dir && !*dir) dir = nullptr; }
    if (!dir || !hlsl || !words || !out_words)
        return rsx_hlsl_to_spirv_compile(hlsl, stage, words, max_words, out_words, log, log_size);
    const char* e = getenv("PS3RECOMP_FRAGCOORD_W");
    const int rcp = (e && *e == 'w') ? 0 : 1;
    char path[1024];
    snprintf(path, sizeof path, "%s/%016llx.spv", dir, spv_cache_key(hlsl, stage, rcp));
    if (FILE* f = fopen(path, "rb")) {
        const size_t n = fread(words, sizeof(u32), max_words, f);
        fclose(f);
        if (n > 5 && words[0] == 0x07230203u) { *out_words = (u32)n; return 0; }
    }
    const int rc = rsx_hlsl_to_spirv_compile(hlsl, stage, words, max_words, out_words, log, log_size);
    if (rc == 0 && *out_words) {
        char tmp[1100];
        snprintf(tmp, sizeof tmp, "%s.%d.tmp", path, (int)getpid());
        if (FILE* f = fopen(tmp, "wb")) {
            const bool ok = fwrite(words, sizeof(u32), *out_words, f) == *out_words;
            fclose(f);
            if (!ok || rename(tmp, path) != 0) remove(tmp);
        }
    }
    return rc;
}

static int rsx_hlsl_to_spirv_compile(const char* hlsl, int stage,
                                     u32* words, u32 max_words, u32* out_words,
                                     char* log, u32 log_size)
{
    if (out_words) *out_words = 0;
    if (!hlsl || !words || !out_words || max_words == 0) {''', "SPIR-V disk cache")
edit("libs/video/rsx_shader_spirv.cpp", r'''#include <vector>
''', r'''#include <vector>
#include <unistd.h>
''', "SPIR-V disk cache: getpid")

# ---------------------------------------------------------------------------------------------------
# cellPad press latch (as inFAMOUSreborn's runtime has it, 2026-10-04): every button seen down by any
# host poll since the guest's last delivered packet is part of the next packet. inFamous reads the
# pad once per frame, so at a low frame rate a press that starts and ends between two reads was
# never seen ("Press the Start Button" ignored; seen here on the slow PC test renderer, and it can
# happen on the console whenever the frame rate dips). Consumed only when a packet is delivered.
# ---------------------------------------------------------------------------------------------------
edit("libs/input/cellPad.c", r'''/* Per-port "a report has arrived since your last read" flag; see cellPadGetData. */
static int s_data_fresh[PAD_MAX_HOST_PORTS];
''', r'''/* Per-port "a report has arrived since your last read" flag; see cellPadGetData. */
static int s_data_fresh[PAD_MAX_HOST_PORTS];
/* Press latch: buttons seen down since the last delivered packet (see cellPadGetData). */
static volatile long s_latch[PAD_MAX_HOST_PORTS];
''', "pad latch: state")
edit("libs/input/cellPad.c", r'''    pad_track_assign();
''', r'''    pad_track_assign();
    for (int _i = 0; _i < PAD_MAX_HOST_PORTS; _i++)
        if (s_host_state[_i].buttons) __sync_fetch_and_or(&s_latch[_i], (long)s_host_state[_i].buttons);
''', "pad latch: collect")
edit("libs/input/cellPad.c", r'''    data->button[CELL_PAD_BTN_OFFSET_DIGITAL1] = (u16)(hs->buttons & 0xFF);
    data->button[CELL_PAD_BTN_OFFSET_DIGITAL2] = (u16)((hs->buttons >> 8) & 0xFF);
''', r'''    const u16 eff_btns = (u16)(hs->buttons | (port_no < PAD_MAX_HOST_PORTS ? (u16)s_latch[port_no] : 0));
    data->button[CELL_PAD_BTN_OFFSET_DIGITAL1] = (u16)(eff_btns & 0xFF);
    data->button[CELL_PAD_BTN_OFFSET_DIGITAL2] = (u16)((eff_btns >> 8) & 0xFF);
''', "pad latch: deliver")
edit("libs/input/cellPad.c", r'''        if (!always && port_no < PAD_MAX_HOST_PORTS && data->len) {
            if (!s_data_fresh[port_no]) data->len = 0;   /* nothing new: end the drain */
            else                        s_data_fresh[port_no] = 0;
        }
''', r'''        if (!always && port_no < PAD_MAX_HOST_PORTS && data->len) {
            if (!s_data_fresh[port_no]) data->len = 0;   /* nothing new: end the drain */
            else                        s_data_fresh[port_no] = 0;
        }
        if (port_no < PAD_MAX_HOST_PORTS && data->len) (void)__sync_lock_test_and_set(&s_latch[port_no], 0);
''', "pad latch: consume")

# SPU_IRQ_PC_MAX=<LS addr>: hold a pending SPU interrupt while the SPU runs code at or above this
# address, and deliver it once it is back below. inFamous 1's WWS job manager (policy module at LS
# 0xA00..0x3680) takes its list stall-and-notify interrupt; taken in the middle of a lifted job
# (srr0 0x18058) the iret came back wrong, the job ran into code it had not loaded (LS 0x18BB0),
# the SPU stopped, SPURS aborted and the RSX waited on that job's command buffer every frame.
# inFamous 2 only ever takes it inside the policy module. Unset = every pc, as before.
edit("runtime/spu/spu_drain.c", r'''    /* Stall-and-notify still settling: let the SPU run on (see above). */
    if (ctx->sn_defer) {
        ctx->sn_defer--;
        return tf;
    }
''', r'''    /* Stall-and-notify still settling: let the SPU run on (see above). */
    if (ctx->sn_defer) {
        ctx->sn_defer--;
        return tf;
    }
    { static _Atomic long s_pcmax = -2;
      if (s_pcmax == -2) { const char* e = getenv("SPU_IRQ_PC_MAX"); s_pcmax = e ? strtol(e, 0, 0) : -1; }
      if (s_pcmax > 0 && (long)(ctx->pc & SPU_LS_MASK) >= s_pcmax) {
          static int _n = 0;
          if (PS3_LOG_FIRST(_n, 8))
              fprintf(stderr, "[spu-int] held at pc=0x%05X (SPU_IRQ_PC_MAX=0x%lX)\n",
                      ctx->pc & SPU_LS_MASK, s_pcmax);
          return tf;
      } }
''', "spu irq: pc max")

# SPU_OVL_CLEAR_AT=<LS addr>: a GET of a job module (>= 512 bytes) to this address whose header
# matches no registered signature clears the resident overlay. Without it the previous job's lift
# stays "resident", and an interpreted job that is not lifted rejoins that lift wherever the two
# share a function address: inFamous 1's job entered at LS 0x18BB0 (module EA ~0x6B3880, not among
# the lifted ones) ran into image 215's function at 0x18BEC, the SPU stopped, SPURS aborted and the
# RSX waited every frame on the command buffer that job should have written.
edit("runtime/spu/spu_channels.c", r'''            ctx->resident_code[slot].image_id = 0;
            ctx->ib_gen++;
        }
    }
    if (ovl_cannot_match(ea, ls, lsa, size)) return;
''', r'''            ctx->resident_code[slot].image_id = 0;
            ctx->ib_gen++;
        }
    }
    { static _Atomic long s_at = -2;
      if (s_at == -2) { const char* e = getenv("SPU_OVL_CLEAR_AT"); s_at = e ? strtol(e, 0, 0) : -1; }
      if (s_at >= 0 && lsa == (uint32_t)s_at && size >= 512 && ctx->resident_ovl) {
          extern int spu_overlay_match_sig(const uint8_t hdr[16]);
          if (!spu_overlay_match_sig(ls)) {
              static int _n = 0;
              if (PS3_LOG_FIRST(_n, 8))
                  fprintf(stderr, "[spu-ovl] img=%d unlifted module ea=0x%08X -> LS 0x%05X: overlay %d no longer resident\n",
                          ctx->image_id, ea, lsa, ctx->resident_ovl);
              ctx->resident_ovl = 0;
              ctx->ib_gen++;
          } } }
    if (ovl_cannot_match(ea, ls, lsa, size)) return;
''', "spu ovl: clear on unmatched module")

# SPU_REJOIN_WHO=<LS pc>: when the interpreter rejoins lifted code at this pc, say who owns it
# (primary image, resident overlay, resident code slots) and the module header at LS 0x4000.
edit("runtime/spu/spu_interp.c", r'''            spu_xfer_log(ctx, "rejoin", g_spu_interp_last_pc, ctx->pc);
''', r'''            { static _Atomic long s_who = -2;
              if (s_who == -2) { const char* e = getenv("SPU_REJOIN_WHO"); s_who = e ? strtol(e, 0, 0) : -1; }
              static _Atomic int s_whon = 0;
              if (s_who >= 0 && ((long)(ctx->pc & SPU_LS_MASK) == s_who || (long)(start_lsa & SPU_LS_MASK) == s_who) &&
                  s_whon++ < 24) {
                  extern void* spu_lookup(uint32_t, int);
                  fprintf(stderr, "[rejoin-who] pc=0x%05X from 0x%05X img=%d (own %d) ovl=%d (own %d) slots:",
                          ctx->pc & SPU_LS_MASK, start_lsa & SPU_LS_MASK, ctx->image_id,
                          spu_lookup(ctx->pc, ctx->image_id) != 0, ctx->resident_ovl,
                          ctx->resident_ovl ? spu_lookup(ctx->pc, ctx->resident_ovl) != 0 : 0);
                  for (unsigned s = 0; s < SPU_RESIDENT_CODE_SLOTS; s++)
                      if (ctx->resident_code[s].image_id)
                          fprintf(stderr, " [%u] img %d LS 0x%05X+0x%X", s, ctx->resident_code[s].image_id,
                                  ctx->resident_code[s].lsa, ctx->resident_code[s].size);
                  fprintf(stderr, " LS[4000]=%08X %08X %08X %08X\n", interp_ls_w(ctx, 0x4000),
                          interp_ls_w(ctx, 0x4004), interp_ls_w(ctx, 0x4008), interp_ls_w(ctx, 0x400C));
              } }
            spu_xfer_log(ctx, "rejoin", g_spu_interp_last_pc, ctx->pc);
''', "spu rejoin: who")

# SPU_INTERP_CONTINUE=1: after interpreting an unlifted target below the stub area, keep going at
# the pc the interpreter rejoined (as the stub-microstep path above already does) instead of
# returning. Returning to the depth-0 driver ended the SPU thread: inFamous 1's job module image 4
# (EA 0x6B3880) enters at LS 0x18BB0, which its lift lacks; the interpreter ran it to 0x18BEC (a
# lifted entry) and the SPU stopped there, SPURS aborted, and the RSX waited on that job's
# command buffer every frame (0.1 fps from the title on).
edit("runtime/spu/spu_channels.c", r'''              spu_interp_run(ctx, p);
              return;
          } }
        spu_halt(ctx);
        return;
''', r'''              spu_interp_run(ctx, p);
              { static _Atomic int s_ic = -1;
                if (s_ic < 0) s_ic = getenv("SPU_INTERP_CONTINUE") ? 1 : 0;
                if (s_ic) {
                    spu_stop_exit_check(ctx);
                    if (g_spu_trampoline_fn || ctx->status != SPU_STATUS_RUNNING ||
                        (ctx->drain_ret_pc && ctx->pc == ctx->drain_ret_pc))
                        return;
                    { static int _n = 0;
                      if (PS3_LOG_FIRST(_n, 8))
                          fprintf(stderr, "[spu] img=%d interpreted 0x%05X, continuing at lifted 0x%05X (depth %u)\n",
                                  ctx->image_id, p, ctx->pc & SPU_LS_MASK, ctx->host_depth); }
#if defined(__clang__)
                    __attribute__((musttail)) return spu_indirect_branch(ctx);
#else
                    spu_indirect_branch(ctx);
                    return;
#endif
                } }
              return;
          } }
        spu_halt(ctx);
        return;
''', "spu interp: continue at rejoin")

# PAD_TRACE=1: once a second, per port, how many reads the title made, how many carried a packet
# (len > 0) and the buttons it was handed -- for a title that ignores scripted presses.
edit("libs/input/cellPad.c", r'''        if (port_no < PAD_MAX_HOST_PORTS && data->len) (void)__sync_lock_test_and_set(&s_latch[port_no], 0);
    }
''', r'''        if (port_no < PAD_MAX_HOST_PORTS && data->len) (void)__sync_lock_test_and_set(&s_latch[port_no], 0);
    }
    { static int tr = -1; static unsigned long long t_last; static unsigned calls[8], pkts[8], btn_or[8];
      if (tr < 0) tr = getenv("PAD_TRACE") ? 1 : 0;
      if (tr && port_no < 8) {
          calls[port_no]++;
          if (data->len) pkts[port_no]++, btn_or[port_no] |=(unsigned)data->button[CELL_PAD_BTN_OFFSET_DIGITAL1] | ((unsigned)data->button[CELL_PAD_BTN_OFFSET_DIGITAL2] << 8);
          unsigned long long now = GetTickCount64();
          if (now - t_last >= 1000) { t_last = now;
              for (int p = 0; p < 8; p++) if (calls[p]) {
                  printf("[cellPad] trace port %d: %u reads, %u packets, buttons seen 0x%04X\n", p, calls[p], pkts[p], btn_or[p]);
                  calls[p] = pkts[p] = btn_or[p] = 0; }
              fflush(stdout); } } }
''', "pad trace")

# Fragment decompiler: the register files were declared r[48] / h[48], but a register index is a
# 6-bit field and programs use half registers past 47 (Festival of Blood: h[54] -> glslang "array
# index out of range '54'", the pipeline was dropped). 64 entries each cover every encodable index.
edit("libs/video/rsx_fp_decompiler.c", r'''        "    float4 r[48]; float4 h[48];\n"''', r'''        "    float4 r[64]; float4 h[64];\n"''', "fp regs: 64 (decl)")
edit("libs/video/rsx_fp_decompiler.c", r'''        "    [unroll] for (int _i = 0; _i < 48; _i++) { r[_i] = (float4)0; h[_i] = (float4)0; }\n"''',
     r'''        "    [unroll] for (int _i = 0; _i < 64; _i++) { r[_i] = (float4)0; h[_i] = (float4)0; }\n"''', "fp regs: 64 (init)")

# VK_GARBAGE_LOG=1: whenever a batch frees more buffers/images than any batch before it, say how many
# (each depth snapshot leaves a w*h*4 host staging buffer alive until the batch is submitted).
edit("libs/video/rsx_vulkan_backend.c", r'''static void vk_batch_after_flush(void)
{
''', r'''static void vk_batch_after_flush(void)
{
    { static int lg = -1; static u32 hb, hi;
      if (lg < 0) lg = getenv("VK_GARBAGE_LOG") ? 1 : 0;
      if (lg && (s_ngbuf > hb || s_ngimg > hi)) {
          if (s_ngbuf > hb) hb = s_ngbuf;
          if (s_ngimg > hi) hi = s_ngimg;
          VK_LOG("batch garbage high-water: %u buffers, %u images\n", hb, hi); } }
''', "vk garbage log")
edit("libs/video/rsx_vulkan_backend.c", r'''          VK_LOG("batch garbage high-water: %u buffers, %u images\n", hb, hi); } }
''', r'''          VkDeviceSize by = 0; for (u32 i = 0; i < s_ngbuf; i++) by += s_gbuf[i].size;
          VK_LOG("batch garbage high-water: %u buffers, %u images (this batch: %u buffers, %llu MB)\n",
                 hb, hi, s_ngbuf, (unsigned long long)(by >> 20)); } }
''', "vk garbage log: bytes")

# PS3_THREAD_TRACE=1: a guest thread's last host steps before its first guest instruction (the
# console runs died silently between "host thread started" and the thread's first syscall).
edit("runtime/syscalls/sys_ppu_thread.c", r'''    if (g_ppu_thread_entry_trampoline) {
        s_exit_armed = 1;
        if (setjmp(s_exit_jmp) == 0)
            g_ppu_thread_entry_trampoline(&info->ctx);
        else''', r'''    if (g_ppu_thread_entry_trampoline) {
        static int s_tt = -1;
        if (s_tt < 0) s_tt = getenv("PS3_THREAD_TRACE") ? 1 : 0;
        s_exit_armed = 1;
        if (s_tt) fprintf(stderr, "[THREAD %llu] setjmp (jmp_buf at %p)\n",
                          (unsigned long long)info->ctx.thread_id, (void*)&s_exit_jmp);
        if (setjmp(s_exit_jmp) == 0) {
            if (s_tt) fprintf(stderr, "[THREAD %llu] entering guest code at 0x%08llX (r1 0x%08llX, toc 0x%08llX)\n",
                              (unsigned long long)info->ctx.thread_id, (unsigned long long)info->entry_addr,
                              (unsigned long long)info->ctx.gpr[1], (unsigned long long)info->ctx.gpr[2]);
            g_ppu_thread_entry_trampoline(&info->ctx);
        }
        else''', "thread trace")

# PS3_THREAD_TRACE=1 also traces each step of a guest thread's first event-queue wait (the console
# runs ended as SpursHdlr1 made its first receive).
edit("runtime/syscalls/sys_event.c", r'''    pthread_mutex_lock(&q->lock);

    if (timeout_us == 0) {
''', r'''    static int s_rt = -1;
    if (s_rt < 0) s_rt = getenv("PS3_THREAD_TRACE") ? 1 : 0;
    static _Atomic int s_rt_n;
    const int rt = s_rt && s_rt_n++ < 16;
    if (rt) fprintf(stderr, "[evt-trace] tid=%llu q=%u timeout=%llu: lock %p\n",
                    (unsigned long long)ctx->thread_id, queue_id, (unsigned long long)timeout_us, (void*)&q->lock);
    pthread_mutex_lock(&q->lock);
    if (rt) fprintf(stderr, "[evt-trace] tid=%llu q=%u: locked, count=%u active=%d cancelled=%d, waiting on %p\n",
                    (unsigned long long)ctx->thread_id, queue_id, (unsigned)q->count, (int)q->active,
                    (int)q->cancelled, (void*)&q->not_empty);

    if (timeout_us == 0) {
''', "evt receive trace")

# PS5: statvfs on the app folder gives no usable answer, so cellGame reported 0 KB free and
# inFamous (1) stopped at "Insufficient hard disk space. An additional 1358 MB is needed" (the
# tenth console run, a black screen: the dialog is not drawn). Report the large value the other
# hosts get above 4 GiB; the console's SSD has the room.
edit("libs/system/cellGame.c", r'''static s32 content_free_kb(void)
{
    const s32 kb = content_free_kb_raw();
''', r'''static s32 content_free_kb(void)
{
#ifdef __PROSPERO__
    return 40 * 1024 * 1024 - 256;
#endif
    const s32 kb = content_free_kb_raw();
''', "ps5 game free space")

# SPU single-precision fa/fs/fm/fma/fms/fnms on x86 with AVX2 (the PS5's Zen 2 and any PC since
# 2013): the NEON fast path's method, four lanes as one f64x4 -- widen (exact), operate, clear the
# 29 low significand bits, narrow (exact) -- with the same per-lane tests and the same exact
# fix-up for the lanes that fail them. Without it every x86 build ran each lane through the
# integer emulation (spu__sf_sum, 128-bit arithmetic): the busiest SPU thread of an inFamous 2
# world frame spent ~25% in spu_fm / spu__fma_any / spu_fa / spu_fs / spu__sf_sum (perf, Linux),
# and that one SPU was 75% of the frame (PS3_FTRACE). tests: tools/test_spu_float_avx2.c.
edit("runtime/spu/spu_helpers.h", r'''#else
static inline u128 spu_fa(u128 a, u128 b) { return spu__fa_s(a, b); }''', r'''#elif defined(__AVX2__) && !defined(SPU_SCALAR_HELPERS)
#include <immintrin.h>
#define SPU_FLOAT_AVX2 1
#pragma clang fp contract(off)
#define SPU__XV_INLINE static inline __attribute__((always_inline))
#define SPU__XV_SLOW   static inline __attribute__((noinline, cold))
SPU__XV_INLINE __m128i spu__xv_ld(u128 v) { __m128i r; memcpy(&r, &v, 16); return r; }
SPU__XV_INLINE u128 spu__xv_st(__m128i v) { u128 r; memcpy(&r, &v, 16); return r; }
SPU__XV_INLINE __m128i spu__xv_bexp(__m128i x) { return _mm_srli_epi32(_mm_slli_epi32(x, 1), 24); }
SPU__XV_INLINE __m128i spu__xv_iszero(__m128i x) {   /* +-0.0 */
    return _mm_cmpeq_epi32(_mm_slli_epi32(x, 1), _mm_setzero_si128());
}
/* An ordinary single (biased exponent 1..254) or a true zero, as spu__nv_plain0. */
SPU__XV_INLINE __m128i spu__xv_plain0(__m128i x) {
    const __m128i be = spu__xv_bexp(x);
    const __m128i plain = _mm_and_si128(_mm_cmpgt_epi32(be, _mm_setzero_si128()),
                                        _mm_cmpgt_epi32(_mm_set1_epi32(255), be));
    return _mm_or_si128(plain, spu__xv_iszero(x));
}
SPU__XV_INLINE __m256d spu__xv_wide(__m128i x) { return _mm256_cvtps_pd(_mm_castsi128_ps(x)); }
/* spu__nv_trunc0 on four doubles: *ok marks the lanes whose result is a normal single or an exact
 * zero (and, with err, not both rounded and on a 24-bit boundary); *zm the zero lanes. */
SPU__XV_INLINE __m128i spu__xv_trunc0(__m256d d, __m128i* ok, __m128i* zm, const __m256d* err) {
    const __m256i u = _mm256_castpd_si256(d);
    const __m256i z64 = _mm256_setzero_si256();
    const __m256i az = _mm256_cmpeq_epi64(_mm256_slli_epi64(u, 1), z64);
    const __m256i e = _mm256_sub_epi64(_mm256_and_si256(_mm256_srli_epi64(u, 52), _mm256_set1_epi64x(0x7FF)),
                                       _mm256_set1_epi64x(1023));
    __m256i good = _mm256_and_si256(_mm256_cmpgt_epi64(e, _mm256_set1_epi64x(-127)),
                                    _mm256_cmpgt_epi64(_mm256_set1_epi64x(128), e));
    if (err) {
        const __m256i lowz = _mm256_cmpeq_epi64(_mm256_and_si256(u, _mm256_set1_epi64x(0x1FFFFFFFll)), z64);
        const __m256i errz = _mm256_castpd_si256(_mm256_cmp_pd(*err, _mm256_setzero_pd(), _CMP_EQ_OQ));
        good = _mm256_and_si256(good, _mm256_or_si256(_mm256_xor_si256(lowz, _mm256_set1_epi64x(-1)), errz));
    }
    const __m256i lo32 = _mm256_setr_epi32(0, 2, 4, 6, 0, 2, 4, 6);
    *ok = _mm256_castsi256_si128(_mm256_permutevar8x32_epi32(_mm256_or_si256(good, az), lo32));
    *zm = _mm256_castsi256_si128(_mm256_permutevar8x32_epi32(az, lo32));
    const __m256d t = _mm256_castsi256_pd(_mm256_and_si256(u, _mm256_set1_epi64x(~0x1FFFFFFFll)));
    return _mm_castps_si128(_mm256_cvtpd_ps(t));
}
SPU__XV_INLINE __m128i spu__xv_pos0(__m128i r, __m128i zm) {   /* the SPU never returns -0 */
    return _mm_andnot_si128(_mm_and_si128(zm, _mm_set1_epi32((int)0x80000000u)), r);
}
SPU__XV_INLINE int spu__xv_all4(__m128i m) { return _mm_movemask_ps(_mm_castsi128_ps(m)) == 0xF; }
SPU__XV_SLOW __m128i spu__xv_fa_fix(__m128i r, __m128i ok, __m128i a, __m128i b, uint32_t negb) {
    uint32_t o[4], m[4], x[4], y[4];
    memcpy(o, &r, 16); memcpy(m, &ok, 16); memcpy(x, &a, 16); memcpy(y, &b, 16);
    for (int i = 0; i < 4; i++) if (!m[i]) o[i] = spu__fa_any(x[i], y[i] ^ negb);
    __m128i v; memcpy(&v, o, 16); return v;
}
SPU__XV_SLOW __m128i spu__xv_fm_fix(__m128i r, __m128i ok, __m128i a, __m128i b) {
    uint32_t o[4], m[4], x[4], y[4];
    memcpy(o, &r, 16); memcpy(m, &ok, 16); memcpy(x, &a, 16); memcpy(y, &b, 16);
    for (int i = 0; i < 4; i++) if (!m[i]) o[i] = spu__fm_any(x[i], y[i]);
    __m128i v; memcpy(&v, o, 16); return v;
}
SPU__XV_SLOW __m128i spu__xv_fma_fix(__m128i r, __m128i ok, __m128i a, __m128i b, __m128i c,
                                     uint32_t negp, uint32_t negc) {
    uint32_t o[4], m[4], x[4], y[4], z[4];
    memcpy(o, &r, 16); memcpy(m, &ok, 16); memcpy(x, &a, 16); memcpy(y, &b, 16); memcpy(z, &c, 16);
    for (int i = 0; i < 4; i++) if (!m[i]) o[i] = spu__fma_any(x[i], y[i], z[i], negp, negc);
    __m128i v; memcpy(&v, o, 16); return v;
}
SPU__XV_INLINE u128 spu__xv_fa(u128 a, u128 b, uint32_t negb) {
    const __m128i xa = spu__xv_ld(a), yb = spu__xv_ld(b);
    const __m128i x = xa, y = _mm_xor_si128(yb, _mm_set1_epi32((int)negb));
    const __m128i gap = _mm_abs_epi32(_mm_sub_epi32(spu__xv_bexp(x), spu__xv_bexp(y)));
    const __m128i pre = _mm_and_si128(_mm_and_si128(spu__xv_plain0(x), spu__xv_plain0(y)),
                                      _mm_or_si128(_mm_cmpgt_epi32(_mm_set1_epi32(30), gap),
                                                   _mm_or_si128(spu__xv_iszero(x), spu__xv_iszero(y))));
    __m128i ok, zm;
    __m128i r = spu__xv_trunc0(_mm256_add_pd(spu__xv_wide(x), spu__xv_wide(y)), &ok, &zm, NULL);
    ok = _mm_and_si128(ok, pre);
    r = spu__xv_pos0(r, zm);
    if (!spu__xv_all4(ok)) r = spu__xv_fa_fix(r, ok, xa, yb, negb);
    return spu__xv_st(r);
}
SPU__XV_INLINE u128 spu_fa(u128 a, u128 b) { return spu__xv_fa(a, b, 0); }
SPU__XV_INLINE u128 spu_fs(u128 a, u128 b) { return spu__xv_fa(a, b, 0x80000000u); }
SPU__XV_INLINE u128 spu_fm(u128 a, u128 b) {
    const __m128i x = spu__xv_ld(a), y = spu__xv_ld(b);
    __m128i ok, zm;
    __m128i r = spu__xv_trunc0(_mm256_mul_pd(spu__xv_wide(x), spu__xv_wide(y)), &ok, &zm, NULL);
    ok = _mm_and_si128(ok, _mm_and_si128(spu__xv_plain0(x), spu__xv_plain0(y)));
    r = spu__xv_pos0(r, zm);
    if (!spu__xv_all4(ok)) r = spu__xv_fm_fix(r, ok, x, y);
    return spu__xv_st(r);
}
/* (+-a*b) + (+-c): the product is exact in double, one rounding in the add, TwoSum says whether. */
SPU__XV_INLINE u128 spu__xv_fma(u128 a, u128 b, u128 c, uint32_t negp, uint32_t negc) {
    const __m128i xa = spu__xv_ld(a), y = spu__xv_ld(b), zc = spu__xv_ld(c);
    const __m128i x = _mm_xor_si128(xa, _mm_set1_epi32((int)negp)), z = _mm_xor_si128(zc, _mm_set1_epi32((int)negc));
    const __m256d p = _mm256_mul_pd(spu__xv_wide(x), spu__xv_wide(y)), zd = spu__xv_wide(z);
    const __m256d s = _mm256_add_pd(p, zd), bb = _mm256_sub_pd(s, p);
    const __m256d err = _mm256_add_pd(_mm256_sub_pd(p, _mm256_sub_pd(s, bb)), _mm256_sub_pd(zd, bb));
    __m128i ok, zm;
    __m128i r = spu__xv_trunc0(s, &ok, &zm, &err);
    ok = _mm_and_si128(ok, _mm_and_si128(_mm_and_si128(spu__xv_plain0(x), spu__xv_plain0(y)), spu__xv_plain0(z)));
    r = spu__xv_pos0(r, zm);
    if (!spu__xv_all4(ok)) r = spu__xv_fma_fix(r, ok, xa, y, zc, negp, negc);
    return spu__xv_st(r);
}
SPU__XV_INLINE u128 spu_fma(u128 a, u128 b, u128 c)  { return spu__xv_fma(a, b, c, 0, 0); }
SPU__XV_INLINE u128 spu_fms(u128 a, u128 b, u128 c)  { return spu__xv_fma(a, b, c, 0, 0x80000000u); }
SPU__XV_INLINE u128 spu_fnms(u128 a, u128 b, u128 c) { return spu__xv_fma(a, b, c, 0x80000000u, 0); }
#pragma clang fp contract(on)
#else
static inline u128 spu_fa(u128 a, u128 b) { return spu__fa_s(a, b); }''', "spu float avx2")

# SPU quadword byte shifts/rotates (shlqby[i|bi], rotqby[i|bi], rotqmby[i|bi]) and cwd on x86 with
# SSSE3: one pshufb, the index computed per host byte as the NEON forms compute it per SPU byte.
# SPU byte P lives at host byte P^3, so host byte h takes SPU byte s = f(h^3) from host byte s^3;
# an index with the top bit set gives 0 (shifted-out bytes). Without it each was a 16-step byte
# loop with a branch per byte (perf: the hottest lines of the busiest inFamous 2 SPU job).
# tests: tools/test_spu_bytes_sse.c.
SPU_X86_BYTES = r'''
#if defined(__SSSE3__) && !defined(__ARM_NEON) && !defined(SPU_SCALAR_HELPERS) && !defined(SPU_SCALAR_INT)
#include <tmmintrin.h>
#define SPU_BYTES_SSSE3 1
/* host byte h -> the SPU byte index it holds (h ^ 3) */
static inline __m128i spu__xb_iota(void) { return _mm_setr_epi8(3,2,1,0, 7,6,5,4, 11,10,9,8, 15,14,13,12); }
static inline u128 spu__xb_perm(u128 a, __m128i s) {   /* s: SPU source byte per host byte; <0 or >15 -> 0 */
    const __m128i oor = _mm_or_si128(_mm_cmpgt_epi8(s, _mm_set1_epi8(15)), _mm_cmplt_epi8(s, _mm_setzero_si128()));
    const __m128i h = _mm_or_si128(_mm_xor_si128(s, _mm_set1_epi8(3)), _mm_and_si128(oor, _mm_set1_epi8((char)0x80)));
    __m128i A; memcpy(&A, &a, 16);
    const __m128i r = _mm_shuffle_epi8(A, h);
    u128 o; memcpy(&o, &r, 16); return o;
}
static inline u128 spu__xb_shl(u128 a, int sh) {        /* SPU byte i <- byte i+sh, 0 past the end */
    return spu__xb_perm(a, _mm_add_epi8(spu__xb_iota(), _mm_set1_epi8((char)(sh & 0x1F))));
}
static inline u128 spu__xb_rot(u128 a, int sh) {        /* SPU byte i <- byte (i+sh) & 15 */
    return spu__xb_perm(a, _mm_and_si128(_mm_add_epi8(spu__xb_iota(), _mm_set1_epi8((char)(sh & 0x0F))), _mm_set1_epi8(15)));
}
static inline u128 spu__xb_shr(u128 a, int sh) {        /* SPU byte i <- byte i-sh, 0 before the start */
    return spu__xb_perm(a, _mm_sub_epi8(spu__xb_iota(), _mm_set1_epi8((char)(sh & 0x1F))));
}
#endif
'''
edit("runtime/spu/spu_helpers.h", r'''static inline u128 spu_shlqbyi_ref(u128 a, int sh) {''', SPU_X86_BYTES + r'''static inline u128 spu_shlqbyi_ref(u128 a, int sh) {''', "spu bytes ssse3: base")
for name, args, call, body in [
    ("spu_shlqbyi",  "u128 a, int sh",  "spu_shlqbyi_ref(a, sh)",  "spu__xb_shl(a, sh)"),
    ("spu_rotqbyi",  "u128 a, int sh",  "spu_rotqbyi_ref(a, sh)",  "spu__xb_rot(a, sh)"),
    ("spu_shlqby",   "u128 a, u128 b",  "spu_shlqby_ref(a, b)",    "spu__xb_shl(a, (int)(b._u32[0] & 0x1F))"),
    ("spu_rotqby",   "u128 a, u128 b",  "spu_rotqby_ref(a, b)",    "spu__xb_rot(a, (int)b._u32[0])"),
    ("spu_shlqbybi", "u128 a, u128 b",  "spu_shlqbybi_ref(a, b)",  "spu__xb_shl(a, (int)((b._u32[0] >> 3) & 0x1F))"),
    ("spu_rotqbybi", "u128 a, u128 b",  "spu_rotqbybi_ref(a, b)",  "spu__xb_rot(a, (int)(b._u32[0] >> 3))"),
    ("spu_rotqmby",  "u128 a, u128 b",  "spu_rotqmby_ref(a, b)",   "spu__xb_shr(a, (0 - (int)b._u32[0]) & 0x1F)"),
    ("spu_rotqmbybi","u128 a, u128 b",  "spu_rotqmbybi_ref(a, b)", "spu__xb_shr(a, (0 - ((int)b._u32[0] >> 3)) & 0x1F)"),
    ("spu_rotqmbyi", "u128 a, int i7",  "spu_rotqmbyi_ref(a, i7)", "spu__xb_shr(a, (0 - i7) & 0x1F)"),
]:
    old = "#else\nstatic inline u128 %s(%s) { return %s; }\n#endif" % (name, args, call)
    new = ("#elif defined(SPU_BYTES_SSSE3)\nstatic inline u128 %s(%s) { return %s; }\n" % (name, args, body)
           + "#else\nstatic inline u128 %s(%s) { return %s; }\n#endif" % (name, args, call))
    edit("runtime/spu/spu_helpers.h", old, new, "spu bytes ssse3: " + name)
edit("runtime/spu/spu_helpers.h",
     "#else\nstatic inline u128 spu_cwd(u128 a, int i7) { return spu_cwd_ref(a, i7); }\n#endif",
     "#elif defined(SPU_BYTES_SSSE3)\n"
     "static inline u128 spu_cwd(u128 a, int i7) {   /* the word slot ((a+i7)>>2)&3 takes 00010203 */\n"
     "    const __m128i m = _mm_cmpeq_epi32(_mm_setr_epi32(0, 1, 2, 3), _mm_set1_epi32((int)((((uint32_t)a._u32[0] + (uint32_t)i7) >> 2) & 3)));\n"
     "    const __m128i base = _mm_setr_epi32(0x10111213, 0x14151617, 0x18191A1B, 0x1C1D1E1F);\n"
     "    const __m128i r = _mm_or_si128(_mm_and_si128(m, _mm_set1_epi32(0x00010203)), _mm_andnot_si128(m, base));\n"
     "    u128 o; memcpy(&o, &r, 16); return o;\n"
     "}\n"
     "#else\nstatic inline u128 spu_cwd(u128 a, int i7) { return spu_cwd_ref(a, i7); }\n#endif",
     "spu bytes ssse3: spu_cwd")

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

# A blocked SPU channel read re-checks its predicate every PS3_SPU_CHWAIT_MS (default 1, was a fixed
# 10): the lost-reservation event is polled (spu_resv_lost_poll: "the ceiling is one poll of wake
# latency"), so a writer the store hooks miss cost up to 10 ms per SPURS handoff. One 128-byte
# compare per millisecond per blocked SPU.
edit("runtime/spu/spu_channels.c",
     '''                SleepConditionVariableSRW((CONDITION_VARIABLE*)&ctx->ch_wait_cv,
                                          (SRWLOCK*)&ctx->ch_wait_lock, 10, 0);''',
     '''                SleepConditionVariableSRW((CONDITION_VARIABLE*)&ctx->ch_wait_cv,
                                          (SRWLOCK*)&ctx->ch_wait_lock, spu_chwait_ms(), 0);''',
     "spu chwait: poll")
edit("runtime/spu/spu_channels.c",
     '''/* Block the calling SPU host thread until `channel` is readable. */
static void spu_ch_wait(''',
     '''static unsigned spu_chwait_ms(void)
{
    static _Atomic int ms = -1;
    if (ms < 0) { const char* e = getenv("PS3_SPU_CHWAIT_MS"); ms = e && atoi(e) > 0 ? atoi(e) : 1; }
    return (unsigned)ms;
}

/* Block the calling SPU host thread until `channel` is readable. */
static void spu_ch_wait(''',
     "spu chwait: knob")

# rsx_draw_backend.light_pass on Vulkan: inFAMOUS 2's SPU light job on the GPU, as the Metal backend
# does it (rsx_metal_backend.m eng_light_fs, ported line for line to HLSL). One full-screen triangle
# through the engine's own pipeline / target / texture / constant path into two persistent RGBA8
# targets (diffuse, specular), recorded in the batch like any engine draw; the engine's bound state
# and constant bytes are saved before and restored after. Without it the engine wrote the normals
# and depth back to guest memory every frame for the SPU job (a GPU sync and 7 MB each), the job
# lit 32x40 tiles on the SPUs, and every tile DMA went through the overlay checks.
VK_LIGHT = r'''
/* ---- E5: the GPU light pass (PS3RECOMP_ENG_GPU_LIGHT) --------------------- */
static const char* const s_lp_vs =
    "struct VSInput { float4 a0:ATTR0; };\n"
    "struct VSOutput { float4 pos:SV_Position; };\n"
    "VSOutput main(VSInput input) { VSOutput o; o.pos = input.a0; return o; }\n";
static const char* const s_lp_ps =
    "Texture2D    rsx_tex[16] : register(t0);\n"
    "SamplerState rsx_samp[16] : register(s0);\n"
    "struct GLight { float4 pos_type; float4 col_inner; float4 oacbn; float4 dir; };\n"
    "cbuffer PSConstants : register(b1) { float4 gl_m[4]; float4 gl_misc; GLight gl_l[128]; };\n"
    "struct PSInput { float4 pos:SV_Position; };\n"
    "struct PSOutput { float4 t0:SV_TARGET0; float4 t1:SV_TARGET1; };\n"
    "PSOutput main(PSInput input) {\n"
    "    int2 px = int2(input.pos.xy);\n"
    "    PSOutput o; o.t0 = float4(0.0, 0.0, 0.0, 0.0); o.t1 = float4(0.0, 0.0, 0.0, 0.0);\n"
    "    uint z24 = (uint)(saturate(rsx_tex[1].Load(int3(px, 0)).x) * 16777215.0);\n"
    "    if (z24 >= 0xFFFFFFu) return o;\n"
    "    float zf = (float)z24 / 16777216.0;\n"
    "    float u = (float)px.x / gl_misc.z, v = (float)px.y / gl_misc.w;\n"
    "    float4 h = u * gl_m[0] + v * gl_m[1] + zf * gl_m[2] + gl_m[3];\n"
    "    float3 P = h.xyz / h.w;\n"
    "    float4 nr = round(rsx_tex[0].Load(int3(px, 0)) * 255.0);\n"
    "    float3 N = normalize(nr.rgb * (2.0 / 255.0) - 1.0);\n"
    "    float s = exp2(nr.a * (8.0 / 255.0) - 0.88896);\n"
    "    float3 V = -normalize(P);\n"
    "    float3 acc = float3(0.0, 0.0, 0.0); float sp = 0.0;\n"
    "    int n = min((int)gl_misc.y, 128);\n"
    "    for (int k = 0; k < n; k++) {\n"
    "        GLight L = gl_l[k];\n"
    "        float3 Lv = L.pos_type.xyz - P; float d = length(Lv); float3 l = Lv / d;\n"
    "        float ndl = max(dot(N, l), 0.0);\n"
    "        float att = saturate((L.oacbn.x - d) / (L.oacbn.x - L.col_inner.w)); att *= att;\n"
    "        if (L.pos_type.w > 1.5) {\n"
    "            float c = saturate((dot(-l, L.dir.xyz) - L.oacbn.z) * -L.oacbn.y);\n"
    "            att *= c * c * (d > L.oacbn.w ? 1.0 : 0.0);\n"
    "        }\n"
    "        float w = att * ndl;\n"
    "        if (w <= 0.0) continue;\n"
    "        float3 C = L.col_inner.xyz * gl_misc.x;\n"
    "        float ndh = max(dot(N, normalize(l + V)), 0.0);\n"
    "        acc += w * C;\n"
    "        sp += w * length(C) * (1.0 + 25.0 / 27.0 * s) * pow(1.0 + s * (1.0 - ndh), -8.0);\n"
    "    }\n"
    "    const float K = 0.35355339 * 255.0;\n"
    "    float3 q = sqrt(acc);\n"
    "    float a = min(255.0, floor(max(1.0, max(q.r, max(q.g, q.b))) * K));\n"
    "    o.t0 = float4(min(float3(255.0, 255.0, 255.0), floor(q * K * 255.0 / a)), a) / 255.0;\n"
    "    o.t1 = float4(0.0, 0.0, 0.0, min(255.0, floor(sqrt(sp) * K)) / 255.0);\n"
    "    return o;\n"
    "}\n";
static u32 s_lp_pipe, s_lp_out[2], s_lp_w, s_lp_h;
static int s_lp_failed;
static u32 vk_eng_light_pass(void* user, u32 normals, u32 depth, u32 w, u32 h,
                             const void* params, u32 param_bytes, u32* spec_out)
{
    if (s_lp_failed || !s_g.on || !normals || !depth || !w || !h || !params || !spec_out) return 0;
    if (!vk_eng_get(normals, VK_ENG_TEXTURE) && !vk_eng_get(normals, VK_ENG_COLOR)) return 0;
    if (!s_lp_pipe) {
        rsx_be_render_state rs; memset(&rs, 0, sizeof rs);
        rs.color_mask = 0xFFFFFFFFu; rs.color_mask_mrt = 0xFFFFFFFFu;
        rsx_vertex_layout_plan lay; memset(&lay, 0, sizeof lay);
        lay.mask = 1u; lay.stride = 16u; lay.count = 1u; lay.attrs[0] = 0;
        for (u32 i = 0; i < RSX_DSP_NUM_VERTEX_ATTR; i++) lay.slot_by_attr[i] = -1;
        lay.slot_by_attr[0] = 0;
        s_lp_pipe = vk_eng_pipeline_create(user, s_lp_vs, s_lp_ps, &rs, &lay, 16u, RSX_BE_FMT_R8G8B8A8, 2u);
        if (!s_lp_pipe) { s_lp_failed = 1; VK_LOG("engine: GPU light pass pipeline failed; the SPU job lights\n"); return 0; }
        VK_LOG("engine: GPU light pass on (two RGBA8 targets, full-screen pass)\n");
    }
    if (!s_lp_out[0] || s_lp_w != w || s_lp_h != h) {
        for (int k = 0; k < 2; k++) {
            if (s_lp_out[k]) vk_eng_release(user, s_lp_out[k]);
            s_lp_out[k] = vk_eng_color_target_create(user, RSX_BE_FMT_R8G8B8A8, w, h, NULL, 0);
            if (!s_lp_out[k]) { s_lp_out[0] = s_lp_out[1] = 0; return 0; }
        }
        s_lp_w = w; s_lp_h = h;
    }
    /* The engine's state, kept: it rebinds only what changes between its own draws. */
    static u8 vs_save[VK_VPCONST_BYTES], ps_save[(RSX_FP_MAX_INLINE_CONSTANTS + 1u) * 16u];
    __typeof__(s_eng_bound) bound = s_eng_bound;
    const u32 pipe = s_e2.pipeline, vsb = s_e2.vs_bytes, psb = s_e2.ps_bytes, mask = s_e2.tex_mask;
    u32 tex[RSX_BE_MAX_TEXTURES]; rsx_be_sampler_desc samp[RSX_BE_MAX_TEXTURES];
    memcpy(tex, s_e2.tex, sizeof tex); memcpy(samp, s_e2.samp, sizeof samp);
    float vp[4]; u32 sc[4]; memcpy(vp, s_e2.vp, sizeof vp); memcpy(sc, s_e2.sc, sizeof sc);
    const int have_vp = s_e2.have_vp, have_sc = s_e2.have_sc;
    const u32 sref = s_e2.stencil_ref;
    if (vsb && vsb <= sizeof vs_save) memcpy(vs_save, s_g.ubo.ptr, vsb);
    if (psb && psb <= sizeof ps_save) memcpy(ps_save, (u8*)s_g.ubo.ptr + s_g.ps_off, psb);

    const u32 rts[2] = { s_lp_out[0], s_lp_out[1] };
    vk_eng_bind_targets(user, rts, 2u, 0u);
    vk_eng_bind_pipeline(user, s_lp_pipe);
    static const float one16[4] = { 0.0f, 0.0f, 0.0f, 0.0f };
    vk_eng_bind_vs_constants(user, one16, 16u);
    vk_eng_bind_ps_constants(user, params, param_bytes);
    u32 t[RSX_BE_MAX_TEXTURES] = { 0 }; rsx_be_sampler_desc sd[RSX_BE_MAX_TEXTURES];
    memset(sd, 0, sizeof sd);
    for (u32 i = 0; i < 2; i++) { sd[i].wrap_s = sd[i].wrap_t = sd[i].wrap_r = 3; sd[i].max_lod = 0.0f; }
    t[0] = normals; t[1] = depth;
    vk_eng_bind_textures(user, t, sd, 3u);
    s_e2.have_vp = 0; s_e2.have_sc = 0; s_e2.stencil_ref = 0;
    static const float tri[12] = { -1.0f, -1.0f, 0.0f, 1.0f,  3.0f, -1.0f, 0.0f, 1.0f,  -1.0f, 3.0f, 0.0f, 1.0f };
    vk_eng_draw(user, RSX_TOPOLOGY_TRIANGLES, tri, 3u, 16u, NULL, 0u);

    s_eng_bound = bound;
    s_e2.pipeline = pipe; s_e2.vs_bytes = vsb; s_e2.ps_bytes = psb; s_e2.tex_mask = mask;
    memcpy(s_e2.tex, tex, sizeof tex); memcpy(s_e2.samp, samp, sizeof samp);
    memcpy(s_e2.vp, vp, sizeof vp); memcpy(s_e2.sc, sc, sizeof sc);
    s_e2.have_vp = have_vp; s_e2.have_sc = have_sc; s_e2.stencil_ref = sref;
    if (vsb && vsb <= sizeof vs_save) memcpy(s_g.ubo.ptr, vs_save, vsb);
    if (psb && psb <= sizeof ps_save) memcpy((u8*)s_g.ubo.ptr + s_g.ps_off, ps_save, psb);
    *spec_out = s_lp_out[1];
    return s_lp_out[0];
}
'''
edit("libs/video/rsx_vulkan_backend.c", "static void vk_eng_bind_pipeline(void* user, u32 pipeline) { (void)user; s_e2.pipeline = pipeline; }\n",
     "static void vk_eng_bind_pipeline(void* user, u32 pipeline) { (void)user; s_e2.pipeline = pipeline; }\n"
     "/* defined with the other engine draws below */\n"
     "static void vk_eng_bind_targets(void* user, const u32* surfaces, u32 count, u32 depth);\n"
     "static void vk_eng_bind_vs_constants(void* user, const void* data, u32 bytes);\n"
     "static void vk_eng_bind_ps_constants(void* user, const void* data, u32 bytes);\n"
     "static void vk_eng_bind_textures(void* user, const u32* textures, const rsx_be_sampler_desc* samplers, u32 mask);\n"
     "static void vk_eng_draw(void* user, rsx_topology topology, const void* vertices, u32 vertex_count,\n"
     "                        u32 stride, const u32* indices, u32 index_count);\n",
     "vk light: decls")
edit("libs/video/rsx_vulkan_backend.c", "    .readback             = vk_eng_readback,\n",
     "    .readback             = vk_eng_readback,\n    .light_pass           = vk_eng_light_pass,\n",
     "vk light: table")
edit("libs/video/rsx_vulkan_backend.c", "static const rsx_draw_backend s_vk_engine_backend = {\n",
     VK_LIGHT + "\nstatic const rsx_draw_backend s_vk_engine_backend = {\n", "vk light: pass")

# depth_snapshot_rgba8 on the GPU: the depth target's R32F copy (vk_eng_depth_snapshot, recorded in
# the batch) turned into the Z24-as-A8R8G8B8 encoding by a one-target full-screen pass -- the CPU
# path's encoding exactly: d24 = (u32)(clamp(d, 0, 1) * 16777215 + 0.5); R = d[15:8], G = d[7:0],
# B = stencil (0: this depth format has no stencil aspect, as before), A = d[23:16]. The CPU path
# flushed the batch, waited for the GPU, converted w*h pixels and uploaded them again, every time
# the game sampled a depth buffer as a colour texture. PS3_VK_DEPTH_RGBA8_GPU=0 keeps the CPU path;
# any failure here falls back to it.
VK_DEPTH8 = r'''
/* ---- E6: depth -> A8R8G8B8 on the GPU ------------------------------------- */
static const char* const s_dz_ps =
    "Texture2D    rsx_tex[16] : register(t0);\n"
    "SamplerState rsx_samp[16] : register(s0);\n"
    "struct PSInput { float4 pos:SV_Position; };\n"
    "float4 main(PSInput input) : SV_TARGET {\n"
    "    float d = saturate(rsx_tex[0].Load(int3(int2(input.pos.xy), 0)).x);\n"
    "    uint v = (uint)(d * 16777215.0 + 0.5);\n"
    "    return float4((float)((v >> 8) & 255u), (float)(v & 255u), 0.0, (float)((v >> 16) & 255u)) / 255.0;\n"
    "}\n";
static u32 s_dz_pipe;
static int s_dz_failed = -1;
static struct { u32 depth, w, h, rt; } s_dz_cache[32];
static u32 vk_eng_depth_rgba8_gpu(void* user, u32 depth, u32 w, u32 h)
{
    if (s_dz_failed < 0) { const char* e = getenv("PS3_VK_DEPTH_RGBA8_GPU"); s_dz_failed = (e && *e == '0') ? 1 : 0; }
    if (s_dz_failed || !s_g.on) return 0;
    vk_eng_obj* z = vk_eng_get(depth, VK_ENG_DEPTH);
    if (!z || s_vk.depth_format != VK_FORMAT_D32_SFLOAT) return 0;
    if (w > z->w) w = z->w;
    if (h > z->h) h = z->h;
    if (!w || !h) return 0;
    if (!s_dz_pipe) {
        rsx_be_render_state rs; memset(&rs, 0, sizeof rs);
        rs.color_mask = 0xFFFFFFFFu;
        rsx_vertex_layout_plan lay; memset(&lay, 0, sizeof lay);
        lay.mask = 1u; lay.stride = 16u; lay.count = 1u;
        for (u32 i = 0; i < RSX_DSP_NUM_VERTEX_ATTR; i++) lay.slot_by_attr[i] = -1;
        lay.slot_by_attr[0] = 0;
        s_dz_pipe = vk_eng_pipeline_create(user, s_lp_vs, s_dz_ps, &rs, &lay, 16u, RSX_BE_FMT_R8G8B8A8, 1u);
        if (!s_dz_pipe) { s_dz_failed = 1; VK_LOG("engine: GPU depth->RGBA8 pipeline failed; the CPU converts\n"); return 0; }
        VK_LOG("engine: depth->RGBA8 snapshots on the GPU\n");
    }
    /* One RGBA8 target per (depth target, size): sampled by draws already recorded, so never
     * reused for another depth target while it may be in flight; evicted round robin. */
    int slot = -1;
    for (int i = 0; i < 32; i++)
        if (s_dz_cache[i].rt && s_dz_cache[i].depth == depth && s_dz_cache[i].w == w && s_dz_cache[i].h == h
            && vk_eng_get(s_dz_cache[i].rt, VK_ENG_COLOR)) { slot = i; break; }
    if (slot < 0) {
        static int next;
        slot = next++ & 31;
        if (s_dz_cache[slot].rt) vk_eng_release(user, s_dz_cache[slot].rt);
        s_dz_cache[slot].rt = vk_eng_color_target_create(user, RSX_BE_FMT_R8G8B8A8, w, h, NULL, 0);
        if (!s_dz_cache[slot].rt) { s_dz_cache[slot].depth = 0; return 0; }
        s_dz_cache[slot].depth = depth; s_dz_cache[slot].w = w; s_dz_cache[slot].h = h;
    }
    const u32 src = vk_eng_depth_snapshot(user, depth, z->w, z->h);
    if (!src) return 0;
    const u32 rt = s_dz_cache[slot].rt;

    static u8 vs_save[VK_VPCONST_BYTES], ps_save[(RSX_FP_MAX_INLINE_CONSTANTS + 1u) * 16u];
    __typeof__(s_eng_bound) bound = s_eng_bound;
    const u32 pipe = s_e2.pipeline, vsb = s_e2.vs_bytes, psb = s_e2.ps_bytes, mask = s_e2.tex_mask;
    u32 tex[RSX_BE_MAX_TEXTURES]; rsx_be_sampler_desc samp[RSX_BE_MAX_TEXTURES];
    memcpy(tex, s_e2.tex, sizeof tex); memcpy(samp, s_e2.samp, sizeof samp);
    float vp[4]; u32 sc[4]; memcpy(vp, s_e2.vp, sizeof vp); memcpy(sc, s_e2.sc, sizeof sc);
    const int have_vp = s_e2.have_vp, have_sc = s_e2.have_sc;
    const u32 sref = s_e2.stencil_ref;
    if (vsb && vsb <= sizeof vs_save) memcpy(vs_save, s_g.ubo.ptr, vsb);
    if (psb && psb <= sizeof ps_save) memcpy(ps_save, (u8*)s_g.ubo.ptr + s_g.ps_off, psb);

    vk_eng_bind_targets(user, &rt, 1u, 0u);
    vk_eng_bind_pipeline(user, s_dz_pipe);
    static const float zero16[4] = { 0.0f, 0.0f, 0.0f, 0.0f };
    vk_eng_bind_vs_constants(user, zero16, 16u);
    vk_eng_bind_ps_constants(user, zero16, 16u);
    u32 t[RSX_BE_MAX_TEXTURES] = { 0 }; rsx_be_sampler_desc sd[RSX_BE_MAX_TEXTURES];
    memset(sd, 0, sizeof sd);
    sd[0].wrap_s = sd[0].wrap_t = sd[0].wrap_r = 3;
    t[0] = src;
    vk_eng_bind_textures(user, t, sd, 1u);
    s_e2.have_vp = 0; s_e2.have_sc = 0; s_e2.stencil_ref = 0;
    static const float tri[12] = { -1.0f, -1.0f, 0.0f, 1.0f,  3.0f, -1.0f, 0.0f, 1.0f,  -1.0f, 3.0f, 0.0f, 1.0f };
    vk_eng_draw(user, RSX_TOPOLOGY_TRIANGLES, tri, 3u, 16u, NULL, 0u);

    s_eng_bound = bound;
    s_e2.pipeline = pipe; s_e2.vs_bytes = vsb; s_e2.ps_bytes = psb; s_e2.tex_mask = mask;
    memcpy(s_e2.tex, tex, sizeof tex); memcpy(s_e2.samp, samp, sizeof samp);
    memcpy(s_e2.vp, vp, sizeof vp); memcpy(s_e2.sc, sc, sizeof sc);
    s_e2.have_vp = have_vp; s_e2.have_sc = have_sc; s_e2.stencil_ref = sref;
    if (vsb && vsb <= sizeof vs_save) memcpy(s_g.ubo.ptr, vs_save, vsb);
    if (psb && psb <= sizeof ps_save) memcpy((u8*)s_g.ubo.ptr + s_g.ps_off, ps_save, psb);
    return rt;
}
'''
edit("libs/video/rsx_vulkan_backend.c",
     "static u32 vk_eng_depth_snapshot_rgba8(void* user, u32 depth, u32 w, u32 h)\n{\n",
     "static u32 vk_eng_depth_rgba8_gpu(void* user, u32 depth, u32 w, u32 h);   /* E6, below */\n"
     "static u32 vk_eng_depth_snapshot_rgba8(void* user, u32 depth, u32 w, u32 h)\n{\n"
     "    { const u32 g = vk_eng_depth_rgba8_gpu(user, depth, w, h); if (g) return g; }\n",
     "vk depth8: hook")
edit("libs/video/rsx_vulkan_backend.c", "\nstatic const rsx_draw_backend s_vk_engine_backend = {\n",
     VK_DEPTH8 + "\nstatic const rsx_draw_backend s_vk_engine_backend = {\n", "vk depth8: pass")

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

# rsx_draw_backend.ssao_pass on Vulkan: inFAMOUS 2's SSAO job on the GPU, the Metal backend's five
# passes (rsx_metal_backend.m ssao_*_fs) ported to HLSL: half-res linear depth, 12-sample AO, two
# depth-aware blurs, the 2x upsample. The engine's targets are RGBA8 only, so the half-res depth (an
# R32F on Metal) travels as its four bytes and the AO planes (R8) in .r; both read back exactly.
# Metal's 64-bit reciprocal-estimate arithmetic is the same in 32 bits ((8192|base) << 19 is always
# 2^32 + base << 19). Constants: the C block's float X[12] / Y[12] / Z[12] are tightly packed, so the
# HLSL cbuffer reads them as float4[3] each (offsets 16, 64, 112; 320 bytes in all).
VK_SSAO = r'''
/* ---- E7: the GPU SSAO passes (PS3RECOMP_ENG_GPU_SSAO) ---------------------- */
#define VK_SSAO_COMMON \
    "Texture2D    rsx_tex[16] : register(t0);\n" \
    "SamplerState rsx_samp[16] : register(s0);\n" \
    "cbuffer PSConstants : register(b1) {\n" \
    "    float4 depth_ab; float4 X4[3]; float4 Y4[3]; float4 Z4[3]; float4 M[3];\n" \
    "    float4 C0, D0, E0, F0; float4 blur; float4 up; uint4 dims;\n" \
    "};\n" \
    "struct PSInput { float4 pos:SV_Position; };\n" \
    "static const uint LUT[32] = {\n" \
    "    0x7FFBE0, 0x7F87A6, 0x70EF72, 0x708B40, 0x638B12, 0x633AEA, 0x5792C4, 0x574AA0,\n" \
    "    0x4CCA7E, 0x4C9262, 0x430A44, 0x42D62A, 0x3A2E12, 0x39FDFA, 0x3215E4, 0x31F1D2,\n" \
    "    0x2AA9BE, 0x2A85AC, 0x23D59A, 0x23BD8E, 0x1D8576, 0x1D8576, 0x17AD5A, 0x17AD5A,\n" \
    "    0x124543, 0x124543, 0x0D392D, 0x0D392D, 0x08851A, 0x08851A, 0x041D07, 0x041D07 };\n" \
    "float ssao_recip(float x) {\n" \
    "    uint b = asuint(x);\n" \
    "    uint sgn = b & 0x80000000u, e = (b >> 23) & 0xFFu;\n" \
    "    uint re = (e == 0u) ? 255u : (e >= 253u ? 0u : 253u - e);\n" \
    "    uint est = sgn | (re << 23) | (LUT[(b >> 18) & 31u] & 0x7FFFFFu);\n" \
    "    int ee = (int)((est >> 23) & 0xFFu);\n" \
    "    if (ee == 0) return 0.0;\n" \
    "    uint A = ((est >> 10) & 0x1FFFu) << 19, P = (est & 0x3FFu) * (b & 0x7FFFFu), mant;\n" \
    "    if (A >= P) mant = ((A - P) >> 9) & 0x7FFFFFu;\n" \
    "    else { ee -= 1; if (ee == 0) return 0.0; mant = ((0u - 2u * (P - A)) >> 9) & 0x7FFFFFu; }\n" \
    "    return asfloat(sgn | ((uint)ee << 23) | mant);\n" \
    "}\n" \
    "float ssao_mul_rz(float a, float b) {\n" \
    "    float p = a * b;\n" \
    "    return (mad(a, b, -p) < 0.0 && p > 0.0) ? asfloat(asuint(p) - 1u) : p;\n" \
    "}\n" \
    "float ssao_sat(float x) { return x >= 1.0 ? asfloat(0x3F7FFFFFu) : max(x, 0.0); }\n" \
    "float ssao_z24(float d01) { return (float)(uint)(clamp(d01, 0.0, 1.0) * 16777215.0); }\n" \
    "float ssao_lin(float z24, float A, float B) {\n" \
    "    float k = A * asfloat(0x33800001u);\n" \
    "    float pe = mad(A, asfloat(0x33800001u), -k);\n" \
    "    if ((pe > 0.0 && k < 0.0) || (pe < 0.0 && k > 0.0)) k = asfloat(asuint(k) - 1u);\n" \
    "    float v = mad(z24, k, B);\n" \
    "    float r = ssao_recip(v);\n" \
    "    return mad(mad(-v, r, 1.0), r, r);\n" \
    "}\n" \
    "float hdv(int2 p) { uint4 q = (uint4)round(rsx_tex[1].Load(int3(p, 0)) * 255.0);\n" \
    "                    return asfloat(q.x | (q.y << 8) | (q.z << 16) | (q.w << 24)); }\n" \
    "float aob(int2 p) { return round(rsx_tex[0].Load(int3(p, 0)).r * 255.0); }\n" \
    "float4 pack_f(float v) { uint u = asuint(v);\n" \
    "    return float4((float)(u & 255u), (float)((u >> 8) & 255u), (float)((u >> 16) & 255u), (float)(u >> 24)) / 255.0; }\n" \
    "float Xk(int k) { return X4[k >> 2][k & 3]; }\n" \
    "float Yk(int k) { return Y4[k >> 2][k & 3]; }\n" \
    "float Zk(int k) { return Z4[k >> 2][k & 3]; }\n"
/* pass 1: half-res linear depth (t0 = depth R32F) */
static const char* const s_ss_hd = VK_SSAO_COMMON
    "float4 main(PSInput input) : SV_TARGET {\n"
    "    int2 p = int2(input.pos.xy) * 2;\n"
    "    return pack_f(ssao_lin(ssao_z24(rsx_tex[0].Load(int3(p, 0)).r), depth_ab.x, depth_ab.y));\n"
    "}\n";
/* pass 2: AO (t1 = hd, t2 = normals) */
static const char* const s_ss_ao = VK_SSAO_COMMON
    "float4 main(PSInput input) : SV_TARGET {\n"
    "    int2 p = int2(input.pos.xy);\n"
    "    int2 hm = int2(dims.zw) - 1;\n"
    "    float d = hdv(p);\n"
    "    float dc = clamp(d, E0.z, E0.w);\n"
    "    float rcp = ssao_recip(dc);\n"
    "    float q = d * rcp;\n"
    "    float3 nb = round(rsx_tex[2].Load(int3(p * 2, 0)).rgb * 255.0);\n"
    "    float3 n = mad(nb * (1.0 / 256.0), float3(2.0078430175781, 2.0078430175781, 2.0078430175781), float3(-1.0, -1.0, -1.0));\n"
    "    float3 n2 = mad(float3(n.z, n.z, n.z), M[2].xyz, mad(float3(n.y, n.y, n.y), M[1].xyz, n.x * M[0].xyz));\n"
    "    float dref = mad(n2.z, q, d);\n"
    "    float bx = mad(n2.x, rcp, 0.5), by = mad(n2.y, rcp, 0.5);\n"
    "    float sx = D0.y * rcp, sy = D0.z * rcp;\n"
    "    float hz = D0.w * q;\n"
    "    float e0 = E0.x * ssao_recip(q), e1 = E0.y * q;\n"
    "    float acc = 0.0;\n"
    "    for (int k = 0; k < 12; k++) {\n"
    "        int tx = p.x + (int)floor(mad(Xk(k), sx, bx));\n"
    "        int ty = p.y + (int)floor(mad(Yk(k), sy, by));\n"
    "        float ds = hdv(clamp(int2(tx, ty), int2(0, 0), hm));\n"
    "        float h = Zk(k) * hz;\n"
    "        float t = (ds - (dref - h)) * 0.5;\n"
    "        acc += mad(ssao_sat(mad(t, e0, e1)), h, clamp(t, 0.0, h));\n"
    "    }\n"
    "    acc *= ssao_recip(D0.x * q);\n"
    "    float v = ssao_sat(mad(acc, F0.x, F0.y));\n"
    "    float o = floor(ssao_mul_rz(v, 255.0 / 256.0) * 256.0) / 255.0;\n"
    "    return float4(o, o, o, o);\n"
    "}\n";
/* passes 3-4: depth-aware blur (t0 = ao, t1 = hd); horizontal and vertical */
#define VK_SSAO_BLUR(DX, DY) VK_SSAO_COMMON \
    "float4 main(PSInput input) : SV_TARGET {\n" \
    "    int2 p = int2(input.pos.xy); int2 dir = int2(" DX ", " DY ");\n" \
    "    int2 hm = int2(dims.zw) - 1;\n" \
    "    float d0 = hdv(p);\n" \
    "    float kk = blur.x * ssao_recip(d0);\n" \
    "    float w[5], a[5];\n" \
    "    for (int o = -2; o <= 2; o++) {\n" \
    "        int2 s = clamp(p + o * dir, int2(0, 0), hm);\n" \
    "        a[o + 2] = aob(s);\n" \
    "        w[o + 2] = max(0.0, mad(-abs(hdv(s) - d0), kk, 1.0)) * ((o == -2 || o == 2) ? blur.y : blur.z);\n" \
    "    }\n" \
    "    float num = mad(w[4], a[4], mad(w[3], a[3], mad(w[1], a[1], mad(w[0], a[0], a[2]))));\n" \
    "    float den = w[4] + (w[3] + (1.0 + (w[0] + w[1])));\n" \
    "    float r = floor(ssao_mul_rz(num, ssao_recip(den))) / 255.0;\n" \
    "    return float4(r, r, r, r);\n" \
    "}\n"
static const char* const s_ss_bh = VK_SSAO_BLUR("1", "0");
static const char* const s_ss_bv = VK_SSAO_BLUR("0", "1");
/* pass 5: 2x depth-aware upsample (t0 = ao, t1 = hd, t2 = depth R32F) */
static const char* const s_ss_up = VK_SSAO_COMMON
    "float4 main(PSInput input) : SV_TARGET {\n"
    "    int2 P = int2(input.pos.xy);\n"
    "    int2 hm = int2(dims.zw) - 1;\n"
    "    float Z = ssao_lin(ssao_z24(rsx_tex[2].Load(int3(P, 0)).r), up.x, up.y);\n"
    "    float kz = up.z * ssao_recip(Z);\n"
    "    int2 b = P >> 1;\n"
    "    int2 s = int2((P.x & 1) ? 1 : -1, (P.y & 1) ? 1 : -1);\n"
    "    int2 off[4] = { int2(0, 0), int2(0, s.y), int2(s.x, 0), s };\n"
    "    float bw[4] = { 9.0, 3.0, 3.0, 1.0 };\n"
    "    float eps[4] = { asfloat(0x3A6BEDFAu), asfloat(0x399D4952u), asfloat(0x399D4952u), asfloat(0x38D1B717u) };\n"
    "    float num = 0.0, den = 0.0;\n"
    "    for (int k = 0; k < 4; k++) {\n"
    "        int2 t = clamp(b + off[k], int2(0, 0), hm);\n"
    "        float w = mad(max(0.0, mad(-abs(hdv(t) - Z), kz, 1.0)), bw[k], eps[k]);\n"
    "        num = mad(w, aob(t), num);\n"
    "        den += w;\n"
    "    }\n"
    "    float r = floor(ssao_mul_rz(num, ssao_recip(den))) / 255.0;\n"
    "    return float4(r, r, r, r);\n"
    "}\n";
static u32 s_ss_pipe[5], s_ss_tex[4], s_ss_dims[4];
static int s_ss_failed;
/* One full-screen draw into `rt` with textures t0..t2, the engine's state kept. */
static void vk_eng_fs_pass(void* user, u32 pipe_h, u32 rt, const u32* texs, u32 ntex, const void* consts, u32 cbytes)
{
    static u8 vs_save[VK_VPCONST_BYTES], ps_save[(RSX_FP_MAX_INLINE_CONSTANTS + 1u) * 16u];
    __typeof__(s_eng_bound) bound = s_eng_bound;
    const u32 pipe = s_e2.pipeline, vsb = s_e2.vs_bytes, psb = s_e2.ps_bytes, mask = s_e2.tex_mask;
    u32 tex[RSX_BE_MAX_TEXTURES]; rsx_be_sampler_desc samp[RSX_BE_MAX_TEXTURES];
    memcpy(tex, s_e2.tex, sizeof tex); memcpy(samp, s_e2.samp, sizeof samp);
    float vp[4]; u32 sc[4]; memcpy(vp, s_e2.vp, sizeof vp); memcpy(sc, s_e2.sc, sizeof sc);
    const int have_vp = s_e2.have_vp, have_sc = s_e2.have_sc;
    const u32 sref = s_e2.stencil_ref;
    if (vsb && vsb <= sizeof vs_save) memcpy(vs_save, s_g.ubo.ptr, vsb);
    if (psb && psb <= sizeof ps_save) memcpy(ps_save, (u8*)s_g.ubo.ptr + s_g.ps_off, psb);

    vk_eng_bind_targets(user, &rt, 1u, 0u);
    vk_eng_bind_pipeline(user, pipe_h);
    static const float zero16[4] = { 0.0f, 0.0f, 0.0f, 0.0f };
    vk_eng_bind_vs_constants(user, zero16, 16u);
    vk_eng_bind_ps_constants(user, consts, cbytes);
    u32 t[RSX_BE_MAX_TEXTURES] = { 0 }; rsx_be_sampler_desc sd[RSX_BE_MAX_TEXTURES];
    memset(sd, 0, sizeof sd);
    u32 m = 0;
    for (u32 i = 0; i < ntex && i < RSX_BE_MAX_TEXTURES; i++) {
        t[i] = texs[i]; sd[i].wrap_s = sd[i].wrap_t = sd[i].wrap_r = 3;
        if (texs[i]) m |= 1u << i;
    }
    vk_eng_bind_textures(user, t, sd, m);
    s_e2.have_vp = 0; s_e2.have_sc = 0; s_e2.stencil_ref = 0;
    static const float tri[12] = { -1.0f, -1.0f, 0.0f, 1.0f,  3.0f, -1.0f, 0.0f, 1.0f,  -1.0f, 3.0f, 0.0f, 1.0f };
    vk_eng_draw(user, RSX_TOPOLOGY_TRIANGLES, tri, 3u, 16u, NULL, 0u);

    s_eng_bound = bound;
    s_e2.pipeline = pipe; s_e2.vs_bytes = vsb; s_e2.ps_bytes = psb; s_e2.tex_mask = mask;
    memcpy(s_e2.tex, tex, sizeof tex); memcpy(s_e2.samp, samp, sizeof samp);
    memcpy(s_e2.vp, vp, sizeof vp); memcpy(s_e2.sc, sc, sizeof sc);
    s_e2.have_vp = have_vp; s_e2.have_sc = have_sc; s_e2.stencil_ref = sref;
    if (vsb && vsb <= sizeof vs_save) memcpy(s_g.ubo.ptr, vs_save, vsb);
    if (psb && psb <= sizeof ps_save) memcpy((u8*)s_g.ubo.ptr + s_g.ps_off, ps_save, psb);
}
static u32 vk_eng_ssao_pass(void* user, u32 depth, u32 normals, const void* consts, u32 const_bytes,
                            u32 fw, u32 fh, u32 hw, u32 hh)
{
    if (s_ss_failed || !s_g.on || !depth || !normals || !consts || !fw || !fh || !hw || !hh) return 0;
    if (const_bytes < 320u) return 0;
    if (!s_ss_pipe[0]) {
        const char* ps[5] = { s_ss_hd, s_ss_ao, s_ss_bh, s_ss_bv, s_ss_up };
        rsx_be_render_state rs; memset(&rs, 0, sizeof rs);
        rs.color_mask = 0xFFFFFFFFu;
        rsx_vertex_layout_plan lay; memset(&lay, 0, sizeof lay);
        lay.mask = 1u; lay.stride = 16u; lay.count = 1u;
        for (u32 i = 0; i < RSX_DSP_NUM_VERTEX_ATTR; i++) lay.slot_by_attr[i] = -1;
        lay.slot_by_attr[0] = 0;
        for (int k = 0; k < 5; k++)
            if (!(s_ss_pipe[k] = vk_eng_pipeline_create(user, s_lp_vs, ps[k], &rs, &lay, 16u, RSX_BE_FMT_R8G8B8A8, 1u))) {
                s_ss_failed = 1; VK_LOG("engine: GPU SSAO pass %d pipeline failed; the SPU job runs\n", k); return 0;
            }
        VK_LOG("engine: GPU SSAO on (five passes, RGBA8 intermediates)\n");
    }
    if (!s_ss_tex[0] || s_ss_dims[0] != fw || s_ss_dims[1] != fh || s_ss_dims[2] != hw || s_ss_dims[3] != hh) {
        for (int k = 0; k < 4; k++) {
            if (s_ss_tex[k]) vk_eng_release(user, s_ss_tex[k]);
            s_ss_tex[k] = vk_eng_color_target_create(user, RSX_BE_FMT_R8G8B8A8, k == 3 ? fw : hw, k == 3 ? fh : hh, NULL, 0);
            if (!s_ss_tex[k]) { for (int j = 0; j < 4; j++) s_ss_tex[j] = 0; return 0; }
        }
        s_ss_dims[0] = fw; s_ss_dims[1] = fh; s_ss_dims[2] = hw; s_ss_dims[3] = hh;
    }
    /* t0 / t1 / t2 per pass, as the shaders read them */
    const u32 hd = s_ss_tex[0], aA = s_ss_tex[1], aB = s_ss_tex[2], out = s_ss_tex[3];
    const u32 t_hd[3] = { depth, 0, 0 };
    const u32 t_ao[3] = { 0, hd, normals };
    const u32 t_bh[3] = { aA, hd, 0 };
    const u32 t_bv[3] = { aB, hd, 0 };
    const u32 t_up[3] = { aA, hd, depth };
    vk_eng_fs_pass(user, s_ss_pipe[0], hd,  t_hd, 1u, consts, const_bytes);
    vk_eng_fs_pass(user, s_ss_pipe[1], aA,  t_ao, 3u, consts, const_bytes);
    vk_eng_fs_pass(user, s_ss_pipe[2], aB,  t_bh, 2u, consts, const_bytes);
    vk_eng_fs_pass(user, s_ss_pipe[3], aA,  t_bv, 2u, consts, const_bytes);
    vk_eng_fs_pass(user, s_ss_pipe[4], out, t_up, 3u, consts, const_bytes);
    return out;
}
'''
edit("libs/video/rsx_vulkan_backend.c", "\nstatic const rsx_draw_backend s_vk_engine_backend = {\n",
     VK_SSAO + "\nstatic const rsx_draw_backend s_vk_engine_backend = {\n", "vk ssao: passes")
edit("libs/video/rsx_vulkan_backend.c", "    .light_pass           = vk_eng_light_pass,\n",
     "    .light_pass           = vk_eng_light_pass,\n    .ssao_pass            = vk_eng_ssao_pass,\n", "vk ssao: table")

# PS3RECOMP_ENG_BLIT_LOG=1: log the first 48 RSX write-backs (blits of a render target to another
# surface), source and destination. How a game's light-job input buffers are found (the offsets
# PS3RECOMP_ENG_GPU_LIGHT takes): they are the two per-frame blits into main memory.
edit("libs/video/rsx_draw_engine.c",
     '''    if (!g.ready || !g.be->readback || !g.be->submit_and_wait) return 0;
    if (eng_gpu_light_blit(local ? RSX_LOCATION_LOCAL : RSX_LOCATION_MAIN, offset, pitch,''',
     '''    if (!g.ready || !g.be->readback || !g.be->submit_and_wait) return 0;
    { static int lg = -1; static _Atomic unsigned n;
      if (lg < 0) lg = getenv("PS3RECOMP_ENG_BLIT_LOG") ? 1 : 0;
      if (lg && n++ < 48)
          fprintf(stderr, "[blit log] %s 0x%08X pitch %u -> %s 0x%08X\\n", local ? "local" : "main",
                  offset, pitch, dst_local < 0 ? "self" : dst_local ? "local" : "main", dst_offset); }
    if (eng_gpu_light_blit(local ? RSX_LOCATION_LOCAL : RSX_LOCATION_MAIN, offset, pitch,''',
     "eng blit log")

# PS3RECOMP_ENG_BLIT_LOG=1, second form: each distinct write-back (source, destination) once (up to
# 96), so the per-frame world blits show up after the menus' repeats.
edit("libs/video/rsx_draw_engine.c",
     '''      if (lg && n++ < 48)
          fprintf(''',
     '''      static u32 seen[96][2]; static unsigned ns;
      int fresh = 0;
      if (lg) {
          static pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;
          pthread_mutex_lock(&m);
          unsigned k = 0;
          while (k < ns && !(seen[k][0] == offset && seen[k][1] == dst_offset)) k++;
          if (k == ns && ns < 96) { seen[ns][0] = offset; seen[ns][1] = dst_offset; ns++; fresh = 1; }
          pthread_mutex_unlock(&m);
      }
      if (fresh && ++n)
          fprintf(''',
     "eng blit log: distinct")

# PS3RECOMP_ENG_GPU_SSAO_WB=1: with the SSAO on the GPU, still write the depth and normals copies
# back to main memory (A/B: FoB's sky/clouds wash out with the GPU SSAO and the copies unwritten,
# and are right with the light pass alone).
edit("libs/video/rsx_draw_engine.c",
     '''      return ssao || (nowb && is_n); }''',
     '''      static int keepwb = -1;
      if (keepwb < 0) { const char* e = getenv("PS3RECOMP_ENG_GPU_SSAO_WB"); keepwb = e && *e == '1'; }
      return (ssao && !keepwb) || (nowb && is_n); }''',
     "eng gpu ssao wb knob")

# spu pollwake probe: count SPU event waits that ended only because the 1 ms re-poll saw the
# reserved line change (its writer raised no SPU_EVENT_LR), and name the first lines it happened on.
edit("runtime/spu/spu_channels.c",
     '''    if (changed && spu_resv_break(ctx, rea & ~127u))
        spu_ev_raise(ctx, 0x400u);
}''',
     '''    if (changed && spu_resv_break(ctx, rea & ~127u)) {
        spu_ev_raise(ctx, 0x400u);
        /* No writer told us: report the line (each distinct one once, up to 32) and a running
         * count, so the store path that skips spu_coh_notify_write can be found. */
        static _Atomic unsigned long s_pw; static uint32_t s_pw_ea[32]; static _Atomic int s_pw_n;
        const unsigned long n = __atomic_add_fetch(&s_pw, 1, __ATOMIC_RELAXED);
        int known = 0; const int nn = s_pw_n;
        for (int i = 0; i < nn && i < 32; i++) if (s_pw_ea[i] == (rea & ~127u)) { known = 1; break; }
        if (!known && nn < 32) { s_pw_ea[nn] = rea & ~127u; s_pw_n = nn + 1;
            fprintf(stderr, "[spu pollwake] spu=%X line 0x%08X changed with no LR raised (pc 0x%05X, img %d)\\n",
                    ctx->spu_id, rea & ~127u, ctx->pc & SPU_LS_MASK, ctx->image_id); }
        if ((n & 4095) == 0)
            fprintf(stderr, "[spu pollwake] %lu wakes found by the poll; LR raised by writers %lu\\n",
                    n, g_spu_lr_raise);
    }
}''',
     "spu pollwake probe")
# ...and how each blocked event wait ended: woken by a producer, or by the timed re-poll.
edit("runtime/spu/spu_channels.c",
     '''            AcquireSRWLockExclusive((SRWLOCK*)&ctx->ch_wait_lock);
            if (!spu_ch_ready(ctx, channel))
                SleepConditionVariableSRW((CONDITION_VARIABLE*)&ctx->ch_wait_cv,
                                          (SRWLOCK*)&ctx->ch_wait_lock, spu_chwait_ms(), 0);
            ReleaseSRWLockExclusive((SRWLOCK*)&ctx->ch_wait_lock);''',
     '''            AcquireSRWLockExclusive((SRWLOCK*)&ctx->ch_wait_lock);
            if (!spu_ch_ready(ctx, channel))
                last_to = !SleepConditionVariableSRW((CONDITION_VARIABLE*)&ctx->ch_wait_cv,
                                          (SRWLOCK*)&ctx->ch_wait_lock, spu_chwait_ms(), 0);
            ReleaseSRWLockExclusive((SRWLOCK*)&ctx->ch_wait_lock);
            sleeps++;''',
     "spu pollwake wait end")
edit("runtime/spu/spu_channels.c",
     '''        unsigned long long start = GetTickCount64(), next_hb = 2000;
        while (!spu_ch_ready(ctx, channel)) {''',
     '''        unsigned long long start = GetTickCount64(), next_hb = 2000;
        int last_to = 0, sleeps = 0;
        while (!spu_ch_ready(ctx, channel)) {''',
     "spu pollwake wait vars")
edit("runtime/spu/spu_channels.c",
     '''                next_hb = ((waited / 2000) + 1) * 2000;
            }
        }
    }
    yz_lockstep_block_end(ctx);            /* rejoin the rotation, reacquire the token */''',
     '''                next_hb = ((waited / 2000) + 1) * 2000;
            }
        }
        /* Event waits: woken by a producer, or found ready by the timed re-poll. */
        if (channel == SPU_RdEventStat && sleeps) {
            static _Atomic unsigned long s_sig, s_to, s_tot;
            if (last_to) __atomic_add_fetch(&s_to, 1, __ATOMIC_RELAXED);
            else         __atomic_add_fetch(&s_sig, 1, __ATOMIC_RELAXED);
            if ((__atomic_add_fetch(&s_tot, 1, __ATOMIC_RELAXED) & 16383) == 0)
                fprintf(stderr, "[spu pollwake] event waits: %lu woken by a producer, %lu by the %u ms re-poll\\n",
                        s_sig, s_to, spu_chwait_ms());
        }
    }
    yz_lockstep_block_end(ctx);            /* rejoin the rotation, reacquire the token */''',
     "spu pollwake wait report")

# spu pollwake probe counters: plain unsigned long with __atomic builtins (clang refuses _Atomic there)
edit("runtime/spu/spu_channels.c",
     '''static _Atomic unsigned long s_pw; static uint32_t s_pw_ea[32]; static _Atomic int s_pw_n;''',
     '''static unsigned long s_pw; static uint32_t s_pw_ea[32]; static int s_pw_n;''',
     "spu pollwake counters plain")
edit("runtime/spu/spu_channels.c",
     '''            static _Atomic unsigned long s_sig, s_to, s_tot;''',
     '''            static unsigned long s_sig, s_to, s_tot;''',
     "spu pollwake wait counters plain")

# usleep kick: a short guest sys_timer_usleep waits for an SPU write to main memory instead of the host timer
# inFAMOUS 2's SPU light-task kicker and main thread poll SPU task results with usleep(3)/usleep(10).
# The host's shortest sleep is ~1 ms on Linux in practice for that loop and ~0.6 ms on the PS5, so ~300
# task handoffs a frame each waited that long. A sleep of PS3_USLEEP_KICK_US (default 50) or less now
# waits on a condition every SPU PUT / PUTLLC / PUTLLUC signals, capped at PS3_USLEEP_KICK_CAP_US
# (default 100): the poll sees the SPU's result at once, and nothing spins.
edit("runtime/spu/spu_coherency.c",
     '''#include "spu_coherency.h"''',
     '''#include "spu_coherency.h"

#include <pthread.h>
#include <time.h>

/* usleep kick: see sys_timer_usleep. g_mk_waiters is read lock-free by every SPU write to main
 * memory; only with a guest thread parked does a write take the mutex, and s_mk_pending makes
 * that at most one broadcast per round of sleepers. */
static pthread_mutex_t s_mk_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t  s_mk_cv = PTHREAD_COND_INITIALIZER;
int g_mk_waiters;
static int s_mk_pending;
unsigned long g_mk_kicks, g_mk_woken, g_mk_timeouts;

void ps3_memkick_slow(void)
{
    if (__atomic_exchange_n(&s_mk_pending, 1, __ATOMIC_ACQ_REL)) return;
    __atomic_add_fetch(&g_mk_kicks, 1, __ATOMIC_RELAXED);
    pthread_mutex_lock(&s_mk_mu);
    pthread_cond_broadcast(&s_mk_cv);
    pthread_mutex_unlock(&s_mk_mu);
}

void ps3_memkick_wait(uint64_t us)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    const uint64_t ns = (uint64_t)ts.tv_nsec + us * 1000ull;
    ts.tv_sec += (time_t)(ns / 1000000000ull);
    ts.tv_nsec = (long)(ns % 1000000000ull);
    pthread_mutex_lock(&s_mk_mu);
    __atomic_add_fetch(&g_mk_waiters, 1, __ATOMIC_SEQ_CST);
    __atomic_store_n(&s_mk_pending, 0, __ATOMIC_RELEASE);
    const int r = pthread_cond_timedwait(&s_mk_cv, &s_mk_mu, &ts);
    __atomic_sub_fetch(&g_mk_waiters, 1, __ATOMIC_SEQ_CST);
    pthread_mutex_unlock(&s_mk_mu);
    __atomic_add_fetch(r ? &g_mk_timeouts : &g_mk_woken, 1, __ATOMIC_RELAXED);
}''',
     "usleep kick core")
edit("runtime/spu/spu_coherency.h",
     '''extern unsigned long g_spu_lr_raise;''',
     '''extern unsigned long g_spu_lr_raise;

/* usleep kick (spu_coherency.c): an SPU write to main memory wakes guest threads parked in a
 * short sys_timer_usleep. ps3_memkick is the cheap check every writer makes. */
extern int g_mk_waiters;
void ps3_memkick_slow(void);
void ps3_memkick_wait(uint64_t us);
static inline void ps3_memkick(void)
{
    if (__atomic_load_n(&g_mk_waiters, __ATOMIC_RELAXED)) ps3_memkick_slow();
}''',
     "usleep kick header")
# The writers: SPU PUT (spu_dma.h), PUTLLC success and PUTLLUC (spu_channels.c).
edit("runtime/spu/spu_dma.h",
     '''        { extern void (*g_spu_put_hook)(uint32_t ea, uint32_t size);
          if (g_spu_put_hook) g_spu_put_hook((uint32_t)ea, size); }''',
     '''        { extern int g_mk_waiters; extern void ps3_memkick_slow(void);   /* usleep kick */
          if (__atomic_load_n(&g_mk_waiters, __ATOMIC_RELAXED)) ps3_memkick_slow(); }
        { extern void (*g_spu_put_hook)(uint32_t ea, uint32_t size);
          if (g_spu_put_hook) g_spu_put_hook((uint32_t)ea, size); }''',
     "usleep kick spu put")
edit("runtime/spu/spu_channels.c",
     '''        RESV_DROP(ctx);                                /* reservation consumed */
        spu_lockline_unlock_mask(llm);
        if (ctx->atomic_stat == 0 && g_spu_line_commit_hook) g_spu_line_commit_hook(ea & ~127u);''',
     '''        RESV_DROP(ctx);                                /* reservation consumed */
        spu_lockline_unlock_mask(llm);
        if (ctx->atomic_stat == 0) ps3_memkick();      /* usleep kick */
        if (ctx->atomic_stat == 0 && g_spu_line_commit_hook) g_spu_line_commit_hook(ea & ~127u);''',
     "usleep kick putllc")
edit("runtime/spu/spu_channels.c",
     '''        RESV_DROP(ctx); ctx->atomic_stat = 2;        /* PUTLLUC complete */
        spu_lockline_unlock_mask(llm);''',
     '''        RESV_DROP(ctx); ctx->atomic_stat = 2;        /* PUTLLUC complete */
        spu_lockline_unlock_mask(llm);
        ps3_memkick();                                 /* usleep kick */''',
     "usleep kick putlluc")
edit("runtime/syscalls/sys_timer.c",
     '''    { static long spin_us = -1;
      if (spin_us < 0) { const char* e = getenv("PS3_USLEEP_SPIN_US");''',
     '''    /* usleep kick (spu_coherency.c): a short sleep is a poll for another processor's result,
     * so it waits for the next SPU write to main memory, at most PS3_USLEEP_KICK_CAP_US.
     * PS3_USLEEP_KICK_US=0 restores the host sleep. The first distinct call sites are logged. */
    { static long kick_us = -1, cap_us = 100;
      if (kick_us < 0) { const char* e = getenv("PS3_USLEEP_KICK_US"); kick_us = e ? atol(e) : 50; if (kick_us < 0) kick_us = 0;
                         const char* c = getenv("PS3_USLEEP_KICK_CAP_US"); if (c && atol(c) > 0) cap_us = atol(c); }
      if (usec > 0 && usec <= (uint64_t)kick_us) {
          static uint32_t seen[16]; static int ns;
          const uint32_t key = (uint32_t)ctx->lr ^ ((uint32_t)usec << 24);
          int k = 0; while (k < ns && seen[k] != key) k++;
          if (k == ns && ns < 16) { seen[ns++] = key;
              fprintf(stderr, "[usleep kick] tid %u usleep(%llu) at lr 0x%08X waits for an SPU write (cap %ld us)\\n",
                      (unsigned)ctx->thread_id, (unsigned long long)usec, (uint32_t)ctx->lr, cap_us); }
          extern void ps3_memkick_wait(uint64_t us);
          ps3_memkick_wait(usec > (uint64_t)cap_us ? usec : (uint64_t)cap_us);
          return CELL_OK;
      } }
    { static long spin_us = -1;
      if (spin_us < 0) { const char* e = getenv("PS3_USLEEP_SPIN_US");''',
     "usleep kick sys_timer")

# spu x86 mpy and ls: SSE4.1 16-bit multiplies and one-pshufb local-store quadword loads/stores
# The x86 builds (Linux zen2, the PS5) ran mpy/mpyu/mpyh/mpyhh/mpyi/mpyui/mpya as four scalar imuls,
# and every lqd/stqd as four 32-bit loads + bswaps merged through 64-bit registers. Same results
# (tools/test_spu_x86_mpy_ls.c compares each against its _ref / the scalar form).
for name, args, body in [
    ("spu_mpy",   "u128 a, u128 b",          "_mm_mullo_epi32(SPU__LO16S(spu__m128(a)), SPU__LO16S(spu__m128(b)))"),
    ("spu_mpyu",  "u128 a, u128 b",          "_mm_mullo_epi32(SPU__LO16U(spu__m128(a)), SPU__LO16U(spu__m128(b)))"),
    ("spu_mpyh",  "u128 a, u128 b",          "_mm_slli_epi32(_mm_mullo_epi32(_mm_srai_epi32(spu__m128(a), 16), SPU__LO16S(spu__m128(b))), 16)"),
    ("spu_mpyhh", "u128 a, u128 b",          "_mm_mullo_epi32(_mm_srai_epi32(spu__m128(a), 16), _mm_srai_epi32(spu__m128(b), 16))"),
]:
    edit("runtime/spu/spu_helpers.h",
         "static inline u128 %s(%s) { return %s_ref(a, b); }" % (name, args, name),
         "#if defined(__SSE4_1__)\nstatic inline u128 %s(%s) { return spu__u128(%s); }\n#else\n"
         "static inline u128 %s(%s) { return %s_ref(a, b); }\n#endif" % (name, args, body, name, args, name),
         "spu x86 " + name)
edit("runtime/spu/spu_helpers.h",
     "static inline u128 spu_mpyi(u128 a, int32_t imm) { return spu_mpyi_ref(a, imm); }",
     "#if defined(__SSE4_1__)\nstatic inline u128 spu_mpyi(u128 a, int32_t imm) { return spu__u128(_mm_mullo_epi32(SPU__LO16S(spu__m128(a)), _mm_set1_epi32((int32_t)(int16_t)imm))); }\n#else\n"
     "static inline u128 spu_mpyi(u128 a, int32_t imm) { return spu_mpyi_ref(a, imm); }\n#endif",
     "spu x86 spu_mpyi")
edit("runtime/spu/spu_helpers.h",
     "static inline u128 spu_mpyui(u128 a, int32_t imm) { return spu_mpyui_ref(a, imm); }",
     "#if defined(__SSE4_1__)\nstatic inline u128 spu_mpyui(u128 a, int32_t imm) { return spu__u128(_mm_mullo_epi32(SPU__LO16U(spu__m128(a)), _mm_set1_epi32((int32_t)(uint16_t)imm))); }\n#else\n"
     "static inline u128 spu_mpyui(u128 a, int32_t imm) { return spu_mpyui_ref(a, imm); }\n#endif",
     "spu x86 spu_mpyui")
edit("runtime/spu/spu_helpers.h",
     "static inline u128 spu_mpya(u128 a, u128 b, u128 c) { return spu_mpya_ref(a, b, c); }",
     "#if defined(__SSE4_1__)\nstatic inline u128 spu_mpya(u128 a, u128 b, u128 c) { return spu__u128(_mm_add_epi32(spu__m128(spu_mpy(a, b)), spu__m128(c))); }\n#else\n"
     "static inline u128 spu_mpya(u128 a, u128 b, u128 c) { return spu_mpya_ref(a, b, c); }\n#endif",
     "spu x86 spu_mpya")
# The converters and lane masks the forms above use, next to the SSE4.1 shufb.
edit("runtime/spu/spu_helpers.h",
     '''#if defined(__SSE4_1__)
#include <smmintrin.h>''',
     '''#if defined(__SSE4_1__)
#include <smmintrin.h>
/* u128 <-> __m128i (the x86 integer forms; memcpy compiles to nothing) and the low halfword of
 * each word, sign- or zero-extended -- the operand of the 16-bit multiplies. */
static inline __m128i spu__m128(u128 a) { __m128i x; memcpy(&x, &a, 16); return x; }
static inline u128 spu__u128(__m128i x) { u128 r; memcpy(&r, &x, 16); return r; }
#define SPU__LO16S(x) _mm_srai_epi32(_mm_slli_epi32((x), 16), 16)
#define SPU__LO16U(x) _mm_and_si128((x), _mm_set1_epi32(0xFFFF))''',
     "spu x86 m128 converters")
# Local store: one unaligned load and a pshufb (each word's bytes reversed), and back.
edit("runtime/spu/spu_context.h",
     '''    const uint8_t* p = &ctx->ls[lsa];
#if SPU_LS_FAST
    uint32_t w0, w1, w2, w3;''',
     '''    const uint8_t* p = &ctx->ls[lsa];
#if SPU_LS_FAST && defined(__SSSE3__)
    { __m128i x = _mm_loadu_si128((const __m128i*)p);
      x = _mm_shuffle_epi8(x, _mm_setr_epi8(3,2,1,0, 7,6,5,4, 11,10,9,8, 15,14,13,12));
      memcpy(&v, &x, 16); }
#elif SPU_LS_FAST
    uint32_t w0, w1, w2, w3;''',
     "spu x86 ls read128")
edit("runtime/spu/spu_context.h",
     '''#if SPU_LS_FAST
    uint32_t w0 = SPU_BSWAP32(val._u32[0]), w1 = SPU_BSWAP32(val._u32[1]);''',
     '''#if SPU_LS_FAST && defined(__SSSE3__)
    { __m128i x; memcpy(&x, &val, 16);
      x = _mm_shuffle_epi8(x, _mm_setr_epi8(3,2,1,0, 7,6,5,4, 11,10,9,8, 15,14,13,12));
      _mm_storeu_si128((__m128i*)p, x); }
#elif SPU_LS_FAST
    uint32_t w0 = SPU_BSWAP32(val._u32[0]), w1 = SPU_BSWAP32(val._u32[1]);''',
     "spu x86 ls write128")
edit("runtime/spu/spu_context.h",
     '''static inline __attribute__((always_inline)) u128 spu_ls_read128(const spu_context* ctx, uint32_t lsa)''',
     '''#if defined(__SSSE3__)
#include <tmmintrin.h>   /* spu_ls_read128/write128: pshufb */
#endif
static inline __attribute__((always_inline)) u128 spu_ls_read128(const spu_context* ctx, uint32_t lsa)''',
     "spu x86 ls include")

# vk dump every: PS3RECOMP_VK_DUMP_EVERY=<s> keeps a half-size screenshot every <s> seconds
# as <PS3RECOMP_VK_DUMP>.<n>.ppm (n = 0..199, then reused) instead of overwriting one full-size file
# each frame: the console's picture, fetched over FTP. One buffer, one fwrite.
edit("libs/video/rsx_vulkan_backend.c",
     '''static void vk_dump_ppm(const unsigned char* rgba)
{
    FILE* f = fopen(s_vk.dump_path, "wb");''',
     '''static void vk_dump_ppm(const unsigned char* rgba)
{
    static double every = -1;
    static unsigned long long last_ns;
    static unsigned seq;
    if (every < 0) { const char* e = getenv("PS3RECOMP_VK_DUMP_EVERY"); every = e ? atof(e) : 0; }
    if (every > 0) {
        struct timespec ts;
        clock_gettime(CLOCK_MONOTONIC, &ts);
        const unsigned long long now = (unsigned long long)ts.tv_sec * 1000000000ull + (unsigned long long)ts.tv_nsec;
        if (last_ns && now - last_ns < (unsigned long long)(every * 1e9)) return;
        last_ns = now;
        char path[600];
        snprintf(path, sizeof path, "%s.%03u.ppm", s_vk.dump_path, seq++ % 200u);
        const u32 w = s_vk.width / 2, h = s_vk.height / 2;
        unsigned char* buf = (unsigned char*)malloc((size_t)w * h * 3 + 32);
        if (!buf) return;
        int len = snprintf((char*)buf, 32, "P6\\n%u %u\\n255\\n", w, h);
        unsigned char* o = buf + len;
        for (u32 y = 0; y < h; y++)
            for (u32 x = 0; x < w; x++) {
                const unsigned char* s = rgba + ((size_t)(y * 2) * s_vk.width + x * 2) * 4;
                *o++ = s[0]; *o++ = s[1]; *o++ = s[2];
            }
        FILE* f = fopen(path, "wb");
        if (f) { fwrite(buf, 1, (size_t)(o - buf), f); fclose(f); }
        free(buf);
        return;
    }
    FILE* f = fopen(s_vk.dump_path, "wb");''',
     "vk dump every")

# tdump spu and event queues: PS3_THREAD_DUMP also prints every live SPU context and event queue
# A hang between a PPU thread and an SPU (Bink's RADG5 decoder: the PPU spins, the SPU waits on its
# event queue) shows only one side in the guest-thread list. Each SPU context: id, group, image, pc,
# status, event status/mask, stop code, inbound mailbox count; each active queue: type, name, count.
edit("runtime/spu/spu_channels.c",
     '''static spu_mfc_slot s_mfc_slots[SPU_MAX_CONTEXTS];
static SRWLOCK      s_mfc_claim_lock = SRWLOCK_INIT;''',
     '''static spu_mfc_slot s_mfc_slots[SPU_MAX_CONTEXTS];
static SRWLOCK      s_mfc_claim_lock = SRWLOCK_INIT;

/* PS3_THREAD_DUMP's SPU half (sys_ppu_thread.c): every context with an MFC slot. */
void spu_dump_contexts(void)
{
    for (int i = 0; i < SPU_MAX_CONTEXTS; i++) {
        const spu_context* c = __atomic_load_n(&s_mfc_slots[i].ctx, __ATOMIC_ACQUIRE);
        if (!c) continue;
        fprintf(stderr, "[tdump] spu ctx%-3d id=0x%X grp=0x%X img=%d pc=0x%05X status=0x%X evstat=0x%X evmask=0x%X stop=0x%X inmbox=%u\\n",
                i, c->spu_id, c->spu_group_id, c->image_id, c->pc & SPU_LS_MASK, c->status,
                c->event_status, c->event_mask, c->stop_code, (unsigned)spu_channel_count(&c->ch_in_mbox));
    }
}''',
     "tdump spu contexts")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''            fputc('\\n', stderr);
        }
        fflush(stderr);''',
     '''            fputc('\\n', stderr);
        }
        { extern void spu_dump_contexts(void); spu_dump_contexts(); }
        for (int q = 0; q < SYS_EVENT_QUEUE_MAX; q++) {
            const sys_event_queue_info* e = &g_sys_event_queues[q];
            if (!e->active) continue;
            fprintf(stderr, "[tdump] equeue %-3d type=%d name=%.8s key=0x%llX pending=%d%s\\n", q + 1, e->type,
                    e->name, (unsigned long long)e->key, e->count, e->cancelled ? " CANCELLED" : "");
        }
        fflush(stderr);''',
     "tdump event queues")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''#ifndef _WIN32
#include <pthread.h>
#include <unistd.h>
static uint32_t td_rd32(uint32_t a)''',
     '''#ifndef _WIN32
#include <pthread.h>
#include <unistd.h>
#include "sys_event.h"   /* tdump: g_sys_event_queues */
static uint32_t td_rd32(uint32_t a)''',
     "tdump event include")

# tdump main thread live ctx: PS3_THREAD_DUMP read the main thread's table copy (lr/sp 0)
# The main guest thread runs on the loader's local ppu_context, not g_ppu_threads[0].ctx, so the
# dump showed it as lr=0 sp=0 -- and a main thread spinning in guest code is exactly what it is for.
edit("runtime/ppu/ppu_loader.cpp",
     '''    { extern uint64_t ppu_thread_register_main(void);
      ctx.thread_id = ppu_thread_register_main(); }''',
     '''    { extern uint64_t ppu_thread_register_main(void);
      ctx.thread_id = ppu_thread_register_main(); }
    { extern "C" ppu_context* g_ppu_main_ctx_live; g_ppu_main_ctx_live = &ctx; }   /* tdump */''',
     "tdump main live ctx set")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''int32_t g_ppu_primary_prio = 1001;''',
     '''int32_t g_ppu_primary_prio = 1001;
/* The main thread's live context (ppu_loader.cpp), for PS3_THREAD_DUMP. */
ppu_context* g_ppu_main_ctx_live;''',
     "tdump main live ctx def")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''            const ppu_context* c = &t->ctx;
            fprintf(stderr, "[tdump] tid=%-3d %-28s lr=0x%08X sp=0x%08X prof=0x%08X chain:",''',
     '''            const ppu_context* c = (i == 0 && g_ppu_main_ctx_live) ? g_ppu_main_ctx_live : &t->ctx;
            fprintf(stderr, "[tdump] tid=%-3d %-28s lr=0x%08X sp=0x%08X prof=0x%08X chain:",''',
     "tdump main live ctx use")

# tdump main live ctx linkage: extern "C" is file-scope only in C++
edit("runtime/ppu/ppu_loader.cpp",
     '''    { extern "C" ppu_context* g_ppu_main_ctx_live; g_ppu_main_ctx_live = &ctx; }   /* tdump */''',
     '''    g_ppu_main_ctx_live = &ctx;   /* tdump */''',
     "tdump main live ctx set2")
edit("runtime/ppu/ppu_loader.cpp",
     '''extern "C" int32_t  g_ppu_primary_prio;   /* main thread priority (sys_ppu_thread.c) */''',
     '''extern "C" int32_t  g_ppu_primary_prio;   /* main thread priority (sys_ppu_thread.c) */
extern "C" ppu_context* g_ppu_main_ctx_live; /* PS3_THREAD_DUMP (sys_ppu_thread.c) */''',
     "tdump main live ctx decl")

# dbgsrv runtime hooks: the thread dump to any FILE, SPU contexts by index, a screenshot on demand
# For the PS5 app's debug server (tools/ps5/ps5_app.c, PS5_DEBUG_PORT): the same dump PS3_THREAD_DUMP
# writes to the log, written to a file the server sends back; an SPU context's local store by its
# slot; and g_vk_dump_now, which makes the next present write a screenshot whatever the interval.
edit("runtime/syscalls/sys_ppu_thread.c",
     '''void ps3_thread_dump_now(const char* why)
{
    {
        fprintf(stderr, "[tdump] ---- guest threads%s%s ----\\n", why ? ": " : "", why ? why : "");''',
     '''void ps3_thread_dump_to(FILE* o, const char* why);
void ps3_thread_dump_now(const char* why) { ps3_thread_dump_to(stderr, why); }
void ps3_thread_dump_to(FILE* o, const char* why)
{
    {
        fprintf(o, "[tdump] ---- guest threads%s%s ----\\n", why ? ": " : "", why ? why : "");''',
     "dbgsrv tdump head")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''            fprintf(stderr, "[tdump] tid=%-3d %-28s lr=0x%08X sp=0x%08X prof=0x%08X chain:",''',
     '''            fprintf(o, "[tdump] tid=%-3d %-28s lr=0x%08X sp=0x%08X prof=0x%08X chain:",''',
     "dbgsrv tdump tid")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''                fprintf(stderr, " 0x%x", td_rd32(next + 20)); /* low word of saved LR at +16 */
                sp = next;
            }
            fputc('\\n', stderr);
        }
        { extern void spu_dump_contexts(void); spu_dump_contexts(); }''',
     '''                fprintf(o, " 0x%x", td_rd32(next + 20)); /* low word of saved LR at +16 */
                sp = next;
            }
            fputc('\\n', o);
        }
        { extern void spu_dump_contexts_to(FILE*); spu_dump_contexts_to(o); }''',
     "dbgsrv tdump chain")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''            fprintf(stderr, "[tdump] equeue %-3d type=%d name=%.8s key=0x%llX pending=%d%s\\n", q + 1, e->type,
                    e->name, (unsigned long long)e->key, e->count, e->cancelled ? " CANCELLED" : "");
        }
        fflush(stderr);''',
     '''            fprintf(o, "[tdump] equeue %-3d type=%d name=%.8s key=0x%llX pending=%d%s\\n", q + 1, e->type,
                    e->name, (unsigned long long)e->key, e->count, e->cancelled ? " CANCELLED" : "");
        }
        fflush(o);''',
     "dbgsrv tdump tail")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''#else
void ps3_thread_dump_now(const char* why) { (void)why; }
#endif''',
     '''#else
void ps3_thread_dump_now(const char* why) { (void)why; }
void ps3_thread_dump_to(FILE* o, const char* why) { (void)o; (void)why; }
#endif''',
     "dbgsrv tdump win stub")
edit("runtime/spu/spu_channels.c",
     '''void spu_dump_contexts(void)
{
    for (int i = 0; i < SPU_MAX_CONTEXTS; i++) {
        const spu_context* c = __atomic_load_n(&s_mfc_slots[i].ctx, __ATOMIC_ACQUIRE);
        if (!c) continue;
        fprintf(stderr, "[tdump] spu ctx%-3d''',
     '''void spu_dump_contexts_to(FILE* o);
void spu_dump_contexts(void) { spu_dump_contexts_to(stderr); }
/* The context in MFC slot i (the "ctx" number the dump prints), or NULL. */
const spu_context* spu_ctx_at(int i)
{
    if (i < 0 || i >= SPU_MAX_CONTEXTS) return NULL;
    return __atomic_load_n(&s_mfc_slots[i].ctx, __ATOMIC_ACQUIRE);
}
/* That context's local store (256 KB), for the debug server's "ls". */
const uint8_t* spu_ctx_ls(int i)
{
    const spu_context* c = spu_ctx_at(i);
    return c ? c->ls : NULL;
}
void spu_dump_contexts_to(FILE* o)
{
    for (int i = 0; i < SPU_MAX_CONTEXTS; i++) {
        const spu_context* c = __atomic_load_n(&s_mfc_slots[i].ctx, __ATOMIC_ACQUIRE);
        if (!c) continue;
        fprintf(o, "[tdump] spu ctx%-3d''',
     "dbgsrv spu ctx dump to")
edit("libs/video/rsx_vulkan_backend.c",
     '''static void vk_dump_ppm(const unsigned char* rgba)
{''',
     '''int g_vk_dump_now;   /* the PS5 debug server's "shot": the next present writes one */
static void vk_dump_ppm(const unsigned char* rgba)
{''',
     "dbgsrv shot flag")
edit("libs/video/rsx_vulkan_backend.c",
     '''        if (last_ns && now - last_ns < (unsigned long long)(every * 1e9)) return;''',
     '''        if (last_ns && now - last_ns < (unsigned long long)(every * 1e9) && !g_vk_dump_now) return;
        g_vk_dump_now = 0;''',
     "dbgsrv shot now")

# dbgsrv regs: a guest thread's registers for the PS5 debug server ("regs <tid>")
# A thread parked in a syscall keeps its arguments and callee-saved registers in its context; with
# them the object it waits on (an event flag, a queue, a lock) can be read from memory.
edit("runtime/syscalls/sys_ppu_thread.c",
     '''void ps3_thread_dump_to(FILE* o, const char* why);
void ps3_thread_dump_now(const char* why) { ps3_thread_dump_to(stderr, why); }''',
     '''void ps3_thread_dump_to(FILE* o, const char* why);
void ps3_thread_dump_now(const char* why) { ps3_thread_dump_to(stderr, why); }
/* One guest thread's registers (tid as the dump prints it). 0 = no such live thread. */
int ps3_thread_regs_to(FILE* o, int tid)
{
    if (tid < 1 || tid > PPU_THREAD_MAX) return 0;
    ppu_thread_info* t = &g_ppu_threads[tid - 1];
    if (t->state != PPU_THREAD_STATE_RUNNING && t->state != PPU_THREAD_STATE_DETACHED) return 0;
    const ppu_context* c = (tid == 1 && g_ppu_main_ctx_live) ? g_ppu_main_ctx_live : &t->ctx;
    fprintf(o, "tid=%d %s cia=0x%08X lr=0x%08X ctr=0x%08X cr=0x%08X xer=0x%llX\\n", tid, t->name,
            (uint32_t)c->cia, (uint32_t)c->lr, (uint32_t)c->ctr, (uint32_t)c->cr, (unsigned long long)c->xer);
    for (int r = 0; r < 32; r += 4)
        fprintf(o, "r%-2d %016llX  r%-2d %016llX  r%-2d %016llX  r%-2d %016llX\\n",
                r, (unsigned long long)c->gpr[r], r + 1, (unsigned long long)c->gpr[r + 1],
                r + 2, (unsigned long long)c->gpr[r + 2], r + 3, (unsigned long long)c->gpr[r + 3]);
    fflush(o);
    return 1;
}''',
     "dbgsrv regs")
edit("runtime/spu/spu_channels.c",
     '''/* That context's local store (256 KB), for the debug server's "ls". */''',
     '''/* That context's registers, for the debug server's "spuregs": pc, status and all 128 GPRs. */
int spu_ctx_regs_to(FILE* o, int i)
{
    const spu_context* c = spu_ctx_at(i);
    if (!c) return 0;
    fprintf(o, "spu ctx%d id=0x%X img=%d pc=0x%05X status=0x%X stop=0x%X evstat=0x%X evmask=0x%X\\n", i, c->spu_id,
            c->image_id, c->pc & SPU_LS_MASK, c->status, c->stop_code, c->event_status, c->event_mask);
    for (int r = 0; r < 128; r += 2)
        fprintf(o, "r%-3d %08X %08X %08X %08X   r%-3d %08X %08X %08X %08X\\n",
                r, c->gpr[r]._u32[0], c->gpr[r]._u32[1], c->gpr[r]._u32[2], c->gpr[r]._u32[3],
                r + 1, c->gpr[r + 1]._u32[0], c->gpr[r + 1]._u32[1], c->gpr[r + 1]._u32[2], c->gpr[r + 1]._u32[3]);
    fflush(o);
    return 1;
}
/* That context's local store (256 KB), for the debug server's "ls". */''',
     "dbgsrv spuregs")

# eng live debug: a live frame capture and render-state overrides through PS3_TOGGLE_FILE
# PS3RECOMP_ENG_CAPTURE=<n>: when the file sets a new value n > 0, the next n frames log every draw
#   ("[cap]": programs, primitive, vertex count, target, depth/cull/blend/alpha-test state, colour
#   mask and the CPU-side position range) and every dropped draw with its reason.
# PS3RECOMP_ENG_DBG_RS=<bits>: force, for every draw from the next one on: 1 alpha test off,
#   2 depth test off, 4 culling off, 8 blending off, 16 colour mask all channels, 32 depth write on.
# Both read once a frame; the overrides change the pipeline key, so new pipelines are built.
edit("libs/video/rsx_draw_engine.c",
     '''static void eng_drop(const char* why, u32 prim)
{
    static int on = -1; static u32 from;''',
     '''static u32 s_cap_until;   /* PS3RECOMP_ENG_CAPTURE: frames below this log every draw */
static int s_dbg_rs;        /* PS3RECOMP_ENG_DBG_RS: render-state override bits */
static void eng_live_debug_frame(void)
{
    static u32 last_frame = ~0u; static int last_cap;
    if (g.frames == last_frame) return;
    last_frame = g.frames;
    const int cap = ps3_toggle_get("PS3RECOMP_ENG_CAPTURE", 0);
    if (cap != last_cap) {
        last_cap = cap;
        if (cap > 0) { s_cap_until = g.frames + (u32)cap; fprintf(stderr, "[cap] capture of %d frames from frame %u\\n", cap, g.frames); }
    }
    s_dbg_rs = ps3_toggle_get("PS3RECOMP_ENG_DBG_RS", 0);
}
static void eng_drop(const char* why, u32 prim)
{
    if (g.frames < s_cap_until)
        fprintf(stderr, "[cap] f=%u d=%u DROP %s prim=%u verts=%u fetch_ok=%d\\n", g.frames, g.guest_draws, why, prim,
                dc.n_verts, dc.fetch_ok);
    static int on = -1; static u32 from;''',
     "eng live debug core")
edit("libs/video/rsx_draw_engine.c",
     '''    DS_MARK(ns_tex);
    int pipeline_is_fixed = 1;''',
     '''    eng_live_debug_frame();
    if (s_dbg_rs) {   /* PS3RECOMP_ENG_DBG_RS */
        if (s_dbg_rs & 1) rs.alpha_test_enable = 0;
        if (s_dbg_rs & 2) rs.depth_test = 0;
        if (s_dbg_rs & 4) rs.cull_enable = 0;
        if (s_dbg_rs & 8) { rs.blend_enable = 0; rs.blend_mrt = 0; }
        if (s_dbg_rs & 16) { rs.color_mask = 0x01010101u; rs.color_mask_mrt = 0xFFFFu; }
        if (s_dbg_rs & 32) rs.depth_write = 1;
    }
    DS_MARK(ns_tex);
    int pipeline_is_fixed = 1;''',
     "eng live debug rs")
edit("libs/video/rsx_draw_engine.c",
     '''    /* PS3_ASPECT_HUD_AFTER=<fp hex>[,<fp hex>..]: the title's 2D overlay for''',
     '''    if (g.frames < s_cap_until) {   /* PS3RECOMP_ENG_CAPTURE */
        const eng_vp_memo* vpm = NULL; const eng_fp_memo* fpm = NULL;
        eng_guest_programs(&vpm, &fpm);
        float mn[4] = { 1e30f, 1e30f, 1e30f, 1e30f }, mx[4] = { -1e30f, -1e30f, -1e30f, -1e30f };
        const s8 ps = layout.slot_by_attr[0];
        if (ps >= 0 && dc.verts && !(dc.vbuf_hit && indexed))
            for (u32 v = 0; v < uploaded_hud_n(dc.n_verts, n_draw, indexed); v++) {
                const float* q = (const float*)((const u8*)dc.verts + (size_t)v * layout.stride + (size_t)ps * 16u);
                for (int c = 0; c < 4; c++) { if (q[c] < mn[c]) mn[c] = q[c]; if (q[c] > mx[c]) mx[c] = q[c]; } }
        fprintf(stderr, "[cap] f=%u d=%u p=%u prim=%u n=%u nt=%u rt=0x%08X %ux%u vp=%016llx fp=%016llx"
                        " z=%u/%u/0x%X cull=%u/0x%X/0x%X cmask=0x%08X/0x%X blend=%u/0x%X at=%u/0x%X/0x%X vtex=0x%X"
                        " pos x[%g,%g] y[%g,%g] z[%g,%g] w[%g,%g]\\n",
                g.frames, g.guest_draws, pipeline, prim, dc.n_verts, n_targets, g.surfaces[target].offset,
                g.surfaces[target].w, g.surfaces[target].h,
                (unsigned long long)(vpm ? vpm->hash : 0), (unsigned long long)(fpm ? fpm->structural : 0),
                rs.depth_test, rs.depth_write, rs.depth_func, rs.cull_enable, rs.cull_face, rs.front_face,
                rs.color_mask, rs.color_mask_mrt, rs.blend_enable, rs.blend_mrt,
                rs.alpha_test_enable, rs.alpha_func, rs.alpha_ref_raw, vtex_mask,
                mn[0], mx[0], mn[1], mx[1], mn[2], mx[2], mn[3], mx[3]);
    }
    /* PS3_ASPECT_HUD_AFTER=<fp hex>[,<fp hex>..]: the title's 2D overlay for''',
     "eng live debug capture")

# vk pipe limit: the Vulkan engine pipeline table held 512 while the engine allows 8192
# Once a session had built 512 pipelines (FoB on the console: the cutscenes, then the level), every
# new one failed with no log and its draws were dropped ("pipeline") -- Cole's body and a roof went
# invisible while everything built earlier still drew. The table now matches the engine's limit,
# and running out or failing to translate says so.
edit("libs/video/rsx_vulkan_backend.c",
     '''#define VK_ENG_MAX_PIPE   512''',
     '''#define VK_ENG_MAX_PIPE   8192   /* = ENG_MAX_PIPELINES (rsx_draw_engine.c); was 512 */''',
     "vk pipe limit size")
edit("libs/video/rsx_vulkan_backend.c",
     '''    if (slot == VK_ENG_MAX_PIPE) return 0;
    vk_eng_pipe* P = &s_epipe[slot];
    memset(P, 0, sizeof *P);
    if (vk_eng_translate(vs_hlsl, RSX_SHADER_STAGE_VERTEX, &P->vs)) return 0;
    if (vk_eng_translate(ps_hlsl, RSX_SHADER_STAGE_FRAGMENT, &P->fs)) {
        pvkDestroyShaderModule(s_vk.device, P->vs, NULL); memset(P, 0, sizeof *P); return 0;
    }''',
     '''    if (slot == VK_ENG_MAX_PIPE) {
        static int told; if (!told++) VK_LOG("engine: pipeline table full (%u): new pipelines fail and their draws are dropped\\n", VK_ENG_MAX_PIPE);
        return 0;
    }
    vk_eng_pipe* P = &s_epipe[slot];
    memset(P, 0, sizeof *P);
    if (vk_eng_translate(vs_hlsl, RSX_SHADER_STAGE_VERTEX, &P->vs)) {
        static int told; if (told++ < 8) VK_LOG("engine: vertex program failed to translate: its draws are dropped\\n");
        return 0;
    }
    if (vk_eng_translate(ps_hlsl, RSX_SHADER_STAGE_FRAGMENT, &P->fs)) {
        static int told; if (told++ < 8) VK_LOG("engine: fragment program failed to translate: its draws are dropped\\n");
        pvkDestroyShaderModule(s_vk.device, P->vs, NULL); memset(P, 0, sizeof *P); return 0;
    }''',
     "vk pipe limit log")

# vk sampler limit: the engine sampler cache held 64 and then handed every new sampler state the default
# A long session meets more than 64 (filter x wrap x LOD) combinations; from the 65th on, textures were
# sampled with the default wrap/filter. 1024 is far under maxSamplerAllocationCount (>= 4000); full says so.
edit("libs/video/rsx_vulkan_backend.c",
     '''#define VK_ENG_SAMP_CACHE 64''',
     '''#define VK_ENG_SAMP_CACHE 1024   /* was 64 */''',
     "vk samp limit size")
edit("libs/video/rsx_vulkan_backend.c",
     '''    if (s_esamp_count >= VK_ENG_SAMP_CACHE) return s_vk.sampler;''',
     '''    if (s_esamp_count >= VK_ENG_SAMP_CACHE) {
        static int told; if (!told++) VK_LOG("engine: sampler cache full (%u): new sampler states use the default\\n", VK_ENG_SAMP_CACHE);
        return s_vk.sampler;
    }''',
     "vk samp limit log")

# skip movies: PS3_SKIP_MOVIES=intro|all makes chosen Bink movies "missing", so the game goes on
# intro: the start-up splashes and logos (movies/cutscene/splash*.bik, *logo*.bik); all: every movie
# in movies/cutscene/ (the comic-book and story videos too). In-world screens (movies/tv/) always play.
# The launcher's SKIP INTRO / SKIP CUTSCENE MOVIES settings set it.
edit("runtime/ppu/ppu_fs.cpp",
     '''    /* fopen() mode strings can't express the PS3/POSIX open semantics (e.g.''',
     '''    { static int skip = -1;
      if (skip < 0) { const char* e = getenv("PS3_SKIP_MOVIES");
                      skip = !e ? 0 : !strcmp(e, "all") ? 2 : !strcmp(e, "intro") ? 1 : 0; }
      if (skip) {
          const char* b = strrchr(gpath, '/'); b = b ? b + 1 : gpath;
          const size_t n = strlen(b);
          if (n > 4 && !strcasecmp(b + n - 4, ".bik") && strstr(gpath, "/movies/cutscene/")) {
              const int intro = !strncasecmp(b, "splash", 6) || strcasestr(b, "logo") != NULL;
              if (skip == 2 || intro) {
                  fprintf(stderr, "[fs] skipped movie '%s' (PS3_SKIP_MOVIES=%s)\\n", gpath, skip == 2 ? "all" : "intro");
                  ctx->gpr[3] = (uint64_t)(int64_t)CELL_FS_ENOENT; return;
              }
          }
      } }
    /* fopen() mode strings can't express the PS3/POSIX open semantics (e.g.''',
     "skip movies open")

# skip movies case: lower-case the name by hand (no strcasestr/strncasecmp: no new PS5 imports)
edit("runtime/ppu/ppu_fs.cpp",
     '''          const char* b = strrchr(gpath, '/'); b = b ? b + 1 : gpath;
          const size_t n = strlen(b);
          if (n > 4 && !strcasecmp(b + n - 4, ".bik") && strstr(gpath, "/movies/cutscene/")) {
              const int intro = !strncasecmp(b, "splash", 6) || strcasestr(b, "logo") != NULL;''',
     '''          const char* b0 = strrchr(gpath, '/'); b0 = b0 ? b0 + 1 : gpath;
          char b[256]; size_t n = 0;
          for (; b0[n] && n < sizeof b - 1; n++) b[n] = (b0[n] >= 'A' && b0[n] <= 'Z') ? (char)(b0[n] + 32) : b0[n];
          b[n] = 0;
          if (n > 4 && !strcmp(b + n - 4, ".bik") && strstr(gpath, "/movies/cutscene/")) {
              const int intro = !strncmp(b, "splash", 6) || strstr(b, "logo") != NULL;''',
     "skip movies case")
# lfq poll: libsre's blocking LFQueue push/pop polls a non-blocking call instead of sleeping on lv2
edit("runtime/syscalls/lv2_prx.c",
     '''static void reg_fn(uint32_t addr, void (*fn)(void*)) { ppu_register_function(addr, (void (*)(ppu_context*))fn); }''',
     '''static void reg_fn(uint32_t addr, void (*fn)(void*)) { ppu_register_function(addr, (void (*)(ppu_context*))fn); }

/* libsre's SPURS LFQueue, blocking side. A blocking _cellSpursLFQueuePushBody /
 * PopBody that finds the queue full (empty) registers the PPU thread as a
 * waiter in the queue line (+0x20..) and sleeps in sys_event_queue_receive on
 * the queue's lv2 event queue until the SPU side wakes it. On the console that
 * path failed after a few minutes of streaming: the push returned an error,
 * inFAMOUS: Festival of Blood's EDGE zlib queue asserted
 * (edgezlib_inflate_queue.cpp:425, 0 == ret), and the inflate SPU later ran a
 * garbage request and branched into its own data (SPURS aborted).
 *
 * The non-blocking call returns CELL_SYNC_ERROR_AGAIN before it touches the
 * line when there is no room, so polling it does what a blocking call does
 * without the waiter registration or the event queue: the wrapper below calls
 * the lifted libsre function with the blocking bit clear and retries AGAIN
 * after a short sleep. Any other error is logged with the queue line.
 * PS3_LFQ_POLL=0 turns it off. */
#ifndef _WIN32
#include <unistd.h>
#endif
extern PPU_THREAD_LOCAL void (*g_trampoline_fn)(void*);
#define LFQ_NID_PUSH 0x8A85674Du
#define LFQ_NID_POP  0x35DAE22Bu
static void (*s_lfq_orig[2])(void*);

static void lfq_polled(ppu_context* ctx, int which)
{
    const uint64_t a3 = ctx->gpr[3], a4 = ctx->gpr[4], a5 = ctx->gpr[5], r2 = ctx->gpr[2], lr = ctx->lr;
    const int blocking = (int)(a5 & 1u);
    int32_t rc = 0;
    for (unsigned n = 0;; n++) {
        ctx->gpr[3] = a3; ctx->gpr[4] = a4; ctx->gpr[5] = blocking ? (a5 & ~1ull) : a5;
        ctx->gpr[2] = r2; ctx->lr = lr;
        s_lfq_orig[which]((void*)ctx);
        while (g_trampoline_fn) { void (*tf)(void*) = g_trampoline_fn; g_trampoline_fn = 0; tf((void*)ctx); }
        rc = (int32_t)ctx->gpr[3];
        if (!blocking || rc != (int32_t)0x80410101u) break;
        if (n == 20000) {
            static int s_full = 0;
            if (s_full++ < 8)
                fprintf(stderr, "[lfq] %s q=0x%08X still %s after ~2 s of polling\\n",
                        which ? "pop" : "push", (uint32_t)a3, which ? "empty" : "full");
        }
#ifndef _WIN32
        usleep(100);
#else
        Sleep(0);
#endif
    }
    if (rc != 0) {
        static int s_err = 0;
        if (s_err++ < 16) {
            const uint8_t* q = vm_base + (uint32_t)a3;
            fprintf(stderr, "[lfq] %s q=0x%08X flags=%u returned 0x%08X; line:", which ? "pop" : "push",
                    (uint32_t)a3, (unsigned)a5, (uint32_t)rc);
            for (int o = 0; o < 128; o += 4) fprintf(stderr, "%s%02X%02X%02X%02X", o % 32 ? " " : "\\n   ", q[o], q[o+1], q[o+2], q[o+3]);
            fprintf(stderr, "\\n");
        }
    }
    ctx->gpr[2] = r2;
    ctx->lr = lr;
}
static void lfq_push_polled(ppu_context* ctx) { lfq_polled(ctx, 0); }
static void lfq_pop_polled(ppu_context* ctx)  { lfq_polled(ctx, 1); }

/* After libsre is placed: put the wrappers at its push and pop functions. */
static void lfq_install(const prx_module* m)
{
    const char* e = getenv("PS3_LFQ_POLL");
    if ((e && *e == '0') || !m->name || (strcmp(m->name, "libsre") && strcmp(m->name, "cellSre_Library"))) return;
    for (uint32_t i = 0; i < m->export_count; i++) {
        const int which = m->exports[i].nid == LFQ_NID_PUSH ? 0 : m->exports[i].nid == LFQ_NID_POP ? 1 : -1;
        if (which < 0) continue;
        const uint32_t fn_ea = rd32(m->base + m->exports[i].vaddr);   /* the OPD's code address */
        for (uint64_t k = 0; k < m->func_count; k++)
            if ((uint32_t)m->funcs[k].addr == fn_ea) { s_lfq_orig[which] = m->funcs[k].func; break; }
        if (!s_lfq_orig[which]) { fprintf(stderr, "[lfq] %s at 0x%08X: no lifted function\\n", which ? "pop" : "push", fn_ea); continue; }
        ppu_register_function(fn_ea, which ? lfq_pop_polled : lfq_push_polled);
        fprintf(stderr, "[lfq] libsre LFQueue %s (0x%08X) polls instead of blocking\\n", which ? "pop" : "push", fn_ea);
    }
}''',
     "lfq poll: wrapper")
edit("runtime/syscalls/lv2_prx.c",
     '''    if (m) prx_place_module(&m->mod, reg_fn);''',
     '''    if (m) { prx_place_module(&m->mod, reg_fn); lfq_install(&m->mod); }''',
     "lfq poll: install")
# perfdiag: thread labels, periodic ftrace windows, present GPU wait, flush sites, file read spans
edit("runtime/platform/host_qos.h",
     '''#define PS3_HOST_QOS_PPU_INTERACTIVE_BELOW 1500
''',
     '''#define PS3_HOST_QOS_PPU_INTERACTIVE_BELOW 1500

/* The host thread's name for the PS5 build's profile and wait reports
 * (tools/ps5/ps5_shims.c defines ps3_host_thread_label). Weak, so a host
 * without it links and this is a no-op. */
#if defined(__GNUC__) || defined(__clang__)
#ifdef __cplusplus
extern "C" {
#endif
void ps3_host_thread_label(const char* name) __attribute__((weak));
#ifdef __cplusplus
}
#endif
static inline void ps3_host_label(const char* name) { if (ps3_host_thread_label) ps3_host_thread_label(name); }
#else
static inline void ps3_host_label(const char* name) { (void)name; }
#endif
''',
     "perfdiag: label hook")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''    { extern void ppu_resv_register(ppu_context*); ppu_resv_register(&info->ctx); }''',
     '''    { extern void ppu_resv_register(ppu_context*); ppu_resv_register(&info->ctx); }
    ps3_host_label(info->name[0] ? info->name : "ppu");''',
     "perfdiag: ppu label")
edit("runtime/syscalls/lv2_register.c",
     '''    ps3_host_qos_self(1);   /* PS3_QOS (host_qos.h): the SPUs set the frame rate */''',
     '''    ps3_host_qos_self(1);   /* PS3_QOS (host_qos.h): the SPUs set the frame rate */
    { char nm[24]; snprintf(nm, sizeof nm, "spu %X.%u", t->group_id, t->index); ps3_host_label(nm); }''',
     "perfdiag: spu label")
edit("runtime/syscalls/lv2_register.c",
     '''    ps3_host_qos_self(1);   /* PS3_QOS (host_qos.h) */
    int32_t rc = 0;''',
     '''    ps3_host_qos_self(1);   /* PS3_QOS (host_qos.h) */
    ps3_host_label("spu fallback");
    int32_t rc = 0;''',
     "perfdiag: spu fallback label")
edit("runtime/spu/spu_workload.c",
     '''    ps3_host_qos_self(1);   /* PS3_QOS (host_qos.h) */
    spu_async_run((spu_async_job*)p);''',
     '''    ps3_host_qos_self(1);   /* PS3_QOS (host_qos.h) */
    ps3_host_label("spu async");
    spu_async_run((spu_async_job*)p);''',
     "perfdiag: spu async label")
edit("runtime/spu/spu_workload.c",
     '''    ps3_host_qos_self(1);   /* PS3_QOS (host_qos.h) */
    spu_task_interp_run(j);''',
     '''    ps3_host_qos_self(1);   /* PS3_QOS (host_qos.h) */
    ps3_host_label("spu task interp");
    spu_task_interp_run(j);''',
     "perfdiag: spu task label")

# ---- ftrace: periodic windows (PS3_FTRACE_EVERY=<period s>:<count>) and file read spans ----
edit("include/ps3emu/ps3_ftrace.h",
     '''    PS3_FT_TEXUP       = 17, /* RSX thread decoded + uploaded a guest texture: a = source KB,
                              * b = 0 new, 1 content changed; | 2 when it evicted another */''',
     '''    PS3_FT_TEXUP       = 17, /* RSX thread decoded + uploaded a guest texture: a = source KB,
                              * b = 0 new, 1 content changed; | 2 when it evicted another */
    PS3_FT_FSREAD      = 18, /* a guest file read: who = PPU tid, a = bytes read, b = fd */''',
     "perfdiag: fsread kind")
edit("include/ps3emu/ps3_ftrace.h",
     '''    ps3_ft_rec* buf;
    char path[1024];''',
     '''    ps3_ft_rec* buf;
    uint64_t period;     /* PS3_FTRACE_EVERY: next window this much later, `left` more of them */
    uint32_t left, k;
    char path[1024];''',
     "perfdiag: rotate state")
edit("include/ps3emu/ps3_ftrace.h",
     '''                atexit(ps3_ft_dump_atexit);''',
     '''                atexit(ps3_ft_dump_atexit);
                {   /* PS3_FTRACE_EVERY=<period s>:<count>: a window every <period> s, <path>.<k>.txt */
                    const char* ev = getenv("PS3_FTRACE_EVERY");
                    double per = 0; unsigned cnt = 0;
                    if (ev && sscanf(ev, "%lf:%u", &per, &cnt) == 2 && per > secs && cnt > 1) {
                        s->period = (uint64_t)(per * 1e9); s->left = cnt; s->k = 0;
                        fprintf(stderr, "[ftrace] then every %.0f s, %u windows in all, to %s.<k>.txt\\n", per, cnt, s->path);
                    }
                }''',
     "perfdiag: rotate init")
edit("include/ps3emu/ps3_ftrace.h",
     '''static inline void ps3_ft_dump_atexit(void) { ps3_ft_dump(); }''',
     '''static inline void ps3_ft_dump_atexit(void) { ps3_ft_dump(); }

/* PS3_FTRACE_EVERY: write the window that just ended to <path>.<k>.txt and arm the next one. The
 * thread whose span crossed the end does it; the others see "not recording" meanwhile. */
static inline void ps3_ft_rotate(void)
{
    ps3_ft_state* s = &g_ps3_ft;
    int expect = 2;
    if (!__atomic_compare_exchange_n(&s->on, &expect, 1, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    char base[1024];
    snprintf(base, sizeof base, "%s", s->path);
    snprintf(s->path, sizeof s->path, "%s.%u.txt", base, s->k);
    __atomic_store_n(&s->dumped, 0, __ATOMIC_RELEASE);
    ps3_ft_dump();                                    /* on -> 3 while it writes */
    snprintf(s->path, sizeof s->path, "%s", base);
    s->k++;
    if (--s->left == 0) return;                       /* that was the last: stays off */
    const uint64_t win = s->end - s->start;
    s->start += s->period;
    s->end = s->start + win;
    memset(s->us, 0, sizeof s->us);
    __atomic_store_n(&s->dropped, 0, __ATOMIC_RELAXED);
    __atomic_store_n(&s->n, 0, __ATOMIC_RELEASE);
    __atomic_store_n(&s->dumped, 0, __ATOMIC_RELEASE);
    __atomic_store_n(&s->on, 2, __ATOMIC_RELEASE);
}''',
     "perfdiag: rotate")
edit("include/ps3emu/ps3_ftrace.h",
     '''    if (t0 > s->end) { ps3_ft_dump(); return; }''',
     '''    if (t0 > s->end) { if (s->period) ps3_ft_rotate(); else ps3_ft_dump(); return; }''',
     "perfdiag: rotate at end")

edit("runtime/ppu/ppu_fs.cpp",
     '''#include "../../include/ps3emu/log_first.h"   /* PS3_LOG_FIRST */''',
     '''#include "../../include/ps3emu/log_first.h"   /* PS3_LOG_FIRST */
#include "../../include/ps3emu/ps3_ftrace.h"   /* PS3_FTRACE: file read spans */''',
     "perfdiag: fs include")
edit("runtime/ppu/ppu_fs.cpp",
     '''    size_t n = fread(vm_base + buf, 1, (size_t)nbytes, g_files[fd]);   /* raw bytes, no swap */''',
     '''    const uint64_t ft_r0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    size_t n = fread(vm_base + buf, 1, (size_t)nbytes, g_files[fd]);   /* raw bytes, no swap */
    if (ft_r0) ps3_ft_span(PS3_FT_FSREAD, (uint32_t)ctx->thread_id, (uint32_t)n, (uint32_t)fd, ft_r0, ps3_ft_now());''',
     "perfdiag: cellFsRead span")
edit("runtime/syscalls/sys_fs.c",
     '''#include "../memory/vm.h"''',
     '''#include "../memory/vm.h"
#include "../../include/ps3emu/ps3_ftrace.h"   /* PS3_FTRACE: file read spans */''',
     "perfdiag: sys_fs include")
edit("runtime/syscalls/sys_fs.c",
     '''    size_t nread = fread(buf, 1, (size_t)size, f->fp);''',
     '''    const uint64_t ft_r0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    size_t nread = fread(buf, 1, (size_t)size, f->fp);
    if (ft_r0) ps3_ft_span(PS3_FT_FSREAD, (uint32_t)ctx->thread_id, (uint32_t)nread, (uint32_t)fd, ft_r0, ps3_ft_now());''',
     "perfdiag: sys_fs_read span")

# ---- Vulkan: every flush is a full GPU wait; count them by call site, always (not only in a trace) ----
edit("libs/video/rsx_vulkan_backend.c",
     '''static int vk_submit_and_wait_at(int line)
{''',
     '''/* "[vk] flush sites" every 10 s: each vk_flush / present is a submit and a wait for the GPU to
 * finish everything, so how many a second and from where is most of the CPU<->GPU picture.
 * The RSX thread is the only caller. */
static void vk_flush_note(int line, uint64_t wait_ns)
{
    enum { N = 48 };
    static struct { int line; unsigned n; uint64_t ns; } s[N];
    static uint64_t t0;
    const uint64_t now = ps3_ft_now();
    if (!t0) t0 = now;
    int i = 0;
    while (i < N && s[i].n && s[i].line != line) i++;
    if (i < N) { s[i].line = line; s[i].n++; s[i].ns += wait_ns; }
    if (now - t0 < 10000000000ull) return;
    const double secs = (double)(now - t0) / 1e9;
    unsigned tot = 0; uint64_t tns = 0;
    for (int k = 0; k < N && s[k].n; k++) { tot += s[k].n; tns += s[k].ns; }
    fprintf(stderr, "[vk] flush sites: %.1f/s, GPU wait %.1f ms/s:", tot / secs, tns / 1e6 / secs);
    for (int r = 0; r < 10; r++) {
        int b = -1;
        for (int k = 0; k < N && s[k].n; k++) if (s[k].line >= 0 && (b < 0 || s[k].ns > s[b].ns)) b = k;
        if (b < 0) break;
        fprintf(stderr, " line %d %.1f/s %.1f ms/s;", s[b].line, s[b].n / secs, s[b].ns / 1e6 / secs);
        s[b].line = -1 - s[b].line;   /* printed */
    }
    fputc('\\n', stderr);
    memset(s, 0, sizeof s);
    t0 = now;
}

static int vk_submit_and_wait_at(int line)
{''',
     "perfdiag: flush note")
edit("libs/video/rsx_vulkan_backend.c",
     '''    const uint64_t ft0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    VK_CHECK(pvkWaitForFences(s_vk.device, 1, &s_vk.fence, VK_TRUE, UINT64_MAX), "vkWaitForFences");
    if (ft0) ps3_ft_span(PS3_FT_GPU_WAIT, 0, s_force ? 0u : 1u,
                         (uint32_t)line, ft0, ps3_ft_now());''',
     '''    const uint64_t ft0 = ps3_ft_now();
    VK_CHECK(pvkWaitForFences(s_vk.device, 1, &s_vk.fence, VK_TRUE, UINT64_MAX), "vkWaitForFences");
    const uint64_t ft1 = ps3_ft_now();
    if (PS3_FT_ON()) ps3_ft_span(PS3_FT_GPU_WAIT, 0, s_force ? 0u : 1u, (uint32_t)line, ft0, ft1);
    vk_flush_note(line, ft1 - ft0);''',
     "perfdiag: flush wait")
edit("libs/video/rsx_vulkan_backend.c",
     '''    pvkWaitForFences(s_vk.device, 1, &s_vk.fence, VK_TRUE, UINT64_MAX);

    VkPresentInfoKHR pi = {''',
     '''    {   const uint64_t pw0 = ps3_ft_now();
        pvkWaitForFences(s_vk.device, 1, &s_vk.fence, VK_TRUE, UINT64_MAX);
        const uint64_t pw1 = ps3_ft_now();
        if (PS3_FT_ON()) ps3_ft_span(PS3_FT_GPU_WAIT, 0, 1u, (uint32_t)__LINE__, pw0, pw1);
        vk_flush_note(__LINE__, pw1 - pw0); }

    VkPresentInfoKHR pi = {''',
     "perfdiag: present wait")
# ---- shader stalls: time SPIR-V cache misses (and keep slow ones' HLSL), time the driver's pipeline builds ----
edit("libs/video/rsx_shader_spirv.cpp",
     '''#include <vector>
#include <unistd.h>''',
     '''#include <vector>
#include <unistd.h>
#include <chrono>
#include "../../include/ps3emu/ps3_ftrace.h"   /* PS3_FTRACE: who = 5 a SPIR-V cache miss compiled */''',
     "perfdiag: spirv include")
edit("libs/video/rsx_shader_spirv.cpp",
     '''    const int rc = rsx_hlsl_to_spirv_compile(hlsl, stage, words, max_words, out_words, log, log_size);
    if (rc == 0 && *out_words) {''',
     '''    /* A miss: compile it, and say so ("[spv] miss" lines; the slow ones' HLSL to
     * PS3RECOMP_SPIRV_MISS_DIR/<key>.hlsl, so text that differs run to run -- a cache that
     * never hits -- can be diffed). */
    const auto m0 = std::chrono::steady_clock::now();
    const uint64_t ft_m0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    const int rc = rsx_hlsl_to_spirv_compile(hlsl, stage, words, max_words, out_words, log, log_size);
    if (ft_m0) ps3_ft_span(PS3_FT_COMPILE, 5, rc == 0, (uint32_t)strlen(hlsl), ft_m0, ps3_ft_now());
    {   const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - m0).count();
        static int said = 0;
        if (said < 3000) { said++;
            fprintf(stderr, "[spv] miss %016llx %s %zu chars: %.1f ms%s\\n", spv_cache_key(hlsl, stage, rcp),
                    stage == RSX_SHADER_STAGE_VERTEX ? "vs" : "fs", strlen(hlsl), ms, rc ? " (failed)" : ""); }
        static const char* mdir = (const char*)-1;
        if (mdir == (const char*)-1) { mdir = getenv("PS3RECOMP_SPIRV_MISS_DIR"); if (mdir && !*mdir) mdir = nullptr; }
        static int kept = 0;
        if (mdir && ms > 50.0 && kept < 200) {
            char hp[1100];
            snprintf(hp, sizeof hp, "%s/%016llx.hlsl", mdir, spv_cache_key(hlsl, stage, rcp));
            if (FILE* f = fopen(hp, "wb")) { fputs(hlsl, f); fclose(f); kept++; }
        } }
    if (rc == 0 && *out_words) {''',
     "perfdiag: spirv miss timing")
edit("libs/video/rsx_vulkan_backend.c",
     '''    if (pvkCreateGraphicsPipelines(s_vk.device, VK_NULL_HANDLE, 1, &gci, NULL,
                                   &P->variant[topo_idx]) != VK_SUCCESS) {
        VK_LOG("engine: vkCreateGraphicsPipelines failed\\n");
        P->variant[topo_idx] = VK_NULL_HANDLE;
    }
    return P->variant[topo_idx];''',
     '''    const uint64_t pc0 = ps3_ft_now();
    if (pvkCreateGraphicsPipelines(s_vk.device, VK_NULL_HANDLE, 1, &gci, NULL,
                                   &P->variant[topo_idx]) != VK_SUCCESS) {
        VK_LOG("engine: vkCreateGraphicsPipelines failed\\n");
        P->variant[topo_idx] = VK_NULL_HANDLE;
    }
    {   /* the driver's pipeline build (RADV/ACO, the Mesa disk cache), at the first draw that needs it */
        const uint64_t pc1 = ps3_ft_now();
        if (PS3_FT_ON()) ps3_ft_span(PS3_FT_COMPILE, 6, P->variant[topo_idx] != VK_NULL_HANDLE, topo_idx, pc0, pc1);
        static unsigned n; static uint64_t ns, t0;
        n++; ns += pc1 - pc0;
        if (!t0) t0 = pc1;
        if (pc1 - pc0 > 50000000ull) VK_LOG("engine: pipeline build took %.0f ms (topology %u)\\n", (pc1 - pc0) / 1e6, topo_idx);
        if (pc1 - t0 > 10000000000ull) {
            if (n) VK_LOG("engine: %u pipeline builds in %.0f s, %.0f ms in all\\n", n, (pc1 - t0) / 1e9, ns / 1e6);
            n = 0; ns = 0; t0 = pc1;
        } }
    return P->variant[topo_idx];''',
     "perfdiag: pipeline build timing")
# vk vcache: the engine's vertex cache on Vulkan (vbuf hooks), present readback only when needed, bigger ring
edit("libs/video/rsx_vulkan_backend.c",
     '''#define VK_RING_BYTES   (128u << 20)
#define VK_DPOOL_SETS   4096u''',
     '''/* 128 MB / 4096 sets filled up once a frame in the console's inFAMOUS worlds, and each time is a
 * vk_flush: a submission and a wait for the GPU in the middle of the frame. */
#define VK_RING_BYTES   (256u << 20)
#define VK_DPOOL_SETS   16384u''',
     "vk vcache: ring size")
edit("libs/video/rsx_vulkan_backend.c",
     '''    VkDeviceSize vs_off, ps_off;
    void* v = vk_ring_alloc(vbytes, 16, voff);
    memcpy(v, vertices, (size_t)vbytes);''',
     '''    VkDeviceSize vs_off, ps_off;
    void* v = vk_ring_alloc(vbytes, 16, voff);
    if (vbytes) memcpy(v, vertices, (size_t)vbytes);   /* 0: a cached vertex buffer (draw_vbuf) */''',
     "vk vcache: ring skip")

# vk_eng_draw -> vk_eng_draw_from with an optional vertex buffer of the engine's vertex cache
edit("libs/video/rsx_vulkan_backend.c",
     '''static void vk_eng_draw(void* user, rsx_topology topology, const void* vertices, u32 vertex_count,
                        u32 stride, const u32* indices, u32 index_count)
{
    (void)user;
    if (!s_e2.pipeline || !vertices || !vertex_count || !stride) return;''',
     '''static void vk_eng_draw_from(void* user, rsx_topology topology, const void* vertices, u32 vertex_count,
                             u32 stride, const u32* indices, u32 index_count, VkBuffer xbuf, VkDeviceSize xoff);
static void vk_eng_draw(void* user, rsx_topology topology, const void* vertices, u32 vertex_count,
                        u32 stride, const u32* indices, u32 index_count)
{
    vk_eng_draw_from(user, topology, vertices, vertex_count, stride, indices, index_count, VK_NULL_HANDLE, 0);
}

/* The engine's vertex cache (rsx_draw_engine.c, PS3RECOMP_ENG_VCACHE): decoded vertices of
 * geometry that did not change between frames live in persistent buffers and are drawn from there,
 * not fetched, decoded and copied into the ring again every frame. Without these hooks the cache
 * stayed off on Vulkan. Buffers are carved from 32 MB host-visible slabs (one allocation each, not
 * one per mesh); a slab is freed when its last buffer is released, through vk_destroy_buffer, which
 * keeps it until the batch that may still draw from it is submitted. */
#define VK_VB_SLAB   (32u << 20)
#define VK_VB_SLABS  256u
#define VK_VB_MAX    65536u
static struct { vk_buffer b; VkDeviceSize used; u32 live; } s_vbslab[VK_VB_SLABS];
static u32 s_vbslab_cur = VK_VB_SLABS;           /* the slab new buffers come from */
static struct { u32 slab; VkDeviceSize off; } s_vbh[VK_VB_MAX];
static u32 s_vbh_free[VK_VB_MAX], s_vbh_nfree, s_vbh_n;

static void vk_vb_slab_drop(u32 s)
{
    vk_destroy_buffer(&s_vbslab[s].b);
    s_vbslab[s].used = 0; s_vbslab[s].live = 0;
    if (s_vbslab_cur == s) s_vbslab_cur = VK_VB_SLABS;
}

static u32 vk_eng_vbuf_create(void* user, const void* data, u32 bytes)
{
    (void)user;
    if (!s_vk.device || !data || !bytes) return 0;
    const VkDeviceSize need = ((VkDeviceSize)bytes + 255u) & ~(VkDeviceSize)255u;
    u32 s = s_vbslab_cur;
    if (s >= VK_VB_SLABS || !s_vbslab[s].b.buf || s_vbslab[s].used + need > s_vbslab[s].b.size) {
        s = VK_VB_SLABS;
        for (u32 i = 0; i < VK_VB_SLABS; i++) if (!s_vbslab[i].b.buf) { s = i; break; }
        if (s == VK_VB_SLABS) return 0;
        const VkDeviceSize size = need > VK_VB_SLAB ? need : VK_VB_SLAB;
        if (vk_create_host_buffer(&s_vbslab[s].b, size, VK_BUFFER_USAGE_VERTEX_BUFFER_BIT) || !s_vbslab[s].b.coherent) {
            if (s_vbslab[s].b.buf) vk_destroy_buffer(&s_vbslab[s].b);
            memset(&s_vbslab[s], 0, sizeof s_vbslab[s]);
            return 0;
        }
        s_vbslab[s].used = 0; s_vbslab[s].live = 0;
        if (need <= VK_VB_SLAB) s_vbslab_cur = s;    /* an outsized one stays its buffer's alone */
    }
    u32 h;
    if (s_vbh_nfree) h = s_vbh_free[--s_vbh_nfree];
    else if (s_vbh_n < VK_VB_MAX) h = s_vbh_n++;
    else return 0;
    s_vbh[h].slab = s; s_vbh[h].off = s_vbslab[s].used;
    memcpy((u8*)s_vbslab[s].b.ptr + s_vbslab[s].used, data, bytes);
    s_vbslab[s].used += need;
    s_vbslab[s].live++;
    return h + 1u;
}

static void vk_eng_vbuf_release(void* user, u32 vbuf)
{
    (void)user;
    if (!vbuf || vbuf > s_vbh_n) return;
    const u32 h = vbuf - 1u, s = s_vbh[h].slab;
    if (s >= VK_VB_SLABS || !s_vbslab[s].b.buf) return;
    s_vbh[h].slab = VK_VB_SLABS;
    s_vbh_free[s_vbh_nfree++] = h;
    if (s_vbslab[s].live && --s_vbslab[s].live == 0) vk_vb_slab_drop(s);
}

static void vk_eng_draw_vbuf(void* user, rsx_topology topology, u32 vbuf, u32 vertex_count, u32 stride,
                             const u32* indices, u32 index_count)
{
    if (!vbuf || vbuf > s_vbh_n) return;
    const u32 s = s_vbh[vbuf - 1u].slab;
    if (s >= VK_VB_SLABS || !s_vbslab[s].b.buf) return;
    vk_eng_draw_from(user, topology, NULL, vertex_count, stride, indices, index_count,
                     s_vbslab[s].b.buf, s_vbh[vbuf - 1u].off);
}

static void vk_eng_draw_from(void* user, rsx_topology topology, const void* vertices, u32 vertex_count,
                             u32 stride, const u32* indices, u32 index_count, VkBuffer xbuf, VkDeviceSize xoff)
{
    (void)user;
    if (!s_e2.pipeline || (!vertices && !xbuf) || !vertex_count || !stride) return;''',
     "vk vcache: draw_from")
edit("libs/video/rsx_vulkan_backend.c",
     '''    const VkDeviceSize vbytes = (VkDeviceSize)vertex_count * stride;
    VkBuffer vbuf, ibuf;
    VkDeviceSize voff = 0, ioff = 0;
    if (vk_batching()) {
        if (vk_batch_draw_begin(vertices, vbytes, indices,
                                (indices && index_count) ? (VkDeviceSize)index_count * 4u : 0, &voff, &ioff))
            return;
        vbuf = ibuf = s_ring.buf;
    } else {
        if (vk_ensure_vertex_buffer(vbytes)) return;
        memcpy(s_vk.vertices.ptr, vertices, (size_t)vbytes);''',
     '''    const VkDeviceSize vbytes = xbuf ? 0 : (VkDeviceSize)vertex_count * stride;
    VkBuffer vbuf, ibuf;
    VkDeviceSize voff = 0, ioff = 0;
    if (vk_batching()) {
        if (vk_batch_draw_begin(vertices, vbytes, indices,
                                (indices && index_count) ? (VkDeviceSize)index_count * 4u : 0, &voff, &ioff))
            return;
        vbuf = ibuf = s_ring.buf;
        if (xbuf) { vbuf = xbuf; voff = xoff; }
    } else if (xbuf) {
        if (indices && index_count) {
            if (vk_eng_ensure_indices((VkDeviceSize)index_count * 4u)) return;
            memcpy(s_e2.indices.ptr, indices, (size_t)index_count * 4u);
        }
        vk_eng_write_descriptors();
        vbuf = xbuf; voff = xoff; ibuf = s_e2.indices.buf;
    } else {
        if (vk_ensure_vertex_buffer(vbytes)) return;
        memcpy(s_vk.vertices.ptr, vertices, (size_t)vbytes);''',
     "vk vcache: draw_from body")
edit("libs/video/rsx_vulkan_backend.c",
     '''    .draw                 = vk_eng_draw,''',
     '''    .draw                 = vk_eng_draw,
    .vbuf_create          = vk_eng_vbuf_create,
    .vbuf_release         = vk_eng_vbuf_release,
    .draw_vbuf            = vk_eng_draw_vbuf,''',
     "vk vcache: hooks")

# present: the whole frame was copied to the CPU and waited for every frame, for one diagnostic pixel
edit("libs/video/rsx_vulkan_backend.c",
     '''static void vk_dump_ppm(const unsigned char* rgba)
{
    static double every = -1;
    static unsigned long long last_ns;''',
     '''static unsigned long long s_dump_last_ns;
/* Whether this present reads the frame back: always headless (the readback is the output) or with a
 * per-frame dump; in a window only when a timed dump or the debug server's shot is due, and every
 * 64th frame so last_center stays roughly current. Every other window present skips a full copy of
 * the frame and a wait for the GPU. */
static int vk_readback_due(void)
{
    if (!s_vk.windowed || !s_vk.swapchain) return 1;
    if ((s_vk.presented & 63u) == 0 || g_vk_dump_now) return 1;
    if (!s_vk.dump_path) return 0;
    static double every = -1;
    if (every < 0) { const char* e = getenv("PS3RECOMP_VK_DUMP_EVERY"); every = e ? atof(e) : 0; }
    if (every <= 0) return 1;
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    const unsigned long long now = (unsigned long long)ts.tv_sec * 1000000000ull + (unsigned long long)ts.tv_nsec;
    return !s_dump_last_ns || now - s_dump_last_ns >= (unsigned long long)(every * 1e9);
}
static void vk_dump_ppm(const unsigned char* rgba)
{
    static double every = -1;
#define last_ns s_dump_last_ns''',
     "vk vcache: readback due")
edit("libs/video/rsx_vulkan_backend.c",
     '''        snprintf(path, sizeof path, "%s.%03u.ppm", s_vk.dump_path, seq++ % 200u);''',
     '''        snprintf(path, sizeof path, "%s.%03u.ppm", s_vk.dump_path, seq++ % 200u);
#undef last_ns''',
     "vk vcache: readback due end")
edit("libs/video/rsx_vulkan_backend.c",
     '''    (void)ud; (void)buffer_id;
    if (!s_vk.device) return;

    if (vk_begin()) return;
    vk_barrier_image(s_vk.color.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);''',
     '''    (void)ud; (void)buffer_id;
    if (!s_vk.device) return;

    if (!vk_readback_due()) {
        s_vk.presented++;
        s_g.last_draws = s_g.draws;
        s_g.draws = 0;
        vk_present_window();
        return;
    }
    if (vk_begin()) return;
    vk_barrier_image(s_vk.color.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);''',
     "vk vcache: present skip")
# slow pipe: split a slow engine pipeline miss into vp decompile / fp decompile+patches / backend build
edit("libs/video/rsx_draw_engine.c",
     '''    const uint64_t ft_c0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    u32 handle = 0;
    int vi = 1, fi = 1;''',
     '''    const uint64_t ft_c0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    /* A miss over 100 ms says where it went ("[rsx engine] slow pipeline" lines): inFAMOUS 2's
     * cutscenes stalled 0.8-1.9 s in single misses whose SPIR-V compile took 10 ms. */
    const uint64_t sp0 = ps3_ft_now();
    uint64_t sp_vp = sp0, sp_fp = sp0;
    u32 handle = 0;
    int vi = 1, fi = 1;''',
     "slow pipe: start")
edit("libs/video/rsx_draw_engine.c",
     '''        fi = rsx_fp_decompile_buffered_shadow_color_expand_vol_ex(fp_uc, fp_size, fp_ctrl, cube_mask, vol_mask,''',
     '''        sp_vp = ps3_ft_now();
        fi = rsx_fp_decompile_buffered_shadow_color_expand_vol_ex(fp_uc, fp_size, fp_ctrl, cube_mask, vol_mask,''',
     "slow pipe: vp done")
edit("libs/video/rsx_draw_engine.c",
     '''    if (vi > 0 && fi > 0)
        handle = g.be->pipeline_create(g.be->user, s_vs_hlsl, s_ps_hlsl, rs,''',
     '''    sp_fp = ps3_ft_now();
    if (sp_vp == sp0) sp_vp = sp_fp;   /* the fixed-function pair: no decompile */
    if (vi > 0 && fi > 0)
        handle = g.be->pipeline_create(g.be->user, s_vs_hlsl, s_ps_hlsl, rs,''',
     "slow pipe: fp done")
edit("libs/video/rsx_draw_engine.c",
     '''    if (ft_c0) ps3_ft_span(PS3_FT_COMPILE, 0, handle != 0, 0, ft_c0, ps3_ft_now());''',
     '''    if (ft_c0) ps3_ft_span(PS3_FT_COMPILE, 0, handle != 0, 0, ft_c0, ps3_ft_now());
    {   const uint64_t sp1 = ps3_ft_now();
        static u32 said;
        if (sp1 - sp0 > 100000000ull && said < 200) { said++;
            fprintf(stderr, "[rsx engine] slow pipeline miss %.0f ms: vp decompile %.0f ms (%u instrs, %zu chars), "
                            "fp decompile+patches %.0f ms (%u bytes, %zu chars), backend %.0f ms%s\\n",
                    (sp1 - sp0) / 1e6, (sp_vp - sp0) / 1e6, (unsigned)vp_instrs, strlen(s_vs_hlsl),
                    (sp_fp - sp_vp) / 1e6, (unsigned)fp_size, strlen(s_ps_hlsl), (sp1 - sp_fp) / 1e6,
                    handle ? "" : " (failed)"); } }''',
     "slow pipe: report")
# vk async: two frames in flight -- a window present submits the frame and goes on recording the next
VKF = "libs/video/rsx_vulkan_backend.c"
edit(VKF,
     '''static VkDescriptorSet  s_wd_set;               /* this draw's set / ring slice, or 0      */''',
     '''/* Frames in flight (PS3RECOMP_VK_ASYNC=0 turns it off): a window present submits the frame and the
 * next one is recorded while the GPU draws it, instead of the CPU waiting for the GPU at every
 * present (a quarter to a third of the console's frame time in all three games). What a submission
 * uses that the CPU writes or frees -- command buffer, fence, acquire semaphore, ring, descriptor
 * pool, the objects released while it was recorded -- belongs to one of two slots; a present waits
 * only for the older slot, and a forced flush (the engine reading results) still waits for all. */
#define VK_SLOTS 2
typedef struct { u8 kind; uint64_t h; } vk_gobj;   /* 1 pipeline, 2 shader module, 3 framebuffer */
#define VK_GOBJ_MAX 4096
typedef struct {
    VkCommandBuffer cmd; VkFence fence; VkSemaphore acq;
    vk_buffer ring; VkDescriptorPool dpool;
    int pending;
    vk_buffer* gbuf; u32 ngbuf;
    vk_image* gimg; u32 ngimg;
    vk_gobj* gobj; u32 ngobj;
} vk_slot;
static vk_slot s_slot[VK_SLOTS];
static u32 s_cur;
static int s_inflight;                          /* the other slot is submitted and not waited for */
static int s_async_ready;                       /* slots set up */
static vk_gobj s_gobj[VK_GOBJ_MAX];
static u32 s_ngobj;
static VkDescriptorSet  s_wd_set;               /* this draw's set / ring slice, or 0      */''',
     "vk async: slots")

edit(VKF,
     '''    if (s_rec && vk_batching() && s_ngimg < VK_GARBAGE_MAX && (im->img || im->view)) {''',
     '''    if ((s_rec || s_inflight) && vk_batching() && s_ngimg < VK_GARBAGE_MAX && (im->img || im->view)) {''',
     "vk async: image garbage")
edit(VKF,
     '''    if (s_rec && vk_batching() && s_ngbuf < VK_GARBAGE_MAX && b->buf) {''',
     '''    if ((s_rec || s_inflight) && vk_batching() && s_ngbuf < VK_GARBAGE_MAX && b->buf) {''',
     "vk async: buffer garbage")

edit(VKF,
     '''    s_ngimg = 0;
    s_ring_off = 0;
    if (s_dpool && s_dsets) { pvkResetDescriptorPool(s_vk.device, s_dpool, 0); s_dsets = 0; }
}''',
     '''    s_ngimg = 0;
    vk_gobj_free(s_gobj, &s_ngobj);
    s_ring_off = 0;
    if (s_dpool && s_dsets) { pvkResetDescriptorPool(s_vk.device, s_dpool, 0); s_dsets = 0; }
}

/* A slot whose submission has completed: free what was released while it was recorded. */
static void vk_slot_free(vk_slot* S)
{
    for (u32 i = 0; i < S->ngbuf; i++) {
        vk_buffer* b = &S->gbuf[i];
        if (b->ptr) pvkUnmapMemory(s_vk.device, b->mem);
        if (b->buf) pvkDestroyBuffer(s_vk.device, b->buf, NULL);
        if (b->mem) pvkFreeMemory(s_vk.device, b->mem, NULL);
    }
    S->ngbuf = 0;
    for (u32 i = 0; i < S->ngimg; i++) {
        vk_image* im = &S->gimg[i];
        if (im->view) pvkDestroyImageView(s_vk.device, im->view, NULL);
        if (im->img)  pvkDestroyImage(s_vk.device, im->img, NULL);
        if (im->mem)  pvkFreeMemory(s_vk.device, im->mem, NULL);
    }
    S->ngimg = 0;
    vk_gobj_free(S->gobj, &S->ngobj);
    S->pending = 0;
}

/* The other slot's submission is complete (a wait for a later one returned, or its own fence). */
static void vk_slots_retire(void)
{
    for (u32 i = 0; i < VK_SLOTS; i++)
        if (i != s_cur && s_slot[i].pending) vk_slot_free(&s_slot[i]);
    s_inflight = 0;
}''',
     "vk async: slot free")

# vk_gobj_free has to come before vk_batch_after_flush
edit(VKF,
     '''/* After a real submission: free what was released while recording, restart the ring and pool. */''',
     '''static void vk_gobj_free(vk_gobj* g, u32* n)
{
    for (u32 i = 0; i < *n; i++) {
        if (g[i].kind == 1) pvkDestroyPipeline(s_vk.device, (VkPipeline)(uintptr_t)g[i].h, NULL);
        else if (g[i].kind == 2) pvkDestroyShaderModule(s_vk.device, (VkShaderModule)(uintptr_t)g[i].h, NULL);
        else if (g[i].kind == 3) pvkDestroyFramebuffer(s_vk.device, (VkFramebuffer)(uintptr_t)g[i].h, NULL);
    }
    *n = 0;
}

/* A pipeline, shader module or framebuffer the open command buffer or a submission in flight may still
 * use: destroyed once that is complete, like vk_destroy_image. 0: destroy it now. */
static int vk_gobj_defer(u8 kind, uint64_t h)
{
    if (!h || !((s_rec || s_inflight) && vk_batching()) || s_ngobj >= VK_GOBJ_MAX) return 0;
    s_gobj[s_ngobj].kind = kind; s_gobj[s_ngobj].h = h; s_ngobj++;
    return 1;
}

/* After a real submission: free what was released while recording, restart the ring and pool. */''',
     "vk async: gobj")

edit(VKF,
     '''static int vk_submit_and_wait_at(int line)
{
    if (!s_rec) return 0;''',
     '''static int vk_submit_and_wait_at(int line)
{
    if (!s_rec) {
        /* Nothing recorded, but the engine may be about to read what an in-flight frame wrote. */
        if (s_force && s_inflight) {
            const uint64_t ft0 = ps3_ft_now();
            for (u32 i = 0; i < VK_SLOTS; i++)
                if (i != s_cur && s_slot[i].pending)
                    pvkWaitForFences(s_vk.device, 1, &s_slot[i].fence, VK_TRUE, UINT64_MAX);
            const uint64_t ft1 = ps3_ft_now();
            if (PS3_FT_ON()) ps3_ft_span(PS3_FT_GPU_WAIT, 0, 0u, (uint32_t)line, ft0, ft1);
            vk_flush_note(line, ft1 - ft0);
            vk_slots_retire();
        }
        return 0;
    }''',
     "vk async: idle forced flush")
edit(VKF,
     '''    if (PS3_FT_ON()) ps3_ft_span(PS3_FT_GPU_WAIT, 0, s_force ? 0u : 1u, (uint32_t)line, ft0, ft1);
    vk_flush_note(line, ft1 - ft0);
    vk_batch_after_flush();
    return 0;
}''',
     '''    if (PS3_FT_ON()) ps3_ft_span(PS3_FT_GPU_WAIT, 0, s_force ? 0u : 1u, (uint32_t)line, ft0, ft1);
    vk_flush_note(line, ft1 - ft0);
    if (s_inflight) vk_slots_retire();          /* the queue is in order: older work is done too */
    vk_batch_after_flush();
    return 0;
}''',
     "vk async: flush retires")

# the asynchronous window present
edit(VKF,
     '''/* Blit the offscreen target into the next swapchain image and present it. */
static void vk_present_window(void)
{
    if (!s_vk.windowed || !s_vk.swapchain) return;
''',
     '''static int vk_async(void)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3RECOMP_VK_ASYNC"); on = !(e && e[0] == '0'); }
    return on && vk_batching() && s_vk.windowed && s_vk.swapchain;
}

static int vk_async_setup(void)
{
    if (s_async_ready) return s_async_ready > 0;
    s_async_ready = -1;
    for (u32 i = 0; i < VK_SLOTS; i++) {
        vk_slot* S = &s_slot[i];
        S->gbuf = (vk_buffer*)calloc(VK_GARBAGE_MAX, sizeof *S->gbuf);
        S->gimg = (vk_image*)calloc(VK_GARBAGE_MAX, sizeof *S->gimg);
        S->gobj = (vk_gobj*)calloc(VK_GOBJ_MAX, sizeof *S->gobj);
        if (!S->gbuf || !S->gimg || !S->gobj) { VK_LOG("async: out of memory\\n"); return 0; }
        if (i == 0) { S->cmd = s_vk.cmd; S->fence = s_vk.fence; S->acq = s_vk.sem_acquire; continue; }
        VkCommandBufferAllocateInfo cai = { .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
                                            .commandPool = s_vk.pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
                                            .commandBufferCount = 1 };
        VkFenceCreateInfo fci = { .sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO };
        VkSemaphoreCreateInfo semi = { .sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO };
        if (pvkAllocateCommandBuffers(s_vk.device, &cai, &S->cmd) != VK_SUCCESS ||
            pvkCreateFence(s_vk.device, &fci, NULL, &S->fence) != VK_SUCCESS ||
            pvkCreateSemaphore(s_vk.device, &semi, NULL, &S->acq) != VK_SUCCESS) {
            VK_LOG("async: no second command buffer / fence / semaphore; presents stay synchronous\\n");
            return 0;
        }
    }
    s_cur = 0;
    s_async_ready = 1;
    VK_LOG("async: %u frames in flight\\n", VK_SLOTS);
    return 1;
}

/* After an asynchronous present: the frame just submitted keeps its slot; recording moves to the other
 * one, once its older submission is complete. */
static void vk_slot_rotate(void)
{
    vk_slot* S = &s_slot[s_cur];
    S->ring = s_ring; S->dpool = s_dpool;
    memcpy(S->gbuf, s_gbuf, s_ngbuf * sizeof *s_gbuf); S->ngbuf = s_ngbuf; s_ngbuf = 0;
    memcpy(S->gimg, s_gimg, s_ngimg * sizeof *s_gimg); S->ngimg = s_ngimg; s_ngimg = 0;
    memcpy(S->gobj, s_gobj, s_ngobj * sizeof *s_gobj); S->ngobj = s_ngobj; s_ngobj = 0;
    S->pending = 1;
    s_cur = (s_cur + 1u) % VK_SLOTS;
    vk_slot* N = &s_slot[s_cur];
    if (N->pending) {
        const uint64_t w0 = ps3_ft_now();
        pvkWaitForFences(s_vk.device, 1, &N->fence, VK_TRUE, UINT64_MAX);
        const uint64_t w1 = ps3_ft_now();
        if (PS3_FT_ON()) ps3_ft_span(PS3_FT_GPU_WAIT, 0, 1u, (uint32_t)__LINE__, w0, w1);
        vk_flush_note(__LINE__, w1 - w0);
        vk_slot_free(N);
    }
    s_inflight = 1;
    s_vk.cmd = N->cmd; s_vk.fence = N->fence; s_vk.sem_acquire = N->acq;
    s_ring = N->ring; s_dpool = N->dpool;
    s_ring_off = 0;
    if (s_dpool) pvkResetDescriptorPool(s_vk.device, s_dpool, 0);
    s_dsets = 0;
}

/* Blit the offscreen target into the next swapchain image and present it. */
static void vk_present_window(void)
{
    if (!s_vk.windowed || !s_vk.swapchain) return;
    const int async = vk_async() && vk_async_setup();
''',
     "vk async: present setup")
edit(VKF,
     '''        VK_LOG("vkAcquireNextImageKHR failed (VkResult %d)\\n", (int)r); return;
    }

    vk_flush();
    if (vk_begin()) return;''',
     '''        VK_LOG("vkAcquireNextImageKHR failed (VkResult %d)\\n", (int)r); return;
    }

    if (!async) vk_flush();                    /* async: the frame goes in this submission */
    if (vk_begin()) return;''',
     "vk async: present no flush")
edit(VKF,
     '''    pvkResetFences(s_vk.device, 1, &s_vk.fence);
    if (pvkQueueSubmit(s_vk.queue, 1, &si, s_vk.fence) != VK_SUCCESS) {
        VK_LOG("vkQueueSubmit (window) failed\\n"); return;
    }
    {   const uint64_t pw0 = ps3_ft_now();''',
     '''    pvkResetFences(s_vk.device, 1, &s_vk.fence);
    if (pvkQueueSubmit(s_vk.queue, 1, &si, s_vk.fence) != VK_SUCCESS) {
        VK_LOG("vkQueueSubmit (window) failed\\n"); return;
    }
    if (async) {
        VkPresentInfoKHR api = {
            .sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR,
            .waitSemaphoreCount = 1, .pWaitSemaphores = &s_vk.sc_done[idx],
            .swapchainCount = 1, .pSwapchains = &s_vk.swapchain, .pImageIndices = &idx,
        };
        r = pvkQueuePresentKHR(s_vk.queue, &api);
        vk_slot_rotate();
        if (r == VK_ERROR_OUT_OF_DATE_KHR || r == VK_SUBOPTIMAL_KHR) vk_swapchain_lost();
        else if (r != VK_SUCCESS) VK_LOG("vkQueuePresentKHR failed (VkResult %d)\\n", (int)r);
        return;
    }
    {   const uint64_t pw0 = ps3_ft_now();''',
     "vk async: present submit")

# pipelines and framebuffers the GPU may still use
edit(VKF,
     '''    for (u32 i = 0; i < s_e2.fb_count; i++)
        if (s_e2.fb[i].fb) pvkDestroyFramebuffer(s_vk.device, s_e2.fb[i].fb, NULL);''',
     '''    for (u32 i = 0; i < s_e2.fb_count; i++)
        if (s_e2.fb[i].fb && !vk_gobj_defer(3, (uint64_t)(uintptr_t)s_e2.fb[i].fb))
            pvkDestroyFramebuffer(s_vk.device, s_e2.fb[i].fb, NULL);''',
     "vk async: fb defer")
edit(VKF,
     '''    for (u32 t = 0; t < VK_ENG_TOPOLOGIES; t++)
        if (P->variant[t]) pvkDestroyPipeline(s_vk.device, P->variant[t], NULL);
    if (P->vs) pvkDestroyShaderModule(s_vk.device, P->vs, NULL);
    if (P->fs) pvkDestroyShaderModule(s_vk.device, P->fs, NULL);
    memset(P, 0, sizeof *P);
    if (s_e2.pipeline == pipeline) s_e2.pipeline = 0;''',
     '''    for (u32 t = 0; t < VK_ENG_TOPOLOGIES; t++)
        if (P->variant[t] && !vk_gobj_defer(1, (uint64_t)(uintptr_t)P->variant[t]))
            pvkDestroyPipeline(s_vk.device, P->variant[t], NULL);
    if (P->vs && !vk_gobj_defer(2, (uint64_t)(uintptr_t)P->vs)) pvkDestroyShaderModule(s_vk.device, P->vs, NULL);
    if (P->fs && !vk_gobj_defer(2, (uint64_t)(uintptr_t)P->fs)) pvkDestroyShaderModule(s_vk.device, P->fs, NULL);
    memset(P, 0, sizeof *P);
    if (s_e2.pipeline == pipeline) s_e2.pipeline = 0;''',
     "vk async: pipe defer")
# spv memcache: the SPIR-V disk cache read into memory by a loader thread, misses written by a writer thread
SPV = "libs/video/rsx_shader_spirv.cpp"
edit(SPV,
     '''#include <vector>
#include <unistd.h>
#include <chrono>''',
     '''#include <vector>
#include <unistd.h>
#include <chrono>
#include <pthread.h>
#include <dirent.h>
#include <unordered_map>
#include <deque>
#include <string>''',
     "spv memcache: includes")
edit(SPV,
     '''extern "C" int rsx_hlsl_to_spirv(const char* hlsl, int stage,
                                 u32* words, u32 max_words, u32* out_words,
                                 char* log, u32 log_size)
{''',
     '''/* The disk cache in memory. On the console a cache lookup was an fopen/fread on the RSX thread, and
 * the file system there stalls for up to a second at times: inFAMOUS 2's single "slow pipeline miss"
 * stalls of 0.8-1 s were spent in the backend around a SPIR-V compile that took 5-8 ms. A loader thread
 * reads every <key>.spv once at start; until it is done a lookup still goes to disk. New entries are
 * written by a writer thread. */
namespace {
pthread_mutex_t s_spv_mu = PTHREAD_MUTEX_INITIALIZER;
pthread_cond_t  s_spv_cv = PTHREAD_COND_INITIALIZER;
std::unordered_map<unsigned long long, std::vector<u32>>* s_spv_mem;
std::deque<std::pair<std::string, std::vector<u32>>>* s_spv_wq;
volatile int s_spv_loaded;                 /* 1: every file on disk is in s_spv_mem */
char s_spv_dir[1024];

void* spv_loader(void*)
{
    const auto t0 = std::chrono::steady_clock::now();
    unsigned n = 0; size_t bytes = 0;
    if (DIR* d = opendir(s_spv_dir)) {
        std::vector<u32> buf(1u << 20);
        while (struct dirent* de = readdir(d)) {
            const char* nm = de->d_name;
            const size_t L = strlen(nm);
            if (L != 20 || strcmp(nm + 16, ".spv") != 0) continue;
            char path[1100];
            snprintf(path, sizeof path, "%s/%s", s_spv_dir, nm);
            FILE* f = fopen(path, "rb");
            if (!f) continue;
            const size_t w = fread(buf.data(), sizeof(u32), buf.size(), f);
            fclose(f);
            if (w <= 5 || buf[0] != 0x07230203u) continue;
            const unsigned long long key = strtoull(std::string(nm, 16).c_str(), nullptr, 16);
            pthread_mutex_lock(&s_spv_mu);
            (*s_spv_mem)[key].assign(buf.begin(), buf.begin() + w);
            pthread_mutex_unlock(&s_spv_mu);
            n++; bytes += w * 4u;
        }
        closedir(d);
    }
    s_spv_loaded = 1;
    fprintf(stderr, "[spv] cache: %u shaders (%zu KB) in memory in %.0f ms\\n", n, bytes >> 10,
            std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count());
    for (;;) {                             /* then the writer */
        pthread_mutex_lock(&s_spv_mu);
        while (s_spv_wq->empty()) pthread_cond_wait(&s_spv_cv, &s_spv_mu);
        auto job = std::move(s_spv_wq->front());
        s_spv_wq->pop_front();
        pthread_mutex_unlock(&s_spv_mu);
        char tmp[1200];
        snprintf(tmp, sizeof tmp, "%s.%d.tmp", job.first.c_str(), (int)getpid());
        if (FILE* f = fopen(tmp, "wb")) {
            const bool ok = fwrite(job.second.data(), sizeof(u32), job.second.size(), f) == job.second.size();
            fclose(f);
            if (!ok || rename(tmp, job.first.c_str()) != 0) remove(tmp);
        }
    }
    return nullptr;
}

/* 1: the memory cache is in use (started on the first lookup). */
int spv_mem_start(const char* dir)
{
    static int on = -1;
    if (on >= 0) return on;
    const char* e = getenv("PS3RECOMP_SPIRV_MEMCACHE");
    on = 0;
    if (e && e[0] == '0') return 0;
    snprintf(s_spv_dir, sizeof s_spv_dir, "%s", dir);
    s_spv_mem = new std::unordered_map<unsigned long long, std::vector<u32>>();
    s_spv_wq = new std::deque<std::pair<std::string, std::vector<u32>>>();
    pthread_t t;
    pthread_attr_t a;
    pthread_attr_init(&a);
    pthread_attr_setstacksize(&a, 256u << 10);
    if (pthread_create(&t, &a, spv_loader, nullptr) == 0) { pthread_detach(t); on = 1; }
    pthread_attr_destroy(&a);
    return on;
}
} // namespace

extern "C" int rsx_hlsl_to_spirv(const char* hlsl, int stage,
                                 u32* words, u32 max_words, u32* out_words,
                                 char* log, u32 log_size)
{''',
     "spv memcache: loader")
edit(SPV,
     '''    snprintf(path, sizeof path, "%s/%016llx.spv", dir, spv_cache_key(hlsl, stage, rcp));
    if (FILE* f = fopen(path, "rb")) {
        const size_t n = fread(words, sizeof(u32), max_words, f);
        fclose(f);
        if (n > 5 && words[0] == 0x07230203u) { *out_words = (u32)n; return 0; }
    }''',
     '''    const unsigned long long key = spv_cache_key(hlsl, stage, rcp);
    snprintf(path, sizeof path, "%s/%016llx.spv", dir, key);
    const int mem = spv_mem_start(dir);
    int on_disk_too = 1;
    if (mem) {
        pthread_mutex_lock(&s_spv_mu);
        auto it = s_spv_mem->find(key);
        const bool hit = it != s_spv_mem->end() && it->second.size() <= max_words;
        if (hit) { memcpy(words, it->second.data(), it->second.size() * sizeof(u32)); *out_words = (u32)it->second.size(); }
        pthread_mutex_unlock(&s_spv_mu);
        if (hit) return 0;
        on_disk_too = !s_spv_loaded;       /* still loading: it may be on disk */
    }
    if (on_disk_too) {
        const auto r0 = std::chrono::steady_clock::now();
        size_t n = 0;
        if (FILE* f = fopen(path, "rb")) {
            n = fread(words, sizeof(u32), max_words, f);
            fclose(f);
        }
        const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - r0).count();
        static int said;
        if (ms > 20.0 && said < 100) { said++; fprintf(stderr, "[spv] slow cache read %.0f ms\\n", ms); }
        if (n > 5 && words[0] == 0x07230203u) { *out_words = (u32)n; return 0; }
    }''',
     "spv memcache: lookup")
edit(SPV,
     '''    if (rc == 0 && *out_words) {
        char tmp[1100];
        snprintf(tmp, sizeof tmp, "%s.%d.tmp", path, (int)getpid());
        if (FILE* f = fopen(tmp, "wb")) {
            const bool ok = fwrite(words, sizeof(u32), *out_words, f) == *out_words;
            fclose(f);
            if (!ok || rename(tmp, path) != 0) remove(tmp);
        }
    }
    return rc;''',
     '''    if (rc == 0 && *out_words && mem) {
        pthread_mutex_lock(&s_spv_mu);
        (*s_spv_mem)[key].assign(words, words + *out_words);
        s_spv_wq->emplace_back(std::string(path), std::vector<u32>(words, words + *out_words));
        pthread_cond_signal(&s_spv_cv);
        pthread_mutex_unlock(&s_spv_mu);
    } else if (rc == 0 && *out_words) {
        char tmp[1100];
        snprintf(tmp, sizeof tmp, "%s.%d.tmp", path, (int)getpid());
        if (FILE* f = fopen(tmp, "wb")) {
            const bool ok = fwrite(words, sizeof(u32), *out_words, f) == *out_words;
            fclose(f);
            if (!ok || rename(tmp, path) != 0) remove(tmp);
        }
    }
    return rc;''',
     "spv memcache: write")

# guest file reads over 5 ms: how much is pre-faulting the buffer and how much is fread
edit("runtime/ppu/ppu_fs.cpp",
     '''    fs_prefault(buf, nbytes);
    const uint64_t ft_r0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    size_t n = fread(vm_base + buf, 1, (size_t)nbytes, g_files[fd]);   /* raw bytes, no swap */''',
     '''    const uint64_t sr0 = ps3_ft_now();
    fs_prefault(buf, nbytes);
    const uint64_t ft_r0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    const uint64_t sr1 = ps3_ft_now();
    size_t n = fread(vm_base + buf, 1, (size_t)nbytes, g_files[fd]);   /* raw bytes, no swap */
    {   const uint64_t sr2 = ps3_ft_now();
        static unsigned said;
        if (sr2 - sr0 > 5000000ull && said < 300) { said++;
            fprintf(stderr, "[fs] slow cellFsRead fd %d %zu bytes at %ld: prefault %.1f ms, fread %.1f ms\\n",
                    fd, n, fpos_before, (sr1 - sr0) / 1e6, (sr2 - sr1) / 1e6); } }''',
     "fs slow: cellFsRead")
edit("runtime/syscalls/sys_fs.c",
     '''    if (size) vm_commit(buf_addr, (uint32_t)size);
    const uint64_t ft_r0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    size_t nread = fread(buf, 1, (size_t)size, f->fp);''',
     '''    const uint64_t sr0 = ps3_ft_now();
    if (size) vm_commit(buf_addr, (uint32_t)size);
    const uint64_t ft_r0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    const uint64_t sr1 = ps3_ft_now();
    size_t nread = fread(buf, 1, (size_t)size, f->fp);
    {   const uint64_t sr2 = ps3_ft_now();
        static unsigned said;
        if (sr2 - sr0 > 5000000ull && said < 300) { said++;
            fprintf(stderr, "[fs] slow sys_fs_read fd %d %zu bytes at %ld: commit %.1f ms, fread %.1f ms\\n",
                    fd, nread, pos_before, (sr1 - sr0) / 1e6, (sr2 - sr1) / 1e6); } }''',
     "fs slow: sys_fs_read")
# vk rpmerge: consecutive engine draws into the same targets share one render pass, without a barrier each
VKF = "libs/video/rsx_vulkan_backend.c"
edit(VKF,
     '''static int vk_load_wsi_device_functions(void)
{
    VK_WSI_DEVICE_FNS(LOAD_D)
    return 0;
}''',
     '''static int vk_load_wsi_device_functions(void)
{
    VK_WSI_DEVICE_FNS(LOAD_D)
    return 0;
}

/* Render pass merging (PS3RECOMP_VK_RPMERGE=0 turns it off). Every engine draw was its own render
 * pass with LOAD/STORE and, before it, a full ALL_COMMANDS barrier on its targets: on the GPU a wait
 * for idle and a cache flush per draw, thousands a frame, so the console was GPU-bound in inFAMOUS 1
 * (looking at the sky, with few draws, ran at 20-30 fps). Now a draw into the same render pass,
 * framebuffer and area as the open one, sampling none of its targets, continues it. Every command
 * that may not be recorded inside a render pass closes the open one first: the macros below wrap
 * those entry points (they are loaded above, by name, before these exist). */
static int s_rp_open;                           /* an engine draw's render pass is open on s_vk.cmd */
static VkRenderPass  s_rp_rp;
static VkFramebuffer s_rp_fb;
static u32           s_rp_w, s_rp_h;
static unsigned      s_rp_begun, s_rp_draws;
static int vk_rp_close(void)
{
    if (s_rp_open) { s_rp_open = 0; pvkCmdEndRenderPass(s_vk.cmd); }
    return 0;
}
static int vk_rp_merge(void)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3RECOMP_VK_RPMERGE"); on = !(e && e[0] == '0'); }
    return on;
}
#define pvkCmdPipelineBarrier       (vk_rp_close(), pvkCmdPipelineBarrier)
#define pvkCmdClearColorImage       (vk_rp_close(), pvkCmdClearColorImage)
#define pvkCmdClearDepthStencilImage (vk_rp_close(), pvkCmdClearDepthStencilImage)
#define pvkCmdCopyImageToBuffer     (vk_rp_close(), pvkCmdCopyImageToBuffer)
#define pvkCmdCopyBufferToImage     (vk_rp_close(), pvkCmdCopyBufferToImage)
#define pvkCmdCopyImage             (vk_rp_close(), pvkCmdCopyImage)
#define pvkCmdBlitImage             (vk_rp_close(), pvkCmdBlitImage)
#define pvkCmdBeginRenderPass       (vk_rp_close(), pvkCmdBeginRenderPass)
#define pvkEndCommandBuffer         (vk_rp_close(), pvkEndCommandBuffer)''',
     "vk rpmerge: close")

edit(VKF,
     '''    if (vk_begin()) return;
    /* Everything submitted before is complete (each submission is waited
     * on); this orders memory for the surfaces this draw touches. */
    for (u32 i = 0; i < n; i++)
        vk_barrier_image(s_eobj[s_eng_bound.rt[i]].im.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);
    VkRenderPassBeginInfo rbi = { .sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,
                                  .renderPass = rp, .framebuffer = fb,
                                  .renderArea = { { 0, 0 }, { w, h } } };
    pvkCmdBeginRenderPass(s_vk.cmd, &rbi, VK_SUBPASS_CONTENTS_INLINE);''',
     '''    if (vk_begin()) return;
    /* A draw that samples one of the open pass's targets (directly or through a view of it) needs the
     * barrier between the two: no merging then. */
    int keep = s_rp_open && vk_rp_merge() && s_rp_rp == rp && s_rp_fb == fb && s_rp_w == w && s_rp_h == h;
    for (u32 u = 0; keep && u < RSX_MAX_TEXTURES; u++) {
        if (!((s_e2.tex_mask >> u) & 1u) || !s_e2.tex[u] || s_e2.tex[u] >= VK_ENG_MAX_OBJ) continue;
        const vk_eng_obj* o = &s_eobj[s_e2.tex[u]];
        const u32 t = o->kind == VK_ENG_VIEW ? o->surface : s_e2.tex[u];
        if (t && t == s_eng_bound.depth) keep = 0;
        for (u32 i = 0; i < n; i++) if (t && t == s_eng_bound.rt[i]) keep = 0;
    }
    s_rp_draws++;
    if (!keep) {
        vk_rp_close();
        /* This orders memory for the surfaces this draw touches after everything recorded or
         * submitted before it. */
        for (u32 i = 0; i < n; i++)
            vk_barrier_image(s_eobj[s_eng_bound.rt[i]].im.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);
        VkRenderPassBeginInfo rbi = { .sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,
                                      .renderPass = rp, .framebuffer = fb,
                                      .renderArea = { { 0, 0 }, { w, h } } };
        pvkCmdBeginRenderPass(s_vk.cmd, &rbi, VK_SUBPASS_CONTENTS_INLINE);
        s_rp_open = 1; s_rp_rp = rp; s_rp_fb = fb; s_rp_w = w; s_rp_h = h;
        s_rp_begun++;
    }
    {   static uint64_t t0;
        const uint64_t now = ps3_ft_now();
        if (!t0) t0 = now;
        if (now - t0 >= 10000000000ull) {
            fprintf(stderr, "[vk] render passes: %u for %u draws in %.0f s\\n", s_rp_begun, s_rp_draws, (now - t0) / 1e9);
            s_rp_begun = s_rp_draws = 0; t0 = now;
        } }''',
     "vk rpmerge: draw begin")
edit(VKF,
     '''        pvkCmdDraw(s_vk.cmd, vertex_count, 1, 0, 0);
    }
    pvkCmdEndRenderPass(s_vk.cmd);
    vk_submit_and_wait();
}''',
     '''        pvkCmdDraw(s_vk.cmd, vertex_count, 1, 0, 0);
    }
    if (!vk_rp_merge()) vk_rp_close();        /* else left open for the next draw */
    vk_submit_and_wait();
}''',
     "vk rpmerge: draw end")
# vk pipe async: engine pipelines are built on worker threads; a draw waits a few ms for its build, then is skipped until it is ready
VKF = "libs/video/rsx_vulkan_backend.c"
edit(VKF,
     '''#include <dlfcn.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>''',
     '''#include <dlfcn.h>
#include <pthread.h>
#include <time.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>''',
     "vk pipe async: includes")
edit(VKF,
     '''    u32                 cube_mask;    /* pixel shader's TextureCube units */
    VkPipeline          variant[VK_ENG_TOPOLOGIES];
} vk_eng_pipe;''',
     '''    u32                 cube_mask;    /* pixel shader's TextureCube units */
    VkPipeline          variant[VK_ENG_TOPOLOGIES];
    u32                 pend, bad;    /* variants being built on a worker / whose build failed */
} vk_eng_pipe;''',
     "vk pipe async: pipe fields")
edit(VKF,
     '''static void vk_eng_pipeline_release(void* user, u32 pipeline)
{
    (void)user;
    if (!pipeline || pipeline > VK_ENG_MAX_PIPE || !s_epipe[pipeline - 1].used) return;
    vk_eng_pipe* P = &s_epipe[pipeline - 1];''',
     '''/* Pipeline builds off the RSX thread (PS3RECOMP_VK_ASYNC_PIPE=0 turns it off). On the console a
 * pipeline the driver had not built before took 0.2-0.9 s in vkCreateGraphicsPipelines, on the RSX
 * thread, in the middle of a frame: inFAMOUS 2's 1-2.7 s freezes, FoB's hitches. Now the first draw
 * that needs a variant hands a copy of its create info to a worker (PS3RECOMP_VK_PIPE_THREADS, 2)
 * and waits up to PS3RECOMP_VK_PIPE_WAIT_MS (8) for it: a build the driver's cache answers is back
 * well within that and the draw happens as before. A longer one is not waited for: its draws are
 * skipped until it is done (the object appears a moment later). A pipeline released while one of
 * its variants is being built waits for that build first, so the shader modules outlive it. */
typedef struct {
    vk_eng_pipe* P;
    u32 topo;
    VkGraphicsPipelineCreateInfo gci;
    VkPipelineShaderStageCreateInfo st[2];
    VkVertexInputBindingDescription vb;
    VkVertexInputAttributeDescription va[VK_GUEST_ATTRS];
    VkPipelineVertexInputStateCreateInfo vi;
    VkPipelineInputAssemblyStateCreateInfo ia;
    VkPipelineViewportStateCreateInfo vps;
    VkPipelineRasterizationStateCreateInfo ras;
    VkPipelineMultisampleStateCreateInfo ms;
    VkPipelineDepthStencilStateCreateInfo ds;
    VkPipelineColorBlendAttachmentState cba[RSX_BE_MAX_COLOR_TARGETS];
    VkPipelineColorBlendStateCreateInfo cb;
    VkDynamicState dyn[8];
    VkPipelineDynamicStateCreateInfo dy;
} vk_pa_job;
void ps3_host_thread_label(const char* name) __attribute__((weak));   /* host_qos.h: the PS5 profile's names */
#define VK_PA_QUEUE 256u
static pthread_mutex_t s_pa_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t  s_pa_work = PTHREAD_COND_INITIALIZER, s_pa_done = PTHREAD_COND_INITIALIZER;
static vk_pa_job s_pa_q[VK_PA_QUEUE];
static u32 s_pa_head, s_pa_tail;               /* s_pa_q[head % N] is the next job */
static u32 s_pa_queued, s_pa_in_time, s_pa_late, s_pa_skips, s_pa_fail;
static double s_pa_max_ms, s_pa_sum_ms;
static int s_pa_wait_ms = 8;

static void* vk_pa_worker(void* arg)
{
    (void)arg;
    if (ps3_host_thread_label) ps3_host_thread_label("vk pipeline build");
    for (;;) {
        pthread_mutex_lock(&s_pa_mu);
        while (s_pa_head == s_pa_tail) pthread_cond_wait(&s_pa_work, &s_pa_mu);
        vk_pa_job j = s_pa_q[s_pa_head % VK_PA_QUEUE];
        s_pa_head++;
        pthread_mutex_unlock(&s_pa_mu);
        /* the copy's pointers into the queue slot are re-aimed at this one */
        j.gci.pStages = j.st; j.vi.pVertexBindingDescriptions = &j.vb; j.vi.pVertexAttributeDescriptions = j.va;
        j.gci.pVertexInputState = &j.vi; j.gci.pInputAssemblyState = &j.ia; j.gci.pViewportState = &j.vps;
        j.gci.pRasterizationState = &j.ras; j.gci.pMultisampleState = &j.ms; j.gci.pDepthStencilState = &j.ds;
        j.cb.pAttachments = j.cba; j.gci.pColorBlendState = &j.cb; j.dy.pDynamicStates = j.dyn; j.gci.pDynamicState = &j.dy;
        const uint64_t t0 = ps3_ft_now();
        VkPipeline p = VK_NULL_HANDLE;
        const VkResult r = pvkCreateGraphicsPipelines(s_vk.device, VK_NULL_HANDLE, 1, &j.gci, NULL, &p);
        const double ms = (ps3_ft_now() - t0) / 1e6;
        if (ms > 50.0) VK_LOG("engine: pipeline build took %.0f ms (topology %u, worker)\\n", ms, j.topo);
        pthread_mutex_lock(&s_pa_mu);
        if (r == VK_SUCCESS && p) __atomic_store_n(&j.P->variant[j.topo], p, __ATOMIC_RELEASE);
        else { j.P->bad |= 1u << j.topo; s_pa_fail++; VK_LOG("engine: vkCreateGraphicsPipelines failed (%d, worker)\\n", (int)r); }
        __atomic_and_fetch(&j.P->pend, ~(1u << j.topo), __ATOMIC_RELEASE);
        if (ms > s_pa_max_ms) s_pa_max_ms = ms;
        s_pa_sum_ms += ms;
        pthread_cond_broadcast(&s_pa_done);
        pthread_mutex_unlock(&s_pa_mu);
    }
    return NULL;
}

static int vk_pa_on(void)
{
    static int on = -1;
    if (on >= 0) return on;
    const char* e = getenv("PS3RECOMP_VK_ASYNC_PIPE");
    on = 0;
    if (e && e[0] == '0') return 0;
    const char* w = getenv("PS3RECOMP_VK_PIPE_WAIT_MS");
    if (w && *w) s_pa_wait_ms = atoi(w);
    const char* t = getenv("PS3RECOMP_VK_PIPE_THREADS");
    int n = t && *t ? atoi(t) : 2;
    if (n < 1) n = 1;
    if (n > 4) n = 4;
    int made = 0;
    for (int i = 0; i < n; i++) {
        pthread_t th;
        pthread_attr_t a;
        pthread_attr_init(&a);
        pthread_attr_setstacksize(&a, 2u << 20);
        if (pthread_create(&th, &a, vk_pa_worker, NULL) == 0) { pthread_detach(th); made++; }
        pthread_attr_destroy(&a);
    }
    on = made > 0;
    VK_LOG("engine: pipelines built on %d worker thread(s), a draw waits up to %d ms for its build\\n", made, s_pa_wait_ms);
    return on;
}

/* Queue the build of P's variant `topo` from `g` (all of it copied) and wait up to the budget. */
static VkPipeline vk_pa_submit(vk_eng_pipe* P, u32 topo, const VkGraphicsPipelineCreateInfo* g)
{
    pthread_mutex_lock(&s_pa_mu);
    if (s_pa_tail - s_pa_head >= VK_PA_QUEUE) { pthread_mutex_unlock(&s_pa_mu); s_pa_skips++; return VK_NULL_HANDLE; }
    vk_pa_job* j = &s_pa_q[s_pa_tail % VK_PA_QUEUE];
    memset(j, 0, sizeof *j);
    j->P = P; j->topo = topo;
    j->gci = *g;
    memcpy(j->st, g->pStages, sizeof j->st);
    j->vi = *g->pVertexInputState;
    if (j->vi.vertexBindingDescriptionCount) j->vb = *g->pVertexInputState->pVertexBindingDescriptions;
    if (j->vi.vertexAttributeDescriptionCount > VK_GUEST_ATTRS) j->vi.vertexAttributeDescriptionCount = VK_GUEST_ATTRS;
    memcpy(j->va, g->pVertexInputState->pVertexAttributeDescriptions, j->vi.vertexAttributeDescriptionCount * sizeof j->va[0]);
    j->ia = *g->pInputAssemblyState; j->vps = *g->pViewportState; j->ras = *g->pRasterizationState;
    j->ms = *g->pMultisampleState; j->ds = *g->pDepthStencilState;
    j->cb = *g->pColorBlendState;
    if (j->cb.attachmentCount > RSX_BE_MAX_COLOR_TARGETS) j->cb.attachmentCount = RSX_BE_MAX_COLOR_TARGETS;
    memcpy(j->cba, g->pColorBlendState->pAttachments, j->cb.attachmentCount * sizeof j->cba[0]);
    j->dy = *g->pDynamicState;
    if (j->dy.dynamicStateCount > 8) j->dy.dynamicStateCount = 8;
    memcpy(j->dyn, g->pDynamicState->pDynamicStates, j->dy.dynamicStateCount * sizeof j->dyn[0]);
    __atomic_or_fetch(&P->pend, 1u << topo, __ATOMIC_RELEASE);
    s_pa_tail++;
    s_pa_queued++;
    pthread_cond_signal(&s_pa_work);
    struct timespec dl;
    clock_gettime(CLOCK_REALTIME, &dl);
    dl.tv_nsec += (long)s_pa_wait_ms * 1000000L;
    while (dl.tv_nsec >= 1000000000L) { dl.tv_nsec -= 1000000000L; dl.tv_sec++; }
    while ((P->pend & (1u << topo)) && s_pa_wait_ms > 0)
        if (pthread_cond_timedwait(&s_pa_done, &s_pa_mu, &dl) != 0) break;
    const int late = (P->pend & (1u << topo)) != 0;
    if (late) s_pa_late++; else s_pa_in_time++;
    {   static uint64_t t0;
        const uint64_t now = ps3_ft_now();
        if (!t0) t0 = now;
        if (now - t0 >= 10000000000ull) {
            VK_LOG("engine: async pipelines in %.0f s: %u queued, %u in time, %u late (skipped until built), %u queue-full, %u failed; builds %.0f ms in all, longest %.0f ms\\n",
                   (now - t0) / 1e9, s_pa_queued, s_pa_in_time, s_pa_late, s_pa_skips, s_pa_fail, s_pa_sum_ms, s_pa_max_ms);
            s_pa_queued = s_pa_in_time = s_pa_late = s_pa_skips = s_pa_fail = 0; s_pa_sum_ms = s_pa_max_ms = 0; t0 = now;
        } }
    pthread_mutex_unlock(&s_pa_mu);
    return __atomic_load_n(&P->variant[topo], __ATOMIC_ACQUIRE);
}

/* Every variant of P that a worker is building is finished. */
static void vk_pa_wait_idle(vk_eng_pipe* P)
{
    if (!__atomic_load_n(&P->pend, __ATOMIC_ACQUIRE)) return;
    pthread_mutex_lock(&s_pa_mu);
    while (P->pend) pthread_cond_wait(&s_pa_done, &s_pa_mu);
    pthread_mutex_unlock(&s_pa_mu);
}

static void vk_eng_pipeline_release(void* user, u32 pipeline)
{
    (void)user;
    if (!pipeline || pipeline > VK_ENG_MAX_PIPE || !s_epipe[pipeline - 1].used) return;
    vk_eng_pipe* P = &s_epipe[pipeline - 1];
    vk_pa_wait_idle(P);''',
     "vk pipe async: workers")
edit(VKF,
     '''        VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP };
    if (P->variant[topo_idx]) return P->variant[topo_idx];''',
     '''        VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP };
    {   const VkPipeline have = __atomic_load_n(&P->variant[topo_idx], __ATOMIC_ACQUIRE);
        if (have) return have;
        if (__atomic_load_n(&P->pend, __ATOMIC_ACQUIRE) & (1u << topo_idx))
            return __atomic_load_n(&P->variant[topo_idx], __ATOMIC_ACQUIRE);   /* still building */
        if (P->bad & (1u << topo_idx)) return VK_NULL_HANDLE; }''',
     "vk pipe async: variant check")
edit(VKF,
     '''    const uint64_t pc0 = ps3_ft_now();
    if (pvkCreateGraphicsPipelines(s_vk.device, VK_NULL_HANDLE, 1, &gci, NULL,
                                   &P->variant[topo_idx]) != VK_SUCCESS) {''',
     '''    if (vk_pa_on()) return vk_pa_submit(P, topo_idx, &gci);
    const uint64_t pc0 = ps3_ft_now();
    if (pvkCreateGraphicsPipelines(s_vk.device, VK_NULL_HANDLE, 1, &gci, NULL,
                                   &P->variant[topo_idx]) != VK_SUCCESS) {''',
     "vk pipe async: submit")
# vk pipe block: a draw into an off-screen target waits for its pipeline build instead of being skipped
VKF = "libs/video/rsx_vulkan_backend.c"
edit(VKF,
     '''static int s_pa_wait_ms = 8;''',
     '''static int s_pa_wait_ms = 8;
/* The draw at hand targets less than 3/4 of a 1280x720 screen (a reflection or shadow map, a
 * look-up table, a cube face): it waits for its build however long that takes. Skipping is only
 * safe for screen-sized targets, which are drawn again next frame; the console run that skipped
 * every late draw left inFAMOUS 2's metal props purple for good (an environment map drawn once at
 * load had been skipped). */
static int s_pa_block;
static unsigned s_pa_blocked;''',
     "vk pipe block: flag")
edit(VKF,
     '''    while ((P->pend & (1u << topo)) && s_pa_wait_ms > 0)
        if (pthread_cond_timedwait(&s_pa_done, &s_pa_mu, &dl) != 0) break;''',
     '''    if (s_pa_block) {
        if (P->pend & (1u << topo)) s_pa_blocked++;
        while (P->pend & (1u << topo)) pthread_cond_wait(&s_pa_done, &s_pa_mu);
    } else
        while ((P->pend & (1u << topo)) && s_pa_wait_ms > 0)
            if (pthread_cond_timedwait(&s_pa_done, &s_pa_mu, &dl) != 0) break;''',
     "vk pipe block: submit wait")
edit(VKF,
     '''            VK_LOG("engine: async pipelines in %.0f s: %u queued, %u in time, %u late (skipped until built), %u queue-full, %u failed; builds %.0f ms in all, longest %.0f ms\\n",
                   (now - t0) / 1e9, s_pa_queued, s_pa_in_time, s_pa_late, s_pa_skips, s_pa_fail, s_pa_sum_ms, s_pa_max_ms);
            s_pa_queued = s_pa_in_time = s_pa_late = s_pa_skips = s_pa_fail = 0; s_pa_sum_ms = s_pa_max_ms = 0; t0 = now;''',
     '''            VK_LOG("engine: async pipelines in %.0f s: %u queued, %u in time, %u late (skipped until built), %u waited for (off-screen target), %u queue-full, %u failed; builds %.0f ms in all, longest %.0f ms\\n",
                   (now - t0) / 1e9, s_pa_queued, s_pa_in_time, s_pa_late, s_pa_blocked, s_pa_skips, s_pa_fail, s_pa_sum_ms, s_pa_max_ms);
            s_pa_queued = s_pa_in_time = s_pa_late = s_pa_blocked = s_pa_skips = s_pa_fail = 0; s_pa_sum_ms = s_pa_max_ms = 0; t0 = now;''',
     "vk pipe block: log")
edit(VKF,
     '''        if (__atomic_load_n(&P->pend, __ATOMIC_ACQUIRE) & (1u << topo_idx))
            return __atomic_load_n(&P->variant[topo_idx], __ATOMIC_ACQUIRE);   /* still building */''',
     '''        if (__atomic_load_n(&P->pend, __ATOMIC_ACQUIRE) & (1u << topo_idx)) {
            if (s_pa_block) {                                                  /* off-screen: wait */
                pthread_mutex_lock(&s_pa_mu);
                if (P->pend & (1u << topo_idx)) s_pa_blocked++;
                while (P->pend & (1u << topo_idx)) pthread_cond_wait(&s_pa_done, &s_pa_mu);
                pthread_mutex_unlock(&s_pa_mu);
            }
            return __atomic_load_n(&P->variant[topo_idx], __ATOMIC_ACQUIRE);   /* still building */
        }''',
     "vk pipe block: pending wait")
edit(VKF,
     '''    VkPipeline pipe = vk_eng_variant(P, (u32)topology - 1u);
    VkRenderPass rp = vk_eng_render_pass(n);''',
     '''    s_pa_block = (uint64_t)w * h < 1280u * 720u * 3u / 4u;
    VkPipeline pipe = vk_eng_variant(P, (u32)topology - 1u);
    VkRenderPass rp = vk_eng_render_pass(n);''',
     "vk pipe block: draw size")
# vk tex3d: 3D textures on Vulkan (colour-grading volumes), and a black stand-in cube with a log line
VKF = "libs/video/rsx_vulkan_backend.c"
edit(VKF,
     '''    u32      snap2;                  /* COLOR/DEPTH: colour / RGBA8 snapshot */
} vk_eng_obj;''',
     '''    u32      snap2;                  /* COLOR/DEPTH: colour / RGBA8 snapshot */
    u8       vol;                    /* TEXTURE: a 3D image, 3D view        */
} vk_eng_obj;''',
     "vk tex3d: obj field")
edit(VKF,
     '''    u32                 cube_mask;    /* pixel shader's TextureCube units */
    VkPipeline          variant[VK_ENG_TOPOLOGIES];''',
     '''    u32                 cube_mask;    /* pixel shader's TextureCube units */
    u32                 vol_mask;     /* pixel shader's Texture3D units */
    VkPipeline          variant[VK_ENG_TOPOLOGIES];''',
     "vk tex3d: pipe field")
edit(VKF,
     '''    for (const char* c = ps_hlsl; (c = strstr(c, "TextureCube rsx_tex")) != NULL; c++) {
        const unsigned u = (unsigned)strtoul(c + 19, NULL, 10);
        if (u < RSX_MAX_TEXTURES) P->cube_mask |= 1u << u;
    }''',
     '''    for (const char* c = ps_hlsl; (c = strstr(c, "TextureCube rsx_tex")) != NULL; c++) {
        const unsigned u = (unsigned)strtoul(c + 19, NULL, 10);
        if (u < RSX_MAX_TEXTURES) P->cube_mask |= 1u << u;
    }
    for (const char* c = ps_hlsl; (c = strstr(c, "Texture3D")) != NULL; c++) {
        const char* t = strstr(c, "rsx_tex");
        if (!t || t - c > 8) continue;
        const unsigned u = (unsigned)strtoul(t + 7, NULL, 10);
        if (u < RSX_MAX_TEXTURES) P->vol_mask |= 1u << u;
    }''',
     "vk tex3d: pipe mask")
edit(VKF,
     '''static VkImageView vk_eng_dummy_cube(void)
{
    static u32 hd;''',
     '''/* 3D textures (the engine's texture_create_3d / texture_upload_3d). Without them a volume was
 * created from its first slice and sampled in 2D: a colour-grading volume (red x green x blue)
 * lost its blue axis, which tinted whole areas -- FoB's town green-yellow, inFAMOUS's alleys blue
 * (user's reference footage, 2026-11-01). One VK_IMAGE_TYPE_3D image with a 3D view; each slice
 * of each level is one upload. */
static u32 vk_eng_texture_create_3d(void* user, rsx_be_format fmt, u32 w, u32 h, u32 depth,
                                    u32 mips, u32 remap, u32 rsx_fmt)
{
    (void)user;
    u32 bpp;
    const VkFormat vf = vk_eng_format(fmt, &bpp);
    const int bc = (fmt == RSX_BE_FMT_BC1 || fmt == RSX_BE_FMT_BC2 || fmt == RSX_BE_FMT_BC3);
    if (vf == VK_FORMAT_UNDEFINED || !w || !h || !depth || w > 2048u || h > 2048u || depth > 2048u || bc)
        return 0;
    if (!mips) mips = 1;
    const u32 hd = vk_eng_alloc();
    if (!hd) return 0;
    vk_eng_obj* o = &s_eobj[hd];
    VkImageCreateInfo ici = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_3D,
        .format = vf, .extent = { w, h, depth }, .mipLevels = mips, .arrayLayers = 1,
        .samples = VK_SAMPLE_COUNT_1_BIT, .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,
        .sharingMode = VK_SHARING_MODE_EXCLUSIVE, .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED };
    VkMemoryRequirements req;
    u32 type;
    if (pvkCreateImage(s_vk.device, &ici, NULL, &o->im.img) != VK_SUCCESS) goto fail;
    pvkGetImageMemoryRequirements(s_vk.device, o->im.img, &req);
    if (vk_find_memory_type(req.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, &type) &&
        vk_find_memory_type(req.memoryTypeBits, 0, &type)) goto fail;
    VkMemoryAllocateInfo mai = { .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                                 .allocationSize = req.size, .memoryTypeIndex = type };
    if (pvkAllocateMemory(s_vk.device, &mai, NULL, &o->im.mem) != VK_SUCCESS ||
        pvkBindImageMemory(s_vk.device, o->im.img, o->im.mem, 0) != VK_SUCCESS) goto fail;
    {   VkImageViewCreateInfo vci = {
            .sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = o->im.img,
            .viewType = VK_IMAGE_VIEW_TYPE_3D, .format = vf, .components = vk_remap(remap, rsx_fmt),
            .subresourceRange = { VK_IMAGE_ASPECT_COLOR_BIT, 0, mips, 0, 1 } };
        if (pvkCreateImageView(s_vk.device, &vci, NULL, &o->im.view) != VK_SUCCESS) goto fail; }
    o->kind = VK_ENG_TEXTURE; o->fmt = vf; o->w = w; o->h = h; o->cube = 0; o->vol = 1;
    o->bpp = bpp; o->block = 0;
    if (vk_begin()) goto fail;
    vk_barrier_image(o->im.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_UNDEFINED);
    if (vk_submit_and_wait()) goto fail;
    {   static int told; if (told++ < 8) VK_LOG("engine: 3D texture %ux%ux%u (%u levels, format %d)\\n", w, h, depth, mips, (int)vf); }
    return hd;
fail:
    vk_destroy_image(&o->im);
    memset(o, 0, sizeof *o);
    return 0;
}

static void vk_eng_texture_upload_3d(void* user, u32 texture, u32 z, u32 mip, u32 w, u32 h,
                                     const void* src, u32 row_bytes)
{
    (void)user;
    vk_eng_obj* o = vk_eng_get(texture, VK_ENG_TEXTURE);
    if (!o || !o->vol || !src || !row_bytes || !w || !h) return;
    size_t tight = (size_t)w * o->bpp;
    if (tight > row_bytes) tight = row_bytes;
    vk_buffer st = {0};
    if (vk_create_host_buffer(&st, (VkDeviceSize)tight * h, VK_BUFFER_USAGE_TRANSFER_SRC_BIT) ||
        !st.coherent) { vk_destroy_buffer(&st); return; }
    for (u32 y = 0; y < h; y++)
        memcpy((u8*)st.ptr + (size_t)y * tight, (const u8*)src + (size_t)y * row_bytes, tight);
    if (!vk_begin()) {
        vk_barrier_image(o->im.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);
        VkBufferImageCopy region = {
            .imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, mip, 0, 1 },
            .imageOffset = { 0, 0, (int32_t)z }, .imageExtent = { w, h, 1 } };
        pvkCmdCopyBufferToImage(s_vk.cmd, st.buf, o->im.img, VK_IMAGE_LAYOUT_GENERAL, 1, &region);
        vk_submit_and_wait();
    }
    vk_destroy_buffer(&st);
}

/* A unit declared Texture3D with nothing usable bound: a 1x1x1 black volume. */
static VkImageView vk_eng_dummy_3d(void)
{
    static u32 hd;
    if (hd && s_eobj[hd].kind == VK_ENG_TEXTURE && s_eobj[hd].vol) return s_eobj[hd].im.view;
    hd = vk_eng_texture_create_3d(NULL, RSX_BE_FMT_R8G8B8A8, 1, 1, 1, 1, 0, 0);
    if (!hd) return s_vk.dummy.view;
    /* the identity crossbar: vk_remap(0, 0) is what create used */
    static const u8 black[4] = { 0, 0, 0, 0xFF };
    vk_eng_texture_upload_3d(NULL, hd, 0, 0, 1, 1, black, 4);
    return s_eobj[hd].im.view;
}

static VkImageView vk_eng_dummy_cube(void)
{
    static u32 hd;''',
     "vk tex3d: create upload")
edit(VKF,
     '''    static const u8 magenta[4] = { 0xFF, 0x00, 0xFF, 0xFF };
    for (u32 f = 0; f < 6; f++) vk_eng_texture_upload(NULL, hd, f, 0, 1, 1, magenta, 4, 1);''',
     '''    /* Black, not magenta: a missing reflection cube is no reflection (inFAMOUS 2's metal props
     * were bright purple on the console). Each use is counted in "[vk] stand-in textures". */
    static const u8 black[4] = { 0x00, 0x00, 0x00, 0xFF };
    for (u32 f = 0; f < 6; f++) vk_eng_texture_upload(NULL, hd, f, 0, 1, 1, black, 4, 1);''',
     "vk tex3d: black cube")
edit(VKF,
     '''    const u32 cube_mask = s_e2.pipeline ? s_epipe[s_e2.pipeline - 1].cube_mask : 0;''',
     '''    const u32 cube_mask = s_e2.pipeline ? s_epipe[s_e2.pipeline - 1].cube_mask : 0;
    const u32 vol_mask = s_e2.pipeline ? s_epipe[s_e2.pipeline - 1].vol_mask : 0;
    static unsigned s_sub_cube, s_sub_vol, s_sub_kind; static uint64_t s_sub_t0;''',
     "vk tex3d: masks")
edit(VKF,
     '''        const u32 want_cube = (cube_mask >> u) & 1u;
        VkImageView v = ((s_e2.tex_mask >> u) & 1u) ? vk_eng_sample_view(s_e2.tex[u]) : VK_NULL_HANDLE;
        if (v && (u32)s_eobj[s_e2.tex[u]].cube != want_cube) v = VK_NULL_HANDLE;
        VkSampler smp = v ? vk_eng_sampler(&s_e2.samp[u]) : s_vk.sampler;
        ii[u] = (VkDescriptorImageInfo){ VK_NULL_HANDLE,
                                         v ? v : want_cube ? vk_eng_dummy_cube() : s_vk.dummy.view,
                                         VK_IMAGE_LAYOUT_GENERAL };''',
     '''        const u32 want_cube = (cube_mask >> u) & 1u, want_vol = (vol_mask >> u) & 1u;
        VkImageView v = ((s_e2.tex_mask >> u) & 1u) ? vk_eng_sample_view(s_e2.tex[u]) : VK_NULL_HANDLE;
        if (v && ((u32)s_eobj[s_e2.tex[u]].cube != want_cube || (u32)s_eobj[s_e2.tex[u]].vol != want_vol)) {
            v = VK_NULL_HANDLE; s_sub_kind++;
        }
        if (!v && want_cube) s_sub_cube++;
        if (!v && want_vol) s_sub_vol++;
        VkSampler smp = v ? vk_eng_sampler(&s_e2.samp[u]) : s_vk.sampler;
        ii[u] = (VkDescriptorImageInfo){ VK_NULL_HANDLE,
                                         v ? v : want_cube ? vk_eng_dummy_cube() : want_vol ? vk_eng_dummy_3d() : s_vk.dummy.view,
                                         VK_IMAGE_LAYOUT_GENERAL };''',
     "vk tex3d: descriptors")
edit(VKF,
     '''    if (s_wd_set) for (int i = 0; i < 4; i++) w[i].dstSet = s_wd_set;
    pvkUpdateDescriptorSets(s_vk.device, 4, w, 0, NULL);''',
     '''    if (s_wd_set) for (int i = 0; i < 4; i++) w[i].dstSet = s_wd_set;
    pvkUpdateDescriptorSets(s_vk.device, 4, w, 0, NULL);
    {   const uint64_t now = ps3_ft_now();
        if (!s_sub_t0) s_sub_t0 = now;
        if (now - s_sub_t0 >= 10000000000ull) {
            if (s_sub_cube || s_sub_vol || s_sub_kind)
                fprintf(stderr, "[vk] stand-in textures in %.0f s: %u cube, %u 3D, %u bound texture of the wrong kind\\n",
                        (now - s_sub_t0) / 1e9, s_sub_cube, s_sub_vol, s_sub_kind);
            s_sub_cube = s_sub_vol = s_sub_kind = 0; s_sub_t0 = now;
        } }''',
     "vk tex3d: log")
edit(VKF,
     '''    .texture_upload       = vk_eng_texture_upload,''',
     '''    .texture_upload       = vk_eng_texture_upload,
    .texture_create_3d    = vk_eng_texture_create_3d,
    .texture_upload_3d    = vk_eng_texture_upload_3d,''',
     "vk tex3d: hooks")
# vk tex3d fix: the decompiler pads "Texture3D" to the TextureCube width, so the unit name is 12 characters on
VKF = "libs/video/rsx_vulkan_backend.c"
edit(VKF,
     '''        if (!t || t - c > 8) continue;''',
     '''        if (!t || t - c > 16) continue;   /* "Texture3D   rsx_tex<n>" */''',
     "vk tex3d fix: parse")
# spin waits: SPU channel waits and the PPU's usleep-kick waits spin briefly before sleeping in the OS
# The console's waits are the frame limiter: the main PPU thread waited ~8,500-14,600 times a second
# (ps3_memkick_wait) and each SPU thread ~1,000 times a second (spu_ch_wait), with the CPU mostly
# idle (2-3 cores busy of 13; RPCS3 on the PS5 keeps ~7 busy at 30-40 fps on inFAMOUS). Every one
# of those was a condition-variable sleep and an OS wake-up. Now each first spins (pause loop) for
# up to PS3_SPU_SPIN_US / PS3_MK_SPIN_US microseconds (40 / 40; 0 = off), checking the same thing
# it would be woken for, and sleeps only when that does not happen in time. Both are also read from
# the toggle file (PS3_TOGGLE_FILE) every few thousand waits, so a running game can be A/B tested.
SPC = "runtime/spu/spu_channels.c"
edit(SPC,
     '''/* Block the calling SPU host thread until `channel` is readable. */
static void spu_ch_wait(spu_context* ctx, uint32_t channel, const char* op)
{
    if (!yz_ch_block() || spu_ch_ready(ctx, channel)) return;''',
     '''/* The spin before a channel sleep (PS3_SPU_SPIN_US, default 40; also live from the toggle file). */
static int spu_spin_us(void)
{
    static _Atomic unsigned n;
    static _Atomic int us = -1;
    if ((__atomic_fetch_add(&n, 1, __ATOMIC_RELAXED) & 4095u) == 0 || us < 0) {
        const char* e = getenv("PS3_SPU_SPIN_US");
        us = ps3_toggle_get("PS3_SPU_SPIN_US", e ? atoi(e) : 40);
    }
    return us;
}
static _Atomic unsigned long s_spin_hit, s_spin_miss;

/* Block the calling SPU host thread until `channel` is readable. */
static void spu_ch_wait(spu_context* ctx, uint32_t channel, const char* op)
{
    if (!yz_ch_block() || spu_ch_ready(ctx, channel)) return;
#if defined(__x86_64__)
    {   const int us = spu_spin_us();
        if (us > 0) {
            const uint64_t t0 = ps3_ft_now(), lim = (uint64_t)us * 1000ull;
            for (unsigned k = 1;; k++) {
                for (int i = 0; i < 8; i++) __builtin_ia32_pause();
                if (spu_ch_ready(ctx, channel)) {
                    __atomic_add_fetch(&s_spin_hit, 1, __ATOMIC_RELAXED);
                    return;
                }
                if (__atomic_load_n(&ctx->stop_request, __ATOMIC_RELAXED)) break;
                if (!(k & 7u) && ps3_ft_now() - t0 > lim) break;
            }
            const unsigned long m = __atomic_add_fetch(&s_spin_miss, 1, __ATOMIC_RELAXED);
            if ((m & 65535u) == 0)
                fprintf(stderr, "[spin] spu channel waits: %lu answered while spinning, %lu slept (spin %d us)\\n",
                        (unsigned long)s_spin_hit, m, us);
        }
    }
#endif''',
     "spin waits: spu")

SCO = "runtime/spu/spu_coherency.c"
edit(SCO,
     '''void ps3_memkick_slow(void)
{
    if (__atomic_exchange_n(&s_mk_pending, 1, __ATOMIC_ACQ_REL)) return;''',
     '''static unsigned s_mk_gen;   /* every kick: a spinning waiter watches it change */
void ps3_memkick_slow(void)
{
    __atomic_add_fetch(&s_mk_gen, 1, __ATOMIC_RELEASE);
    if (__atomic_exchange_n(&s_mk_pending, 1, __ATOMIC_ACQ_REL)) return;''',
     "spin waits: kick gen")
edit(SCO,
     '''void ps3_memkick_wait(uint64_t us)
{
    struct timespec ts;''',
     '''/* The spin before a usleep-kick sleep (PS3_MK_SPIN_US, default 40; also live from the toggle file). */
#include "ps3emu/ps3_toggles.h"
static int mk_spin_us(void)
{
    static unsigned n;
    static int v = -1;
    if ((__atomic_fetch_add(&n, 1, __ATOMIC_RELAXED) & 4095u) == 0 || v < 0) {
        const char* e = getenv("PS3_MK_SPIN_US");
        v = ps3_toggle_get("PS3_MK_SPIN_US", e ? atoi(e) : 40);
    }
    return v;
}
static unsigned long s_mk_spin_hit, s_mk_spin_miss;
static uint64_t mk_now_ns(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec;
}

void ps3_memkick_wait(uint64_t us)
{
#if defined(__x86_64__)
    {   const int sp = mk_spin_us();
        if (sp > 0) {
            /* A waiter makes every SPU write call ps3_memkick_slow, which bumps the generation. */
            __atomic_add_fetch(&g_mk_waiters, 1, __ATOMIC_SEQ_CST);
            const unsigned g0 = __atomic_load_n(&s_mk_gen, __ATOMIC_ACQUIRE);
            const uint64_t t0 = mk_now_ns(), lim = (uint64_t)(sp < (int)us ? sp : (int)us) * 1000ull;
            int hit = 0;
            for (unsigned k = 1;; k++) {
                for (int i = 0; i < 8; i++) __builtin_ia32_pause();
                if (__atomic_load_n(&s_mk_gen, __ATOMIC_ACQUIRE) != g0) { hit = 1; break; }
                if (!(k & 7u) && mk_now_ns() - t0 > lim) break;
            }
            __atomic_sub_fetch(&g_mk_waiters, 1, __ATOMIC_SEQ_CST);
            if (hit) {
                __atomic_add_fetch(&g_mk_woken, 1, __ATOMIC_RELAXED);
                __atomic_add_fetch(&s_mk_spin_hit, 1, __ATOMIC_RELAXED);
                return;
            }
            const unsigned long m = __atomic_add_fetch(&s_mk_spin_miss, 1, __ATOMIC_RELAXED);
            if ((m & 65535u) == 0)
                fprintf(stderr, "[spin] usleep-kick waits: %lu answered while spinning, %lu slept (spin %d us)\\n",
                        s_mk_spin_hit, m, sp);
        }
    }
#endif
    struct timespec ts;''',
     "spin waits: memkick")
# spin waits fix: plain counters (the __atomic builtins reject C11 _Atomic objects under clang)
SPC = "runtime/spu/spu_channels.c"
edit(SPC,
     '''    static _Atomic unsigned n;
    static _Atomic int us = -1;''',
     '''    static unsigned n;
    static int us = -1;''',
     "spin waits fix: spu knob")
edit(SPC,
     '''static _Atomic unsigned long s_spin_hit, s_spin_miss;''',
     '''static unsigned long s_spin_hit, s_spin_miss;''',
     "spin waits fix: spu counters")
# spin off: both spins default to 0 -- the console's condition-variable hand-off is 3.8 us, so spinning gained nothing, and inFAMOUS 1 hung at load with it
edit("runtime/spu/spu_channels.c",
     '''        us = ps3_toggle_get("PS3_SPU_SPIN_US", e ? atoi(e) : 40);''',
     '''        us = ps3_toggle_get("PS3_SPU_SPIN_US", e ? atoi(e) : 0);''',
     "spin off: spu default")
edit("runtime/spu/spu_coherency.c",
     '''        v = ps3_toggle_get("PS3_MK_SPIN_US", e ? atoi(e) : 40);''',
     '''        v = ps3_toggle_get("PS3_MK_SPIN_US", e ? atoi(e) : 0);''',
     "spin off: kick default")
# inline stores: lifted guest stores get the same inline fast path the loads have
# Every lifted stw/std/stb/sth was an out-of-line call into ppu_loader.cpp (vm_write32 etc.), and
# each of those called spu_coh_is_reserved -- another out-of-line call -- twice. On the console the
# main PPU thread (the frame limiter in all three games) was hot in vm_write32/vm_write64 and their
# coherence calls. Now the generated header stores inline when the address is ordinary guest
# memory (vm_inl_ok: no diagnostic armed, not the null page / raw SPU windows / gcm ref word / past
# the mapping), no write watch or null sweep is active, and the 128-byte line is not SPU-reserved
# (the bitmap and armed flag are read inline). After the store the line is checked again, as in
# VM_WRITE_COH, and a line reserved meanwhile gets the lock + LR notify (vm_coh_after_store).
# Everything else takes the old out-of-line call. -DPPU_NO_INLINE_STORES turns it off.
SCO = "runtime/spu/spu_coherency.c"
edit(SCO,
     '''static unsigned char s_coh_bitmap[SPU_COH_BITMAP_SZ];''',
     '''unsigned char s_coh_bitmap[SPU_COH_BITMAP_SZ];   /* read inline by ppu_recomp.h stores */''',
     "inline stores: bitmap")
edit(SCO,
     '''static int s_coh_armed;''',
     '''int s_coh_armed;   /* read inline by ppu_recomp.h stores */''',
     "inline stores: armed")

PLD = "runtime/ppu/ppu_loader.cpp"
edit(PLD,
     '''    v = __builtin_bswap64(v); VM_WRITE_COH(a, &v, 8); }
}''',
     '''    v = __builtin_bswap64(v); VM_WRITE_COH(a, &v, 8); }
/* The inline stores in ppu_recomp.h: the line became SPU-reserved between the check and the store. */
void vm_coh_after_store(uint32_t ca, uint32_t n)
{
    const uint64_t llm = spu_lockline_mask_range(ca, n);
    spu_lockline_lock_mask(llm);
    spu_coh_notify_write_from_ppu(ca);
    spu_lockline_unlock_mask(llm);
}
}''',
     "inline stores: after-store notify")

HDR_OLD = '''#define vm_read64(a) vm_read64_inl(a)
#endif
'''
HDR_NEW = '''#define vm_read64(a) vm_read64_inl(a)
#endif

/* Inline guest-store fast paths: plain memory, no watch, line not SPU-reserved (checked again after
 * the store, as VM_WRITE_COH does); everything else goes to the out-of-line vm_write*. */
#ifdef __cplusplus
extern "C" {
#endif
extern int           s_coh_armed;
extern unsigned char s_coh_bitmap[];
extern uint32_t      g_barrier_sync_watch, g_null_sweep_hi;
void vm_coh_after_store(uint32_t ea, uint32_t n);
#ifdef __cplusplus
}
#endif
static inline int vm_coh_res_inl(uint32_t ea)
{
    if (!__atomic_load_n(&s_coh_armed, __ATOMIC_ACQUIRE)) return 0;
    const uint32_t line = ea >> 7;
    return (__atomic_load_n(&s_coh_bitmap[line >> 3], __ATOMIC_RELAXED) >> (line & 7)) & 1u;
}
static inline int vm_st_inl_ok(uint32_t ea, uint32_t n)
{
    return vm_inl_ok(ea, n) && __builtin_expect(!g_barrier_sync_watch && !g_null_sweep_hi, 1) &&
           !vm_coh_res_inl(ea);
}
#define VM_ST_INL(T, raw, slow) do { const uint32_t _ea = (uint32_t)a; \\
    if (vm_st_inl_ok(_ea, sizeof(T))) { \\
        VM_RAW_ST(T, _ea, raw); \\
        __atomic_signal_fence(__ATOMIC_SEQ_CST); \\
        if (__builtin_expect(vm_coh_res_inl(_ea), 0)) vm_coh_after_store(_ea, sizeof(T)); \\
    } else slow; } while (0)
static inline void vm_write8_inl (uint64_t a, uint8_t  v) { VM_ST_INL(uint8_t,  v,                   vm_write8(a, v)); }
static inline void vm_write16_inl(uint64_t a, uint16_t v) { VM_ST_INL(uint16_t, __builtin_bswap16(v), vm_write16(a, v)); }
static inline void vm_write32_inl(uint64_t a, uint32_t v) { VM_ST_INL(uint32_t, __builtin_bswap32(v), vm_write32(a, v)); }
static inline void vm_write64_inl(uint64_t a, uint64_t v) { VM_ST_INL(uint64_t, __builtin_bswap64(v), vm_write64(a, v)); }
#ifndef PPU_NO_INLINE_STORES
#define vm_write8(a, v)  vm_write8_inl(a, v)
#define vm_write16(a, v) vm_write16_inl(a, v)
#define vm_write32(a, v) vm_write32_inl(a, v)
#define vm_write64(a, v) vm_write64_inl(a, v)
#endif
'''
for _g in ("if1", "if2", "fob"):
    edit(__import__("os").path.expanduser("~") + f"/{_g}/infamous2-lle/recompiled/ppu_recomp.h", HDR_OLD, HDR_NEW, f"inline stores: header {_g}")
    edit(__import__("os").path.expanduser("~") + f"/{_g}/infamous2-lle/recompiled/ppu_recomp.h", HDR_OLD, HDR_NEW, f"inline stores: header {_g}")
edit(PLD,
     '''#define PPU_NO_INLINE_LOADS   /* this file defines the out-of-line accessors */''',
     '''#define PPU_NO_INLINE_LOADS   /* this file defines the out-of-line accessors */
#define PPU_NO_INLINE_STORES''',
     "inline stores: loader opt-out")
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
# spu dma fast: SPU transfer plumbing on x86 (vector copies, no mfence, inline channel field writes)
# PC FoB no-draw profile: SPU threads spent ~38% in runtime plumbing. The three biggest single costs:
# (1) gm_copy_from/gm_copy_to moved every DMA 8 bytes per iteration (relaxed atomics never
#     vectorize) -- the hottest instruction of mfc_do_transfer and spu_overlay_note_get;
# (2) mfc_submit put a full mfence on both sides of every command -- needed on ARM64, where host
#     loads and stores reorder across addresses; x86 is TSO (loads stay ordered with loads, stores
#     with stores) and the atomic line ops (GETLLAR/PUTLLC) go through locked instructions, so a
#     compiler barrier keeps the same order. PS3_SPU_DMA_FENCE=1 restores the mfence;
# (3) every wrch of MFC_LSA/EAH/EAL/Size/TagID/WrTagMask (5-6 per DMA) was a call into spu_wrch
#     plus the engine-slot lookup, only to store one field. The lifted code passes those channels as
#     constants, so spu_helpers.h now stores the field inline; MFC_Cmd and every other channel still
#     call spu_wrch. -DSPU_NO_INLINE_WRCH turns it off (spu_channels.c, which defines spu_wrch).
# gm_equal (the reservation-line compare) also compares 32 bytes at a time on x86.
GMA = "runtime/memory/guest_mem_atomic.h"
edit(GMA,
     '''#define GM_RELAXED __ATOMIC_RELAXED
''',
     '''#define GM_RELAXED __ATOMIC_RELAXED
/* x86 (AVX2): bulk copies and compares 32 bytes at a time. An aligned 8-byte part of a vector
 * access is never torn on x86, which is all the per-word atomics below promise. */
#if defined(__x86_64__) && defined(__AVX2__) && !defined(GM_SCALAR_COPY)
#include <immintrin.h>
#define GM_X86_VEC 1
#endif
''',
     "spu dma fast: gm vec include")
edit(GMA,
     '''    for (; i < n && (((uintptr_t)(g + i)) & 7u); i++) d[i] = gm_load8(g + i);
    for (; i + 8 <= n; i += 8) { uint64_t v = gm_load64(g + i); memcpy(d + i, &v, 8); }''',
     '''    for (; i < n && (((uintptr_t)(g + i)) & 7u); i++) d[i] = gm_load8(g + i);
#ifdef GM_X86_VEC
    for (; i + 32 <= n; i += 32)
        _mm256_storeu_si256((__m256i*)(d + i), _mm256_loadu_si256((const __m256i*)(g + i)));
#endif
    for (; i + 8 <= n; i += 8) { uint64_t v = gm_load64(g + i); memcpy(d + i, &v, 8); }''',
     "spu dma fast: gm_copy_from")
edit(GMA,
     '''    for (; i < n && (((uintptr_t)(g + i)) & 7u); i++) gm_store8(g + i, s[i]);
    for (; i + 8 <= n; i += 8) { uint64_t v; memcpy(&v, s + i, 8); gm_store64(g + i, v); }''',
     '''    for (; i < n && (((uintptr_t)(g + i)) & 7u); i++) gm_store8(g + i, s[i]);
#ifdef GM_X86_VEC
    for (; i + 32 <= n; i += 32)
        _mm256_storeu_si256((__m256i*)(g + i), _mm256_loadu_si256((const __m256i*)(s + i)));
#endif
    for (; i + 8 <= n; i += 8) { uint64_t v; memcpy(&v, s + i, 8); gm_store64(g + i, v); }''',
     "spu dma fast: gm_copy_to")
edit(GMA,
     '''static inline int gm_equal(const uint8_t* g, const void* snap, size_t n)
{
    uint8_t buf[256];''',
     '''static inline int gm_equal(const uint8_t* g, const void* snap, size_t n)
{
#ifdef GM_X86_VEC
    if (((uintptr_t)g & 7u) == 0 && (n & 31u) == 0) {
        const uint8_t* s = (const uint8_t*)snap;
        for (size_t i = 0; i < n; i += 32) {
            const __m256i x = _mm256_loadu_si256((const __m256i*)(g + i));
            const __m256i y = _mm256_loadu_si256((const __m256i*)(s + i));
            if ((unsigned)_mm256_movemask_epi8(_mm256_cmpeq_epi8(x, y)) != 0xFFFFFFFFu) return 0;
        }
        return 1;
    }
#endif
    uint8_t buf[256];''',
     "spu dma fast: gm_equal")

DMA = "runtime/spu/spu_dma.h"
edit(DMA,
     '''static inline int mfc_submit(mfc_engine* mfc, spu_context* spu, uint32_t cmd)
{
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    int r = mfc_submit_body(mfc, spu, cmd);
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    return r;
}''',
     '''#if defined(__x86_64__)
/* x86 is TSO: a compiler barrier keeps the order above (spu_channels.c; PS3_SPU_DMA_FENCE=1 = mfence). */
extern volatile int g_spu_dma_fence;
#define MFC_SUBMIT_FENCE() do { if (__builtin_expect(g_spu_dma_fence, 0)) __atomic_thread_fence(__ATOMIC_SEQ_CST); \\
                                else __atomic_signal_fence(__ATOMIC_SEQ_CST); } while (0)
#else
#define MFC_SUBMIT_FENCE() __atomic_thread_fence(__ATOMIC_SEQ_CST)
#endif
static inline int mfc_submit(mfc_engine* mfc, spu_context* spu, uint32_t cmd)
{
    MFC_SUBMIT_FENCE();
    int r = mfc_submit_body(mfc, spu, cmd);
    MFC_SUBMIT_FENCE();
    return r;
}''',
     "spu dma fast: x86 fence")

SCH = "runtime/spu/spu_channels.c"
edit(SCH,
     '''volatile int g_spu_dma_lean = 1;
''',
     '''volatile int g_spu_dma_lean = 1;
/* spu_dma.h, x86: 1 = a full fence around every MFC command (PS3_SPU_DMA_FENCE=1), as on ARM64. */
volatile int g_spu_dma_fence = 0;
''',
     "spu dma fast: fence var")
edit(SCH,
     '''    if (__atomic_exchange_n(&once, 1, __ATOMIC_ACQ_REL)) return;
    ps3_toggle_watch(PS3T_SPU_DMA_LEAN, spu_dma_lean_set);''',
     '''    if (__atomic_exchange_n(&once, 1, __ATOMIC_ACQ_REL)) return;
    { const char* e = getenv("PS3_SPU_DMA_FENCE"); if (e && e[0] == '1') g_spu_dma_fence = 1; }
    ps3_toggle_watch(PS3T_SPU_DMA_LEAN, spu_dma_lean_set);''',
     "spu dma fast: fence env")
edit(SCH,
     '''#include "spu_dma.h"
#include "../../include/ps3emu/log_first.h"   /* PS3_LOG_FIRST */''',
     '''#define SPU_NO_INLINE_WRCH   /* this file defines spu_wrch */
#include "spu_dma.h"
#include "../../include/ps3emu/log_first.h"   /* PS3_LOG_FIRST */''',
     "spu dma fast: wrch opt-out")

HLP = "runtime/spu/spu_helpers.h"
edit(HLP,
     '''#endif /* SPU_HELPERS_H */''',
     '''/* Channel writes that only store an MFC command field: inline when the channel is a constant (the
 * lifted code's case); the command itself and every other channel go to spu_wrch. */
#ifndef SPU_NO_INLINE_WRCH
#ifdef __cplusplus
extern "C"
#endif
void spu_wrch(spu_context* ctx, uint32_t channel, u128 value);
static inline __attribute__((always_inline)) void spu_wrch_inl(spu_context* ctx, uint32_t channel, u128 value)
{
    if (__builtin_constant_p(channel)) {
        switch (channel) {
        case MFC_LSA:       ctx->mfc_lsa = value._u32[0]; return;
        case MFC_EAH:       ctx->mfc_eah = value._u32[0]; return;
        case MFC_EAL:       ctx->mfc_eal = value._u32[0]; return;
        case MFC_Size:      ctx->mfc_size = value._u32[0]; return;
        case MFC_TagID:     ctx->mfc_tag = value._u32[0] & 0x1F; return;
        case MFC_WrTagMask: ctx->mfc_tag_mask = value._u32[0]; return;
        default: break;
        }
    }
    spu_wrch(ctx, channel, value);
}
#define spu_wrch(c, ch, v) spu_wrch_inl(c, ch, v)
#endif

#endif /* SPU_HELPERS_H */''',
     "spu dma fast: inline wrch")
# ppu fast: no fences on plain DMA in the atomic wrapper, hashed HLE dispatch, inlined stores, AVX VMX floats
# PC FoB no-draw profile after patch_spu_dma_fast.py:
# (1) spu_mfc_atomic -- called for EVERY MFC command -- put a full fence on both sides before its
#     body found out the command was not a lock-line op, so every plain GET/PUT paid four mfences
#     (two here, two in mfc_submit). Plain commands now return at once (mfc_submit orders them);
#     on x86 only a GETLLAR keeps the fence in front (its loads are the one thing TSO lets pass this
#     SPU's earlier stores; PUTLLC/PUTLLUC take the lock-line lock, a locked RMW).
#     PS3_SPU_DMA_FENCE=1 = both fences on every lock-line command, as before.
# (2) every HLE import call scanned the PRX export registry (up to 2048 entries, a full scan for
#     every import no PRX serves -- most of them) and then the context-handler table linearly; the
#     console's fios media threads spent 30-44% of their samples in prx_resolve_export. Both are
#     hashed now (rebuilt when the registry changes / the handler table grows; first entry wins).
# (3) the inline guest stores were emitted out of line (vm_write64_inl 8%, vm_write32_inl 4% of the
#     main thread): always_inline.
# (4) vmx_vmaddfp / vaddfp / vsubfp / vnmsubfp worked byte by byte, one lane at a time (vmaddfp alone
#     5.5% of the main thread): AVX2/FMA forms with the same flush (VSCR NJ), NaN rules and fused
#     rounding (the scalar forms stay as *_ref; tools/test_vmx_fast.c compares them bit for bit).
SCH = "runtime/spu/spu_channels.c"
edit(SCH,
     '''static int spu_mfc_atomic(spu_context* ctx, uint32_t cmd)
{
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    int r = spu_mfc_atomic_body(ctx, cmd);
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    return r;
}''',
     '''static int spu_mfc_atomic(spu_context* ctx, uint32_t cmd)
{
    if (cmd != MFC_GETLLAR_CMD && cmd != MFC_PUTLLC_CMD &&
        cmd != MFC_PUTLLUC_CMD && cmd != MFC_PUTQLLUC_CMD)
        return 0;   /* a plain command: mfc_submit orders it */
#if defined(__x86_64__)
    if (g_spu_dma_fence || cmd == MFC_GETLLAR_CMD) __atomic_thread_fence(__ATOMIC_SEQ_CST);
    int r = spu_mfc_atomic_body(ctx, cmd);
    if (g_spu_dma_fence) __atomic_thread_fence(__ATOMIC_SEQ_CST);
    else __atomic_signal_fence(__ATOMIC_SEQ_CST);
    return r;
#else
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    int r = spu_mfc_atomic_body(ctx, cmd);
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
    return r;
#endif
}''',
     "ppu fast: atomic fences")

PRX = "runtime/prx/prx_loader.c"
edit(PRX,
     '''uint32_t prx_resolve_export(uint32_t nid)
{
    for (uint32_t i = 0; i < s_export_reg_n; i++)
        if (s_export_reg[i].nid == nid)
            return s_export_reg[i].guest_addr;
    return 0;
}''',
     '''/* NID -> guest address, open addressing over a copy of the registry (nid 0 = empty slot; NID 0
 * is never registered). Rebuilt on the first lookup after the registry changed (s_xhash_gen).
 * Old tables are never freed: a reader may still hold one, and they change only on module loads. */
typedef struct { uint32_t gen, mask; uint32_t kv[]; } prx_xhash;
static prx_xhash* s_xhash;
static uint32_t s_xhash_gen = 1;
static int s_xhash_lock;
static uint32_t prx_resolve_export_scan(uint32_t nid)
{
    for (uint32_t i = 0; i < s_export_reg_n; i++)
        if (s_export_reg[i].nid == nid)
            return s_export_reg[i].guest_addr;
    return 0;
}
uint32_t prx_resolve_export(uint32_t nid)
{
    const uint32_t gen = __atomic_load_n(&s_xhash_gen, __ATOMIC_ACQUIRE);
    prx_xhash* h = __atomic_load_n(&s_xhash, __ATOMIC_ACQUIRE);
    if (!h || h->gen != gen) {
        while (__atomic_exchange_n(&s_xhash_lock, 1, __ATOMIC_ACQUIRE)) { }
        h = __atomic_load_n(&s_xhash, __ATOMIC_ACQUIRE);
        if (!h || h->gen != gen) {
            const uint32_t n = s_export_reg_n;
            uint32_t size = 64;
            while (size < 2 * n) size <<= 1;
            prx_xhash* nx = (prx_xhash*)calloc(1, sizeof(prx_xhash) + 2 * size * sizeof(uint32_t));
            if (!nx) { __atomic_store_n(&s_xhash_lock, 0, __ATOMIC_RELEASE); return prx_resolve_export_scan(nid); }
            nx->gen = gen; nx->mask = size - 1;
            for (uint32_t i = 0; i < n; i++) {
                const uint32_t k = s_export_reg[i].nid;
                if (!k) continue;
                for (uint32_t s = (k * 2654435761u) & nx->mask;; s = (s + 1) & nx->mask)
                    if (!nx->kv[2 * s] || nx->kv[2 * s] == k) { nx->kv[2 * s] = k; nx->kv[2 * s + 1] = s_export_reg[i].guest_addr; break; }
            }
            __atomic_store_n(&s_xhash, nx, __ATOMIC_RELEASE);
            h = nx;
        }
        __atomic_store_n(&s_xhash_lock, 0, __ATOMIC_RELEASE);
    }
    if (!nid) return prx_resolve_export_scan(nid);
    for (uint32_t s = (nid * 2654435761u) & h->mask;; s = (s + 1) & h->mask) {
        const uint32_t k = h->kv[2 * s];
        if (k == nid) return h->kv[2 * s + 1];
        if (!k) return 0;
    }
}''',
     "ppu fast: prx export hash")
edit(PRX,
     '''    if (s_export_reg_n < PRX_EXPORT_REG_CAP)
        s_export_reg[s_export_reg_n++] = (prx_export_reg_entry){ nid, guest_addr };''',
     '''    __atomic_add_fetch(&s_xhash_gen, 1, __ATOMIC_RELEASE);   /* prx_resolve_export rebuilds */
    if (s_export_reg_n < PRX_EXPORT_REG_CAP)
        s_export_reg[s_export_reg_n++] = (prx_export_reg_entry){ nid, guest_addr };''',
     "ppu fast: prx gen on add")
edit(PRX,
     '''        if (s_export_reg[i].nid == nid) {
            s_export_reg[i].guest_addr = guest_addr;
            return;
        }''',
     '''        if (s_export_reg[i].nid == nid) {
            s_export_reg[i].guest_addr = guest_addr;
            __atomic_add_fetch(&s_xhash_gen, 1, __ATOMIC_RELEASE);
            return;
        }''',
     "ppu fast: prx gen on replace")
edit(PRX,
     '''        if (s_export_reg[i].nid == nid && s_export_reg[i].guest_addr == guest_addr) {
            s_export_reg[i] = s_export_reg[--s_export_reg_n];''',
     '''        if (s_export_reg[i].nid == nid && s_export_reg[i].guest_addr == guest_addr) {
            s_export_reg[i] = s_export_reg[--s_export_reg_n];
            __atomic_add_fetch(&s_xhash_gen, 1, __ATOMIC_RELEASE);''',
     "ppu fast: prx gen on remove")
# The hash and its generation counter are declared above prx_export_register.
edit(PRX,
     '''static void prx_export_register(uint32_t nid, uint32_t guest_addr)
{''',
     '''static uint32_t s_xhash_gen;
static void prx_export_register(uint32_t nid, uint32_t guest_addr)
{''',
     "ppu fast: prx gen forward")

HLE = "runtime/ppu/ppu_hle.cpp"
edit(HLE,
     '''extern "C" void ps3_hle_register_ctx(uint32_t nid, const char* name, hle_ctx_fn fn)
{''',
     '''/* NID -> g_ctx index, rebuilt when the table has grown (entries are only appended); the first
 * entry for a NID wins, as with the linear scan. */
struct HleCtxIndex { uint32_t count, mask; int32_t slot[1]; };
static std::atomic<const HleCtxIndex*> g_ctx_index{nullptr};
static int hle_ctx_find(uint32_t nid)
{
    const uint32_t n = g_ctx_count.load(std::memory_order_acquire);
    const HleCtxIndex* ix = g_ctx_index.load(std::memory_order_acquire);
    if (!ix || ix->count != n) {
        std::lock_guard<std::mutex> lk(g_hle_index_lock);
        ix = g_ctx_index.load(std::memory_order_acquire);
        if (!ix || ix->count != n) {
            uint32_t size = 16;
            while (size < 2 * n) size <<= 1;
            HleCtxIndex* nx = (HleCtxIndex*)malloc(sizeof(HleCtxIndex) + (size - 1) * sizeof(int32_t));
            if (!nx) { for (uint32_t i = 0; i < n; i++) if (g_ctx[i].nid == nid) return (int)i; return -1; }
            nx->count = n; nx->mask = size - 1;
            for (uint32_t i = 0; i < size; i++) nx->slot[i] = -1;
            for (uint32_t i = 0; i < n; i++)
                for (uint32_t h = (g_ctx[i].nid * 2654435761u) & nx->mask;; h = (h + 1) & nx->mask) {
                    if (nx->slot[h] < 0) { nx->slot[h] = (int32_t)i; break; }
                    if (g_ctx[nx->slot[h]].nid == g_ctx[i].nid) break;
                }
            g_ctx_index.store(nx, std::memory_order_release);
            ix = nx;
        }
    }
    for (uint32_t h = (nid * 2654435761u) & ix->mask;; h = (h + 1) & ix->mask) {
        const int32_t k = ix->slot[h];
        if (k < 0) return -1;
        if (g_ctx[k].nid == nid) return k;
    }
}

extern "C" void ps3_hle_register_ctx(uint32_t nid, const char* name, hle_ctx_fn fn)
{''',
     "ppu fast: ctx index")
edit(HLE,
     '''    for (uint32_t i = 0; i < g_ctx_count; i++)
        if (g_ctx[i].nid == nid) {
            ps3_msf("hle:%s", g_ctx[i].name);''',
     '''    if (const int i = hle_ctx_find(nid); i >= 0) {
            ps3_msf("hle:%s", g_ctx[i].name);''',
     "ppu fast: ctx dispatch")

for _g in ("if1", "if2", "fob"):
    H = __import__("os").path.expanduser("~") + f"/{_g}/infamous2-lle/recompiled/ppu_recomp.h"
    for _n in ("8_inl (", "16_inl(", "32_inl(", "64_inl("):
        edit(H, f"static inline void vm_write{_n}", f"static inline __attribute__((always_inline)) void vm_write{_n}",
             f"ppu fast: always_inline store {_n[:2].strip('_')} {_g}")

VMX = "runtime/ppu/ppu_vmx.h"
edit(VMX,
     '''VMX_FBIN(vmx_vaddfp, vmx_f(x) + vmx_f(y), 1)
VMX_FBIN(vmx_vsubfp, vmx_f(x) - vmx_f(y), 1)''',
     '''VMX_FBIN(vmx_vaddfp_ref, vmx_f(x) + vmx_f(y), 1)
VMX_FBIN(vmx_vsubfp_ref, vmx_f(x) - vmx_f(y), 1)''',
     "ppu fast: vmx add ref")
edit(VMX,
     '''VMX_INL void vmx_vmaddfp(VMX_D, VMX_A, VMX_B, VMX_C, uint32_t vscr) {''',
     '''VMX_INL void vmx_vmaddfp_ref(VMX_D, VMX_A, VMX_B, VMX_C, uint32_t vscr) {''',
     "ppu fast: vmx madd ref")
edit(VMX,
     '''VMX_INL void vmx_vnmsubfp(VMX_D, VMX_A, VMX_B, VMX_C, uint32_t vscr) {''',
     '''VMX_INL void vmx_vnmsubfp_ref(VMX_D, VMX_A, VMX_B, VMX_C, uint32_t vscr) {''',
     "ppu fast: vmx nmsub ref")

edit(VMX,
     '''        vmx_sw(r, i, vmx_flush(vmx_fix(vmx_u(-fmaf(x, z, -y))), vscr)); } VMX_OUT; }
''',
     '''        vmx_sw(r, i, vmx_flush(vmx_fix(vmx_u(-fmaf(x, z, -y))), vscr)); } VMX_OUT; }

/* AVX2/FMA forms of the four hot float ops: the same lane results as the *_ref forms above. */
#if defined(__AVX2__) && defined(__FMA__) && !defined(VMX_SCALAR_FLOAT)
#include <immintrin.h>
#define VMX_XV static inline __attribute__((always_inline))
VMX_XV __m128i vmx__ld(const void* p) {      /* big-endian words -> host lanes */
    return _mm_shuffle_epi8(_mm_loadu_si128((const __m128i*)p), _mm_setr_epi8(3,2,1,0, 7,6,5,4, 11,10,9,8, 15,14,13,12));
}
VMX_XV void vmx__st(void* p, __m128i v) {
    _mm_storeu_si128((__m128i*)p, _mm_shuffle_epi8(v, _mm_setr_epi8(3,2,1,0, 7,6,5,4, 11,10,9,8, 15,14,13,12)));
}
VMX_XV __m128i vmx__flush(__m128i x, uint32_t vscr) {   /* NJ: a zero exponent becomes a signed zero */
    if (!(vscr & VMX_NJ)) return x;
    const __m128i den = _mm_cmpeq_epi32(_mm_and_si128(x, _mm_set1_epi32(0x7F800000)), _mm_setzero_si128());
    return _mm_blendv_epi8(x, _mm_and_si128(x, _mm_set1_epi32((int)0x80000000u)), den);
}
VMX_XV __m128i vmx__isnan(__m128i x) {
    return _mm_cmpgt_epi32(_mm_and_si128(x, _mm_set1_epi32(0x7FFFFFFF)), _mm_set1_epi32(0x7F800000));
}
VMX_XV __m128i vmx__fix(__m128i r) {
    return _mm_blendv_epi8(r, _mm_set1_epi32(0x7FC00000), vmx__isnan(r));
}
VMX_XV __m128i vmx__nan2(__m128i r, __m128i a, __m128i b) {  /* NaN precedence: A, B (quieted), else fixed */
    const __m128i q = _mm_set1_epi32(0x7FC00000);
    r = _mm_blendv_epi8(vmx__fix(r), _mm_or_si128(b, q), vmx__isnan(b));
    return _mm_blendv_epi8(r, _mm_or_si128(a, q), vmx__isnan(a));
}
VMX_XV void vmx_vaddfp(VMX_D, VMX_A, VMX_B, uint32_t vscr) {
    const __m128i x = vmx__flush(vmx__ld(a_), vscr), y = vmx__flush(vmx__ld(b_), vscr);
    const __m128i z = _mm_castps_si128(_mm_add_ps(_mm_castsi128_ps(x), _mm_castsi128_ps(y)));
    vmx__st(d_, vmx__flush(vmx__nan2(z, x, y), vscr));
}
VMX_XV void vmx_vsubfp(VMX_D, VMX_A, VMX_B, uint32_t vscr) {
    const __m128i x = vmx__flush(vmx__ld(a_), vscr), y = vmx__flush(vmx__ld(b_), vscr);
    const __m128i z = _mm_castps_si128(_mm_sub_ps(_mm_castsi128_ps(x), _mm_castsi128_ps(y)));
    vmx__st(d_, vmx__flush(vmx__nan2(z, x, y), vscr));
}
VMX_XV void vmx_vmaddfp(VMX_D, VMX_A, VMX_B, VMX_C, uint32_t vscr) {   /* a*c + b, one rounding */
    const __m128 x = _mm_castsi128_ps(vmx__flush(vmx__ld(a_), vscr)), y = _mm_castsi128_ps(vmx__flush(vmx__ld(b_), vscr)),
                 z = _mm_castsi128_ps(vmx__flush(vmx__ld(c_), vscr));
    vmx__st(d_, vmx__flush(vmx__fix(_mm_castps_si128(_mm_fmadd_ps(x, z, y))), vscr));
}
VMX_XV void vmx_vnmsubfp(VMX_D, VMX_A, VMX_B, VMX_C, uint32_t vscr) {  /* -(a*c - b), one rounding */
    const __m128 x = _mm_castsi128_ps(vmx__flush(vmx__ld(a_), vscr)), y = _mm_castsi128_ps(vmx__flush(vmx__ld(b_), vscr)),
                 z = _mm_castsi128_ps(vmx__flush(vmx__ld(c_), vscr));
    const __m128i m = _mm_xor_si128(_mm_castps_si128(_mm_fmsub_ps(x, z, y)), _mm_set1_epi32((int)0x80000000u));
    vmx__st(d_, vmx__flush(vmx__fix(m), vscr));
}
#else
#define vmx_vaddfp   vmx_vaddfp_ref
#define vmx_vsubfp   vmx_vsubfp_ref
#define vmx_vmaddfp  vmx_vmaddfp_ref
#define vmx_vnmsubfp vmx_vnmsubfp_ref
#endif
''',
     "ppu fast: vmx avx")

# ppu fast: vperm with pshufb (tools/ppu_vperm_fast.py rewrites the lifted byte loops into vmx_vperm calls)
edit(VMX, "VMX_XV void vmx__st(void* p, __m128i v) {", "/* vperm on the registers' big-endian bytes: byte i = (a:b)[c[i] & 31]. Exact; one pshufb per source. */\n#define VMX_HAVE_VPERM 1\nVMX_XV void vmx_vperm(void* d, const void* a, const void* b, const void* c) {\n    const __m128i C = _mm_loadu_si128((const __m128i*)c);\n    const __m128i i = _mm_and_si128(C, _mm_set1_epi8(0x0F));\n    const __m128i ra = _mm_shuffle_epi8(_mm_loadu_si128((const __m128i*)a), i);\n    const __m128i rb = _mm_shuffle_epi8(_mm_loadu_si128((const __m128i*)b), i);\n    const __m128i hi = _mm_slli_epi16(C, 3);   /* bit 4 -> bit 7 of each byte: blendv's selector */\n    _mm_storeu_si128((__m128i*)d, _mm_blendv_epi8(ra, rb, hi));\n}\nVMX_XV void vmx__st(void* p, __m128i v) {", "ppu fast: vperm sse")
edit(VMX, "#define vmx_vnmsubfp vmx_vnmsubfp_ref\n#endif\n", '#define vmx_vnmsubfp vmx_vnmsubfp_ref\n#endif\n#ifndef VMX_HAVE_VPERM\nVMX_INL void vmx_vperm(void* d, const void* a_, const void* b_, const void* c_) {\n    const uint8_t* a = (const uint8_t*)a_; const uint8_t* b = (const uint8_t*)b_; const uint8_t* c = (const uint8_t*)c_;\n    uint8_t t[16];\n    for (int i = 0; i < 16; i++) { const uint8_t s = c[i] & 0x1F; t[i] = s < 16 ? a[s] : b[s - 16]; }\n    memcpy(d, t, 16);\n}\n#endif\n', "ppu fast: vperm fallback")
# spu ffast: SPU single-precision fm/fa/fs/fma/fms/fnms in native single precision, still bit exact
# PC FoB no-draw profile: lifted SPU code is ~64% of SPU-thread samples and ~26% of that is the
# AVX2 float emulation (widen to double, truncate the 29 low bits, range-check every operand: ~35
# instructions, half of them 256-bit, per spu_fm). The SPU rounds toward zero; the host rounds to
# nearest. The native result r = RN(v) differs from RZ(v) by at most one unit, and only when the
# exact residual v - r has the opposite sign to r -- then RZ(v) is r with its magnitude one unit
# lower (the bit pattern minus one, also across a power of two). The residual is exact:
#   fm:  fmsub(x, y, r)                       (TwoProduct; result kept >= 2^-79 so it is normal)
#   fa:  TwoSum(x, y)                         (exact; inputs kept below 2^126 so it cannot overflow)
#   fma: fma_pd(x, y, z - r) in double        (z - r exact in double when their exponents differ
#                                              by at most 28; the sign of the double rounding of
#                                              v - r is the sign of v - r)
# Every lane must have ordinary inputs (biased exponent 1..254 or +-0) and an ordinary result
# (or zero, which the SPU returns as +0); any other vector goes to the exact AVX2 path as before
# (out of line when on). The MXCSR stays at its default (round to nearest, no FTZ/DAZ): nothing in the
# runtime changes it. OFF by default (-DSPU_FFAST_ON): a micro-benchmark measured fm -10%, fa -7%, fma +10% time vs the
# exact AVX2 path, ~3% overall -- not worth the risk. tools/test_spu_ffast.c checks
# the new forms against the scalar exact forms (spu_*_ref) bit for bit.
SFH = "runtime/spu/spu_helpers.h"
edit(SFH,
     '''SPU__XV_INLINE u128 spu_fa(u128 a, u128 b) { return spu__xv_fa(a, b, 0); }
SPU__XV_INLINE u128 spu_fs(u128 a, u128 b) { return spu__xv_fa(a, b, 0x80000000u); }
SPU__XV_INLINE u128 spu_fm(u128 a, u128 b) {
    const __m128i x = spu__xv_ld(a), y = spu__xv_ld(b);''',
     '''#if defined(__FMA__) && defined(SPU_FFAST_ON)   /* measured ~3% faster only: off */
#define SPU_FFAST 1
#define SPU__FX SPU__XV_SLOW
#else
#define SPU__FX SPU__XV_INLINE
#endif
SPU__FX u128 spu__xv_fa_x(u128 a, u128 b, uint32_t negb) { return spu__xv_fa(a, b, negb); }
SPU__FX u128 spu__xv_fm_x(u128 a, u128 b) {
    const __m128i x = spu__xv_ld(a), y = spu__xv_ld(b);''',
     "spu ffast: exact fa/fm out of line")
edit(SFH,
     '''SPU__XV_INLINE u128 spu_fma(u128 a, u128 b, u128 c)  { return spu__xv_fma(a, b, c, 0, 0); }
SPU__XV_INLINE u128 spu_fms(u128 a, u128 b, u128 c)  { return spu__xv_fma(a, b, c, 0, 0x80000000u); }
SPU__XV_INLINE u128 spu_fnms(u128 a, u128 b, u128 c) { return spu__xv_fma(a, b, c, 0x80000000u, 0); }''',
     '''SPU__FX u128 spu__xv_fma_x(u128 a, u128 b, u128 c, uint32_t negp, uint32_t negc) {
    return spu__xv_fma(a, b, c, negp, negc);
}
#ifdef SPU_FFAST
/* Native single precision, corrected to round-toward-zero (tools/patch_spu_ffast.py). */
SPU__XV_INLINE __m128i spu__ff_range(__m128i r, int lo, int hi) {   /* biased exponent lo..hi, or +-0 */
    const __m128i t = _mm_sub_epi32(spu__xv_bexp(r), _mm_set1_epi32(lo));
    return _mm_or_si128(_mm_cmpeq_epi32(_mm_min_epu32(t, _mm_set1_epi32(hi - lo)), t), spu__xv_iszero(r));
}
/* r one unit toward zero where the residual e is nonzero, of the other sign, and r is not zero. */
SPU__XV_INLINE __m128i spu__ff_fix(__m128i r, __m128i e_sign_word, __m128i e_zero) {
    const __m128i fix = _mm_andnot_si128(_mm_or_si128(e_zero, spu__xv_iszero(r)),
                                         _mm_srai_epi32(_mm_xor_si128(e_sign_word, r), 31));
    return _mm_add_epi32(r, fix);
}
SPU__XV_INLINE u128 spu__ff_fa(u128 a, u128 b, uint32_t negb) {
    const __m128i xi = spu__xv_ld(a), yi = _mm_xor_si128(spu__xv_ld(b), _mm_set1_epi32((int)negb));
    const __m128 x = _mm_castsi128_ps(xi), y = _mm_castsi128_ps(yi);
    const __m128 s = _mm_add_ps(x, y), bb = _mm_sub_ps(s, x);
    const __m128i e = _mm_castps_si128(_mm_add_ps(_mm_sub_ps(x, _mm_sub_ps(s, bb)), _mm_sub_ps(y, bb)));
    const __m128i si = _mm_castps_si128(s);
    __m128i o = spu__ff_fix(si, e, spu__xv_iszero(e));
    /* inputs below 2^126: TwoSum's s - x cannot overflow */
    const __m128i ok = _mm_and_si128(_mm_and_si128(spu__ff_range(xi, 1, 252), spu__ff_range(yi, 1, 252)),
                                     _mm_and_si128(spu__ff_range(si, 1, 254), spu__ff_range(o, 1, 254)));
    if (__builtin_expect(!spu__xv_all4(ok), 0)) return spu__xv_fa_x(a, b, negb);
    return spu__xv_st(spu__xv_pos0(o, spu__xv_iszero(o)));
}
SPU__XV_INLINE u128 spu_fa(u128 a, u128 b) { return spu__ff_fa(a, b, 0); }
SPU__XV_INLINE u128 spu_fs(u128 a, u128 b) { return spu__ff_fa(a, b, 0x80000000u); }
SPU__XV_INLINE u128 spu_fm(u128 a, u128 b) {
    const __m128i xi = spu__xv_ld(a), yi = spu__xv_ld(b);
    const __m128 x = _mm_castsi128_ps(xi), y = _mm_castsi128_ps(yi);
    const __m128 r = _mm_mul_ps(x, y);
    const __m128i ri = _mm_castps_si128(r), e = _mm_castps_si128(_mm_fmsub_ps(x, y, r));
    const __m128i o = spu__ff_fix(ri, e, spu__xv_iszero(e));
    const __m128i ok = _mm_and_si128(_mm_and_si128(spu__xv_plain0(xi), spu__xv_plain0(yi)), spu__ff_range(ri, 48, 254));
    if (__builtin_expect(!spu__xv_all4(ok), 0)) return spu__xv_fm_x(a, b);
    return spu__xv_st(spu__xv_pos0(o, spu__xv_iszero(o)));
}
SPU__XV_INLINE u128 spu__ff_fma(u128 a, u128 b, u128 c, uint32_t negp, uint32_t negc) {
    const __m128i xi = _mm_xor_si128(spu__xv_ld(a), _mm_set1_epi32((int)negp)), yi = spu__xv_ld(b);
    const __m128i zi = _mm_xor_si128(spu__xv_ld(c), _mm_set1_epi32((int)negc));
    const __m128 r = _mm_fmadd_ps(_mm_castsi128_ps(xi), _mm_castsi128_ps(yi), _mm_castsi128_ps(zi));
    const __m128i ri = _mm_castps_si128(r);
    const __m256d w = _mm256_fmadd_pd(spu__xv_wide(xi), spu__xv_wide(yi),
                                      _mm256_sub_pd(spu__xv_wide(zi), spu__xv_wide(ri)));
    const __m256i hi32 = _mm256_setr_epi32(1, 3, 5, 7, 1, 3, 5, 7);
    const __m128i wsign = _mm256_castsi256_si128(_mm256_permutevar8x32_epi32(_mm256_castpd_si256(w), hi32));
    const __m128i wzero = _mm256_castsi256_si128(_mm256_permutevar8x32_epi32(
        _mm256_castpd_si256(_mm256_cmp_pd(w, _mm256_setzero_pd(), _CMP_EQ_OQ)), hi32));
    const __m128i o = spu__ff_fix(ri, wsign, wzero);
    /* z - r is exact in double when the exponents differ by at most 28 (or either is zero) */
    const __m128i gap = _mm_abs_epi32(_mm_sub_epi32(spu__xv_bexp(zi), spu__xv_bexp(ri)));
    const __m128i dex = _mm_or_si128(_mm_cmpgt_epi32(_mm_set1_epi32(29), gap),
                                     _mm_or_si128(spu__xv_iszero(zi), spu__xv_iszero(ri)));
    const __m128i ok = _mm_and_si128(_mm_and_si128(_mm_and_si128(spu__xv_plain0(xi), spu__xv_plain0(yi)),
                                                   _mm_and_si128(spu__xv_plain0(zi), dex)),
                                     _mm_and_si128(spu__ff_range(ri, 1, 254), spu__ff_range(o, 1, 254)));
    if (__builtin_expect(!spu__xv_all4(ok), 0)) return spu__xv_fma_x(a, b, c, negp, negc);
    return spu__xv_st(spu__xv_pos0(o, spu__xv_iszero(o)));
}
SPU__XV_INLINE u128 spu_fma(u128 a, u128 b, u128 c)  { return spu__ff_fma(a, b, c, 0, 0); }
SPU__XV_INLINE u128 spu_fms(u128 a, u128 b, u128 c)  { return spu__ff_fma(a, b, c, 0, 0x80000000u); }
SPU__XV_INLINE u128 spu_fnms(u128 a, u128 b, u128 c) { return spu__ff_fma(a, b, c, 0x80000000u, 0); }
#else
SPU__XV_INLINE u128 spu_fa(u128 a, u128 b) { return spu__xv_fa_x(a, b, 0); }
SPU__XV_INLINE u128 spu_fs(u128 a, u128 b) { return spu__xv_fa_x(a, b, 0x80000000u); }
SPU__XV_INLINE u128 spu_fm(u128 a, u128 b) { return spu__xv_fm_x(a, b); }
SPU__XV_INLINE u128 spu_fma(u128 a, u128 b, u128 c)  { return spu__xv_fma_x(a, b, c, 0, 0); }
SPU__XV_INLINE u128 spu_fms(u128 a, u128 b, u128 c)  { return spu__xv_fma_x(a, b, c, 0, 0x80000000u); }
SPU__XV_INLINE u128 spu_fnms(u128 a, u128 b, u128 c) { return spu__xv_fma_x(a, b, c, 0x80000000u, 0); }
#endif''',
     "spu ffast: native fast paths")
# spu contention: no atomic writes to shared hot globals on every SPU reservation / DMA PUT
# PC FoB profile (perf_fast2): the hottest instructions of spu_wrch and coh_mark_line were the
# writes to process-wide globals that every SPU thread (and every PPU store) touches -- each one
# moves that cache line to the writing core, and on the console the six SPU threads and the main
# PPU thread sit on two core complexes:
#  - spu_wrch PUTLLC: `lock incl g_spu_putllc_count` on every PUTLLC, a counter nothing reads;
#    now only with -DSPU_PUTLLC_COUNT.
#  - coh_mark_line (every GETLLAR): an atomic OR into the reserved-line bitmap and a SEQ_CST store
#    (xchg) to s_coh_armed -- both are read inline by EVERY PPU store, so every reservation also
#    evicted those lines from the PPU core. The bit is never cleared and s_coh_armed is never reset:
#    when both are already set, only the full fence the RMW gave is kept.
#  - ps3_memkick_slow (every SPU write to main memory while a guest thread sleeps in a short
#    usleep -- the main thread, most of the frame): an atomic add to s_mk_gen and an atomic exchange
#    of s_mk_pending even when a wake-up was already pending. Now: a plain load first; the
#    generation is bumped only while someone spins on it (PS3_MK_SPIN_US > 0).
CHN = "runtime/spu/spu_channels.c"
edit(CHN,
     '''        __atomic_fetch_add(&g_spu_putllc_count, 1u, __ATOMIC_RELAXED);   /* read by the PM flow trace */''',
     '''#ifdef SPU_PUTLLC_COUNT   /* spu contention: a shared counter nothing reads */
        __atomic_fetch_add(&g_spu_putllc_count, 1u, __ATOMIC_RELAXED);   /* read by the PM flow trace */
#endif''',
     "spu contention: putllc counter")
COH = "runtime/spu/spu_coherency.c"
edit(COH,
     '''    const unsigned char bit = (unsigned char)(1u << (line & 7));
    const unsigned char was = __atomic_fetch_or(&s_coh_bitmap[line >> 3], bit, __ATOMIC_SEQ_CST);
    __atomic_store_n(&s_coh_armed, 1, __ATOMIC_SEQ_CST);
    if (!(was & bit)) spu_process_barrier();''',
     '''    const unsigned char bit = (unsigned char)(1u << (line & 7));
    /* Already marked and armed (neither is ever cleared): read-only, so the line stays shared
     * with the PPU cores that read both on every store; keep the RMW's full fence. */
    if ((__atomic_load_n(&s_coh_bitmap[line >> 3], __ATOMIC_ACQUIRE) & bit) &&
        __atomic_load_n(&s_coh_armed, __ATOMIC_ACQUIRE)) {
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        return;
    }
    const unsigned char was = __atomic_fetch_or(&s_coh_bitmap[line >> 3], bit, __ATOMIC_SEQ_CST);
    __atomic_store_n(&s_coh_armed, 1, __ATOMIC_SEQ_CST);
    if (!(was & bit)) spu_process_barrier();''',
     "spu contention: coh_mark_line")
edit(COH,
     '''static unsigned s_mk_gen;   /* every kick: a spinning waiter watches it change */
void ps3_memkick_slow(void)
{
    __atomic_add_fetch(&s_mk_gen, 1, __ATOMIC_RELEASE);
    if (__atomic_exchange_n(&s_mk_pending, 1, __ATOMIC_ACQ_REL)) return;''',
     '''static unsigned s_mk_gen;   /* every kick: a spinning waiter watches it change */
static int s_mk_spinners;   /* waiters spinning on s_mk_gen (PS3_MK_SPIN_US > 0) */
void ps3_memkick_slow(void)
{
    if (__atomic_load_n(&s_mk_spinners, __ATOMIC_ACQUIRE)) __atomic_add_fetch(&s_mk_gen, 1, __ATOMIC_RELEASE);
    if (__atomic_load_n(&s_mk_pending, __ATOMIC_ACQUIRE)) return;   /* a wake-up is already on its way */
    if (__atomic_exchange_n(&s_mk_pending, 1, __ATOMIC_ACQ_REL)) return;''',
     "spu contention: memkick")
edit(COH,
     '''            __atomic_add_fetch(&g_mk_waiters, 1, __ATOMIC_SEQ_CST);
            const unsigned g0 = __atomic_load_n(&s_mk_gen, __ATOMIC_ACQUIRE);''',
     '''            __atomic_add_fetch(&s_mk_spinners, 1, __ATOMIC_SEQ_CST);
            __atomic_add_fetch(&g_mk_waiters, 1, __ATOMIC_SEQ_CST);
            const unsigned g0 = __atomic_load_n(&s_mk_gen, __ATOMIC_ACQUIRE);''',
     "spu contention: memkick spinners in")
edit(COH,
     '''            __atomic_sub_fetch(&g_mk_waiters, 1, __ATOMIC_SEQ_CST);
            if (hit) {''',
     '''            __atomic_sub_fetch(&g_mk_waiters, 1, __ATOMIC_SEQ_CST);
            __atomic_sub_fetch(&s_mk_spinners, 1, __ATOMIC_SEQ_CST);
            if (hit) {''',
     "spu contention: memkick spinners out")
# spu contention A/B switch: -DSPU_NO_CONTENTION_FIX (or #define at the file top) restores the old
# hot-path atomics of patch_spu_contention.py (putllc counter, coh_mark_line RMW, memkick add/xchg),
# so the fix can be measured against the same build.
edit(CHN,
     '''#ifdef SPU_PUTLLC_COUNT   /* spu contention: a shared counter nothing reads */''',
     '''#if defined(SPU_PUTLLC_COUNT) || defined(SPU_NO_CONTENTION_FIX)   /* spu contention: a shared counter nothing reads */''',
     "spu contention ab: putllc")
edit(COH,
     '''    if ((__atomic_load_n(&s_coh_bitmap[line >> 3], __ATOMIC_ACQUIRE) & bit) &&
        __atomic_load_n(&s_coh_armed, __ATOMIC_ACQUIRE)) {
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        return;
    }''',
     '''#ifndef SPU_NO_CONTENTION_FIX
    if ((__atomic_load_n(&s_coh_bitmap[line >> 3], __ATOMIC_ACQUIRE) & bit) &&
        __atomic_load_n(&s_coh_armed, __ATOMIC_ACQUIRE)) {
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        return;
    }
#endif''',
     "spu contention ab: coh_mark_line")
edit(COH,
     '''    if (__atomic_load_n(&s_mk_spinners, __ATOMIC_ACQUIRE)) __atomic_add_fetch(&s_mk_gen, 1, __ATOMIC_RELEASE);
    if (__atomic_load_n(&s_mk_pending, __ATOMIC_ACQUIRE)) return;   /* a wake-up is already on its way */''',
     '''#ifndef SPU_NO_CONTENTION_FIX
    if (__atomic_load_n(&s_mk_spinners, __ATOMIC_ACQUIRE)) __atomic_add_fetch(&s_mk_gen, 1, __ATOMIC_RELEASE);
    if (__atomic_load_n(&s_mk_pending, __ATOMIC_ACQUIRE)) return;   /* a wake-up is already on its way */
#else
    __atomic_add_fetch(&s_mk_gen, 1, __ATOMIC_RELEASE);
#endif''',
     "spu contention ab: memkick")
# spu contention fix reverted (BC-250, 2026-11-01): with it FoB stalls for good at the menu load (the
# step after load_menu_catalog.log never runs; SPUs idle, main thread pacing a loading screen); with
# -DSPU_NO_CONTENTION_FIX the same build plays on. Off by default now; -DSPU_CONTENTION_FIX brings it back.
for _f in (CHN, COH):
    edit(_f, '''#include''', '''#ifndef SPU_CONTENTION_FIX   /* spu contention fix off: it stalled FoB's menu load */
#  define SPU_NO_CONTENTION_FIX 1
#endif
#include''', "spu contention off: " + _f)
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
# tdump waits: the guest thread dump (debug server `threads`, PS3_THREAD_DUMP) names what each guest
# thread is blocked in. The dispatchers already kept the in-flight lv2 syscall number (g_sc_inflight)
# and HLE import name (g_hle_inflight) per guest thread id; now the syscall's first arguments and
# both start times are kept too, and the dump prints "in sys N(r3,r4,r5) 12.3 s" / "in <hle> 4.0 s".
# A stall at a load screen (FoB after a death, 2026-11-01) then reads off the semaphore / lwmutex /
# event queue each thread sits on, without a debugger.
LDR = "runtime/ppu/ppu_loader.cpp"
HLE = "runtime/ppu/ppu_hle.cpp"
PPT = "runtime/syscalls/sys_ppu_thread.c"
edit(LDR,
     '''extern "C" uint32_t g_sc_inflight[PS3_SC_INFLIGHT_MAX] = { 0 };''',
     '''extern "C" uint32_t g_sc_inflight[PS3_SC_INFLIGHT_MAX] = { 0 };
/* tdump waits: the in-flight syscall's r3..r5 and its start (ps3_ft_now ns). */
extern "C" uint32_t g_sc_inflight_arg[PS3_SC_INFLIGHT_MAX][3] = { { 0 } };
extern "C" uint64_t g_sc_inflight_t0[PS3_SC_INFLIGHT_MAX] = { 0 };''',
     "tdump waits: sc arrays")
edit(LDR,
     '''      if (t < PS3_SC_INFLIGHT_MAX) g_sc_inflight[t] = (uint32_t)num; }''',
     '''      if (t < PS3_SC_INFLIGHT_MAX) {
          g_sc_inflight_arg[t][0] = (uint32_t)ctx->gpr[3]; g_sc_inflight_arg[t][1] = (uint32_t)ctx->gpr[4];
          g_sc_inflight_arg[t][2] = (uint32_t)ctx->gpr[5]; g_sc_inflight_t0[t] = ps3_ft_now();
          g_sc_inflight[t] = (uint32_t)num; } }''',
     "tdump waits: sc set")
edit(HLE,
     '''extern "C" const char* g_hle_inflight[PS3_HLE_INFLIGHT_MAX] = { nullptr };''',
     '''extern "C" const char* g_hle_inflight[PS3_HLE_INFLIGHT_MAX] = { nullptr };
extern "C" uint64_t g_hle_inflight_t0[PS3_HLE_INFLIGHT_MAX] = { 0 };   /* tdump waits */
static inline uint64_t tdw_now(void)   /* the clock of ps3_ft_now (CLOCK_MONOTONIC ns) */
{
#ifdef _WIN32
    return 0;
#else
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
#endif
}''',
     "tdump waits: hle array")
edit(HLE,
     '''      if (t < PS3_HLE_INFLIGHT_MAX) g_hle_inflight[t] = e->name; }''',
     '''      if (t < PS3_HLE_INFLIGHT_MAX) { g_hle_inflight_t0[t] = tdw_now(); g_hle_inflight[t] = e->name; } }''',
     "tdump waits: hle set")
edit(PPT,
     '''void ps3_thread_dump_to(FILE* o, const char* why)
{''',
     '''#define TDW_MAX 64
extern uint32_t g_sc_inflight[TDW_MAX];
extern uint32_t g_sc_inflight_arg[TDW_MAX][3];
extern uint64_t g_sc_inflight_t0[TDW_MAX];
extern const char* g_hle_inflight[TDW_MAX];
extern uint64_t g_hle_inflight_t0[TDW_MAX];
/* tdump waits: what guest thread `tid` is inside right now (syscall / HLE import), and for how long. */
static void tdump_wait_of(FILE* o, unsigned tid)
{
    if (tid >= TDW_MAX) return;
    const uint64_t now = ps3_ft_now();
    const uint32_t sc = __atomic_load_n(&g_sc_inflight[tid], __ATOMIC_RELAXED);
    const char* h = __atomic_load_n(&g_hle_inflight[tid], __ATOMIC_RELAXED);
    if (sc) {
        const uint64_t t0 = g_sc_inflight_t0[tid];
        fprintf(o, " | in sys %u(0x%X,0x%X,0x%X) %.1fs", sc, g_sc_inflight_arg[tid][0], g_sc_inflight_arg[tid][1],
                g_sc_inflight_arg[tid][2], t0 && now > t0 ? (double)(now - t0) / 1e9 : 0.0);
    }
    if (h) {
        const uint64_t t0 = g_hle_inflight_t0[tid];
        fprintf(o, " | in %s %.1fs", h, t0 && now > t0 ? (double)(now - t0) / 1e9 : 0.0);
    }
}
void ps3_thread_dump_to(FILE* o, const char* why)
{''',
     "tdump waits: printer")
edit(PPT,
     '''                fprintf(o, " 0x%x", td_rd32(next + 20)); /* low word of saved LR at +16 */
                sp = next;
            }
            fputc('\\n', o);''',
     '''                fprintf(o, " 0x%x", td_rd32(next + 20)); /* low word of saved LR at +16 */
                sp = next;
            }
            tdump_wait_of(o, (unsigned)(i + 1));
            fputc('\\n', o);''',
     "tdump waits: per thread")
# devpad: controller input for development tools, in memory (no file polling), port 0 only.
#  - inject: ps3_devpad_press(mask, polls, lx, ly, rx, ry): hold buttons (PAD_SCRIPT mask encoding,
#    DIGITAL2 << 8 | DIGITAL1) and the sticks (0..255, 128 centred; -1 leaves a stick alone) for
#    `polls` reads of the pad. The PS5 debug server's `pad` command drives it.
#  - record: ps3_devpad_record(path) writes every change of the final pad state (the player's and
#    anything injected) as "t_ms d1 d2 lx ly rx ry"; ps3_devpad_record(NULL) stops.
#  - replay: ps3_devpad_replay(path) plays such a file back from now (time-based), on top of the
#    player's input; it ends by itself at the file's end.
# A recorded play session can then be replayed on the console or the BC-250 to reproduce what the
# player saw (FoB's fall through an unloaded building, 2026-11-01).
PAD = "libs/input/cellPad.c"
edit(PAD,
     '''s32 cellPadGetData(u32 port_no, CellPadData* data_guest)''',
     '''/* devpad (tools/patch_devpad.py) */
static volatile unsigned s_dp_mask; static volatile int s_dp_polls, s_dp_l[2] = { -1, -1 }, s_dp_r[2] = { -1, -1 };
void ps3_devpad_press(unsigned mask, int polls, int lx, int ly, int rx, int ry)
{
    s_dp_l[0] = lx; s_dp_l[1] = ly; s_dp_r[0] = rx; s_dp_r[1] = ry;
    s_dp_mask = mask;
    __atomic_store_n(&s_dp_polls, polls > 0 ? polls : 6, __ATOMIC_RELEASE);
}
static FILE* s_dp_rec; static unsigned long long s_dp_rec_t0; static unsigned s_dp_last[6] = { ~0u };
static FILE* s_dp_play; static unsigned long long s_dp_play_t0; static int s_dp_next_ok;
static unsigned s_dp_next_t, s_dp_next[6], s_dp_cur[6] = { 0, 0, 128, 128, 128, 128 };
static void* s_dp_lock_dummy;
int ps3_devpad_record(const char* path)
{
    if (s_dp_rec) { fclose(s_dp_rec); s_dp_rec = NULL; }
    if (!path || !*path) return 0;
    s_dp_rec = fopen(path, "w");
    s_dp_rec_t0 = GetTickCount64();
    s_dp_last[0] = ~0u;
    return s_dp_rec ? 0 : -1;
}
static int dp_read_next(void)
{
    char line[128];   /* fgets + sscanf: fscanf would be a new import on the PS5 */
    return s_dp_play && fgets(line, sizeof line, s_dp_play) &&
           sscanf(line, "%u %u %u %u %u %u %u", &s_dp_next_t, &s_dp_next[0], &s_dp_next[1],
                  &s_dp_next[2], &s_dp_next[3], &s_dp_next[4], &s_dp_next[5]) == 7;
}
int ps3_devpad_replay(const char* path)
{
    if (s_dp_play) { fclose(s_dp_play); s_dp_play = NULL; }
    if (!path || !*path) return 0;
    s_dp_play = fopen(path, "r");
    if (!s_dp_play) return -1;
    s_dp_play_t0 = GetTickCount64();
    s_dp_cur[0] = s_dp_cur[1] = 0; s_dp_cur[2] = s_dp_cur[3] = s_dp_cur[4] = s_dp_cur[5] = 128;
    s_dp_next_ok = dp_read_next();
    (void)s_dp_lock_dummy;
    return 0;
}

s32 cellPadGetData(u32 port_no, CellPadData* data_guest)''',
     "devpad: api")
edit(PAD,
     '''    data->button[CELL_PAD_BTN_OFFSET_ANALOG_RIGHT_X] = hs->analog_rx;
    data->button[CELL_PAD_BTN_OFFSET_ANALOG_RIGHT_Y] = hs->analog_ry;
    data->button[CELL_PAD_BTN_OFFSET_ANALOG_LEFT_X]  = hs->analog_lx;
    data->button[CELL_PAD_BTN_OFFSET_ANALOG_LEFT_Y]  = hs->analog_ly;''',
     '''    /* devpad: injected presses and a replay, then the recorder (port 0) */
    if (port_no == 0) {
        if (s_dp_play) {
            const unsigned long long el = GetTickCount64() - s_dp_play_t0;
            while (s_dp_next_ok && el >= s_dp_next_t) { memcpy(s_dp_cur, s_dp_next, sizeof s_dp_cur); s_dp_next_ok = dp_read_next(); }
            data->button[CELL_PAD_BTN_OFFSET_DIGITAL1] |= (u16)s_dp_cur[0];
            data->button[CELL_PAD_BTN_OFFSET_DIGITAL2] |= (u16)s_dp_cur[1];
            hs->analog_lx = (u8)s_dp_cur[2]; hs->analog_ly = (u8)s_dp_cur[3];
            hs->analog_rx = (u8)s_dp_cur[4]; hs->analog_ry = (u8)s_dp_cur[5];
            if (!s_dp_next_ok) { fclose(s_dp_play); s_dp_play = NULL; printf("[devpad] replay finished\\n"); }
        }
        if (__atomic_load_n(&s_dp_polls, __ATOMIC_ACQUIRE) > 0) {
            __atomic_sub_fetch(&s_dp_polls, 1, __ATOMIC_ACQ_REL);
            data->button[CELL_PAD_BTN_OFFSET_DIGITAL1] |= (u16)(s_dp_mask & 0xFF);
            data->button[CELL_PAD_BTN_OFFSET_DIGITAL2] |= (u16)((s_dp_mask >> 8) & 0xFF);
            if (s_dp_l[0] >= 0) { hs->analog_lx = (u8)s_dp_l[0]; hs->analog_ly = (u8)s_dp_l[1]; }
            if (s_dp_r[0] >= 0) { hs->analog_rx = (u8)s_dp_r[0]; hs->analog_ry = (u8)s_dp_r[1]; }
        }
        if (s_dp_rec) {
            const unsigned v[6] = { data->button[CELL_PAD_BTN_OFFSET_DIGITAL1] & 0xFFu,
                                    data->button[CELL_PAD_BTN_OFFSET_DIGITAL2] & 0xFFu,
                                    hs->analog_lx, hs->analog_ly, hs->analog_rx, hs->analog_ry };
            if (memcmp(v, s_dp_last, sizeof v)) {
                memcpy(s_dp_last, v, sizeof v);
                fprintf(s_dp_rec, "%llu %u %u %u %u %u %u\\n", GetTickCount64() - s_dp_rec_t0, v[0], v[1], v[2], v[3], v[4], v[5]);
            }
        }
    }
    data->button[CELL_PAD_BTN_OFFSET_ANALOG_RIGHT_X] = hs->analog_rx;
    data->button[CELL_PAD_BTN_OFFSET_ANALOG_RIGHT_Y] = hs->analog_ry;
    data->button[CELL_PAD_BTN_OFFSET_ANALOG_LEFT_X]  = hs->analog_lx;
    data->button[CELL_PAD_BTN_OFFSET_ANALOG_LEFT_Y]  = hs->analog_ly;''',
     "devpad: hook")
# ib stats: where spu_indirect_branch's time goes. inFAMOUS 1's one-SPU group thread spends ~52% of
# its samples in dispatch (spu_lookup / spu_indirect_branch / spu_drain_call / depth guard) and ~29%
# in lifted game code (console profile, 2026-11-01), with the inline cache on. Per SPU thread
# (thread-local, no shared cache line): calls, cache hits, misses by cause (empty / other pc / ib_gen
# changed / reg_gen / image-ovl-task / stale slot), the slow path by reason. Every 2^21 calls on a
# thread one "[ibstat]" line. PS3_SPU_IBSTAT=0 turns the counting off.
CHN = "runtime/spu/spu_channels.c"
edit(CHN,
     '''void spu_indirect_branch(spu_context* ctx)
{
    const uint32_t pc = ctx->pc & SPU_LS_MASK;''',
     '''/* ib stats (tools/patch_ibstat.py) */
enum { IBS_CALL, IBS_HIT, IBS_M_EMPTY, IBS_M_PC, IBS_M_GEN, IBS_M_REG, IBS_M_CTX, IBS_M_STALE, IBS_NOCACHE,
       IBS_S_STOP, IBS_S_PC, IBS_S_RESOLVER, IBS_S_JOB, IBS_S_POLICY, IBS_S_TASK, IBS_S_DIAG, IBS_S_NOFN, IBS_N };
static __thread unsigned long t_ibs[IBS_N];
static int s_ibs_on = -1;
static __attribute__((noinline, cold)) void ibs_report(const spu_context* ctx)
{
    static const char* const nm[IBS_N] = { "calls", "hit", "miss-empty", "miss-pc", "miss-ibgen", "miss-reggen",
        "miss-img/ovl/task", "miss-stale", "no-cache", "slow-stop/irq", "slow-pc", "slow-resolver", "slow-job",
        "slow-policy", "slow-task", "slow-diag", "slow-nofn" };
    char b[700]; int k = snprintf(b, sizeof b, "[ibstat] spu %X img %d ovl %d:", ctx->spu_id, ctx->image_id, ctx->resident_ovl);
    for (int i = 0; i < IBS_N && k < (int)sizeof b - 40; i++)
        if (t_ibs[i]) k += snprintf(b + k, sizeof b - (size_t)k, " %s %lu", nm[i], t_ibs[i]);
    fprintf(stderr, "%s\\n", b);
    memset(t_ibs, 0, sizeof t_ibs);
}
#define IBS(x) do { if (__builtin_expect(s_ibs_on, 1)) t_ibs[x]++; } while (0)

void spu_indirect_branch(spu_context* ctx)
{
    const uint32_t pc = ctx->pc & SPU_LS_MASK;
    if (__builtin_expect(s_ibs_on < 0, 0)) { const char* e = getenv("PS3_SPU_IBSTAT"); s_ibs_on = !(e && *e == '0'); }
    if (s_ibs_on && ++t_ibs[IBS_CALL] >= (1ul << 21)) ibs_report(ctx);''',
     "ibstat: counters")
edit(CHN,
     '''        (!ctx->policy_mode && pc == SPU_JOB_RETURN_LS) || spu_ib_diag_enabled())
        goto slow;
    {''',
     '''        (!ctx->policy_mode && pc == SPU_JOB_RETURN_LS) || spu_ib_diag_enabled()) {
        if (s_ibs_on) {
            if (__atomic_load_n(&ctx->stop_request, __ATOMIC_RELAXED) || ctx->irq_saved) IBS(IBS_S_STOP);
            else if (ctx->image_id == SPU_RESOLVER_ONLY_IMAGE_ID) IBS(IBS_S_RESOLVER);
            else if (ctx->resident_ovl >= 200 && spu_job_slow_routing()) IBS(IBS_S_JOB);
            else if (ctx->policy_mode) IBS(IBS_S_POLICY);
            else if (spu_ib_diag_enabled()) IBS(IBS_S_DIAG);
            else IBS(IBS_S_PC);
        }
        goto slow;
    }
    {''',
     "ibstat: slow reasons")
edit(CHN,
     '''            if (ti && !rt && ctx->host_depth && !ctx->policy_mode)
                goto slow;                            /* may unwind to the driver */''',
     '''            if (ti && !rt && ctx->host_depth && !ctx->policy_mode) {
                IBS(IBS_S_TASK);
                goto slow;                            /* may unwind to the driver */
            }''',
     "ibstat: task")
edit(CHN,
     '''            ce = &ctx->ib_cache[(pc >> 2) & (SPU_IB_CACHE_SIZE - 1)];
            if (ce->fn && ce->pc == pc && ce->gen == ctx->ib_gen && ce->reg_gen == reg_gen &&
                ce->img == ctx->image_id && ce->ovl == ctx->resident_ovl && ce->task == ctx->resident_task) {
                const int cs = ce->slot;
                if (cs < 0 || !spu_slot_word_stale(ctx, (unsigned)cs, pc)) {
                    if (cs >= 0 && ctx->resident_code[cs].reloc) ctx->code_base = ctx->resident_code[cs].lsa;
                    fn = ce->fn;
                    goto have_fn;
                }
            }
        }''',
     '''            ce = &ctx->ib_cache[(pc >> 2) & (SPU_IB_CACHE_SIZE - 1)];
            if (ce->fn && ce->pc == pc && ce->gen == ctx->ib_gen && ce->reg_gen == reg_gen &&
                ce->img == ctx->image_id && ce->ovl == ctx->resident_ovl && ce->task == ctx->resident_task) {
                const int cs = ce->slot;
                if (cs < 0 || !spu_slot_word_stale(ctx, (unsigned)cs, pc)) {
                    if (cs >= 0 && ctx->resident_code[cs].reloc) ctx->code_base = ctx->resident_code[cs].lsa;
                    fn = ce->fn;
                    IBS(IBS_HIT);
                    goto have_fn;
                }
                IBS(IBS_M_STALE);
            } else if (s_ibs_on) {
                IBS(!ce->fn ? IBS_M_EMPTY : ce->pc != pc ? IBS_M_PC : ce->gen != ctx->ib_gen ? IBS_M_GEN
                    : ce->reg_gen != reg_gen ? IBS_M_REG : IBS_M_CTX);
            }
        } else IBS(IBS_NOCACHE);''',
     "ibstat: cache")
edit(CHN,
     '''        if (!fn) goto slow;
        /* A stale slot that covered pc makes the answer depend on LS words''',
     '''        if (!fn) { IBS(IBS_S_NOFN); goto slow; }
        /* A stale slot that covered pc makes the answer depend on LS words''',
     "ibstat: nofn")
# ib cache 4096: the indirect-branch inline cache had 256 direct-mapped entries (one per 1 KiB of LS).
# inFAMOUS 1's one-SPU group thread (spu 2005, group 0x1001) makes ~3x the indirect branches of the
# other SPUs and 8.5% of them missed because another branch held the slot ("miss-pc", [ibstat],
# console 2026-11-01). 4096 entries = one per 16 KiB of LS. The array is the last member of
# spu_context, so nothing else moves; +144 KiB per context (some contexts live on a host stack).
# ib stats also keep the 8 most frequent LS addresses that had no lifted function (they run on the
# interpreter: spu_step / spu_smc_microstep were ~14% of that thread) and print them with each line.
CTXH = "runtime/spu/spu_context.h"
edit(CTXH,
     '''#define SPU_IB_CACHE_SIZE 256   /* spu_indirect_branch inline cache entries (power of two) */''',
     '''#define SPU_IB_CACHE_SIZE 4096  /* spu_indirect_branch inline cache entries (power of two; was 256) */''',
     "ib cache 4096: size")
edit(CHN,
     '''static __thread unsigned long t_ibs[IBS_N];''',
     '''static __thread unsigned long t_ibs[IBS_N];
static __thread struct { uint32_t pc; uint32_t n; } t_ibs_nofn[8];   /* the hottest no-lift addresses */
static void ibs_nofn(uint32_t pc)
{
    int lo = 0;
    for (int i = 0; i < 8; i++) {
        if (t_ibs_nofn[i].pc == pc && t_ibs_nofn[i].n) { t_ibs_nofn[i].n++; return; }
        if (t_ibs_nofn[i].n < t_ibs_nofn[lo].n) lo = i;
    }
    t_ibs_nofn[lo].pc = pc; t_ibs_nofn[lo].n = 1;   /* replaces the least frequent (a rough top 8) */
}''',
     "ib cache 4096: nofn table")
edit(CHN,
     '''    for (int i = 0; i < IBS_N && k < (int)sizeof b - 40; i++)
        if (t_ibs[i]) k += snprintf(b + k, sizeof b - (size_t)k, " %s %lu", nm[i], t_ibs[i]);''',
     '''    for (int i = 0; i < IBS_N && k < (int)sizeof b - 40; i++)
        if (t_ibs[i]) k += snprintf(b + k, sizeof b - (size_t)k, " %s %lu", nm[i], t_ibs[i]);
    if (t_ibs[IBS_S_NOFN]) {
        k += snprintf(b + k, sizeof b - (size_t)k, " | nofn pcs:");
        for (int i = 0; i < 8 && k < (int)sizeof b - 24; i++)
            if (t_ibs_nofn[i].n) k += snprintf(b + k, sizeof b - (size_t)k, " %05X*%u", t_ibs_nofn[i].pc, t_ibs_nofn[i].n);
    }
    memset(t_ibs_nofn, 0, sizeof t_ibs_nofn);''',
     "ib cache 4096: report nofn")
edit(CHN,
     '''        if (!fn) { IBS(IBS_S_NOFN); goto slow; }''',
     '''        if (!fn) { IBS(IBS_S_NOFN); if (s_ibs_on) ibs_nofn(pc); goto slow; }''',
     "ib cache 4096: count nofn")
# lazy ovl: a job module whose load was never seen still runs lifted.
# Overlay residency is noted when a DMA GET of >= 512 bytes lands a registered module's first 16
# bytes (spu_overlay_note_get). On inFAMOUS 1's one-SPU group thread (spu 0x2005, group 0x1001) that
# never happens: its jobs (e.g. jobmod_44377568bd76 / 542edebc6499 at LS 0x4000, both lifted and
# registered by signature) stayed "ovl 0", so every branch into them missed and ran on the
# interpreter (spu_step + spu_smc_microstep ~14% of that thread; [ibstat] nofn pcs 0x043A0...).
# Now: when an indirect branch at/above LS 0x4000 finds no lifted function, the 16 bytes at LS 0x4000
# are matched against the registered signatures; a match makes that module resident for this
# context. The adoption is remembered per host thread with its signature, and every later indirect
# branch on that thread re-checks those 16 bytes first: when another job has replaced the module
# the adoption is dropped before any lookup, so a new job never runs the old job's lifted code.
# PS3_SPU_LAZY_OVL=1 turns it on (off by default since 2026-11-02: it never adopted a module on the
# BC-250 crater runs; the 0x4xxx no-lift addresses there do not carry a registered signature).
edit(CHN,
     '''/* ib stats (tools/patch_ibstat.py) */''',
     '''/* lazy ovl (tools/patch_lazy_ovl.py) */
#define LAZY_OVL_LSA 0x4000u
static int s_lazy_ovl = -1;
static __thread int t_lazy_ovl;                 /* image adopted on this thread, 0 = none */
static __thread uint8_t t_lazy_sig[16];
static __thread unsigned long t_lazy_n;
int spu_overlay_match_sig(const uint8_t hdr[16]);
static __attribute__((noinline)) spu_fn spu_lazy_ovl_adopt(spu_context* ctx, uint32_t pc)
{
    if (s_lazy_ovl < 0) { const char* e = getenv("PS3_SPU_LAZY_OVL"); s_lazy_ovl = e && *e == '1'; }   /* off by default: never adopted in a measured run */
    if (!s_lazy_ovl || pc < LAZY_OVL_LSA || !ctx->ls) return NULL;
    const int ov = spu_overlay_match_sig(ctx->ls + LAZY_OVL_LSA);
    if (!ov || ov == ctx->resident_ovl) return NULL;
    spu_fn fn = spu_lookup(pc, ov);
    if (!fn) return NULL;
    ctx->resident_ovl = ov;
    ctx->ib_gen++;
    t_lazy_ovl = ov;
    memcpy(t_lazy_sig, ctx->ls + LAZY_OVL_LSA, 16);
    if (t_lazy_n++ < 8 || (t_lazy_n & 0xFFFF) == 0)
        fprintf(stderr, "[spu-ovl] spu %X: job image %d at LS 0x%05X adopted by signature (pc 0x%05X, #%lu)\\n",
                ctx->spu_id, ov, LAZY_OVL_LSA, pc, t_lazy_n);
    return fn;
}

/* ib stats (tools/patch_ibstat.py) */''',
     "lazy ovl: adopt")
edit(CHN,
     '''    if (s_ibs_on && ++t_ibs[IBS_CALL] >= (1ul << 21)) ibs_report(ctx);''',
     '''    if (s_ibs_on && ++t_ibs[IBS_CALL] >= (1ul << 21)) ibs_report(ctx);
    /* lazy ovl: an adopted job module stays resident only while its signature is still at LS 0x4000 */
    if (__builtin_expect(t_lazy_ovl != 0, 0) &&
        (ctx->resident_ovl != t_lazy_ovl || memcmp(ctx->ls + LAZY_OVL_LSA, t_lazy_sig, 16))) {
        if (ctx->resident_ovl == t_lazy_ovl) { ctx->resident_ovl = 0; ctx->ib_gen++; }
        t_lazy_ovl = 0;
    }''',
     "lazy ovl: revalidate")
edit(CHN,
     '''        if (!fn) { IBS(IBS_S_NOFN); if (s_ibs_on) ibs_nofn(pc); goto slow; }''',
     '''        if (!fn && (fn = spu_lazy_ovl_adopt(ctx, pc))) stale_seen = 1;   /* not cached: ovl changed */
        if (!fn) { IBS(IBS_S_NOFN); if (s_ibs_on) ibs_nofn(pc); goto slow; }''',
     "lazy ovl: on miss")
# vk vpc range: only the vertex-constant rows the bound program reads reach the GPU on Vulkan.
# The draw engine already computes them per vertex program (vpc_lo/vpc_n, rsx_vp_analyze_constants;
# relative addressing keeps the whole block) and calls bind_vs_constants_range when a backend has it
# (Metal did; Vulkan did not). Without it every draw copied the full 514-row block (8.2 KB) four
# times: engine copy, CPU shadow, mapped UBO, per-draw ring. inFAMOUS 1's crater (BC-250, 2026-11-01):
# 13,500 draws per frame, "vs-const 111 MB" staged per frame, RSX thread 98% of a core at 11.7 fps.
# Now the rows [first, first + count) and the viewport tail go into the shadow and the UBO, and the
# per-draw ring copy takes only those (the rest of the ring block is never read by that program).
# A full bind (bind_vs_constants: helper draws, relative-addressing programs) copies everything as
# before. PS3RECOMP_ENG_VPC_FULL=1 turns ranges off (draw engine A/B switch).
VKB = "libs/video/rsx_vulkan_backend.c"
edit(VKB,
     '''    u32          vs_bytes, ps_bytes;
    u32          tex[RSX_BE_MAX_TEXTURES];''',
     '''    u32          vs_bytes, ps_bytes;
    u32          vs_ranged, vs_lo, vs_n, vs_tail;      /* vk vpc range: rows the program reads */
    u32          tex[RSX_BE_MAX_TEXTURES];''',
     "vk vpc range: state")
edit(VKB,
     '''    vk_ubo_put(0, data, bytes);
    s_e2.vs_bytes = bytes;
}''',
     '''    vk_ubo_put(0, data, bytes);
    s_e2.vs_bytes = bytes;
    s_e2.vs_ranged = 0;
}
/* vk vpc range (tools/patch_vk_vpc_range.py): rows [first, first + count) and the tail at row 512. */
static void vk_eng_bind_vs_constants_range(void* user, const void* rows, u32 first, u32 count,
                                           const void* tail, u32 tail_bytes, u32 total_bytes)
{
    const u32 tail_off = RSX_MAX_VERTEX_CONSTANTS * 16u;
    if (!s_g.on || !rows || first > RSX_MAX_VERTEX_CONSTANTS || count > RSX_MAX_VERTEX_CONSTANTS - first ||
        total_bytes > (u32)s_g.ps_off || tail_off + tail_bytes > total_bytes) {
        /* not representable: the whole block, as before */
        static u8 blk[VK_VPCONST_BYTES];
        if (!rows || total_bytes > sizeof blk || tail_off + tail_bytes > total_bytes) { vk_eng_bind_vs_constants(user, NULL, 0); return; }
        memcpy(blk, rows, tail_off);
        memcpy(blk + tail_off, tail, tail_bytes);
        vk_eng_bind_vs_constants(user, blk, total_bytes);
        return;
    }
    (void)user;
    if (count) vk_ubo_put((size_t)first * 16u, (const u8*)rows + first * 16u, count * 16u);
    if (tail_bytes) vk_ubo_put(tail_off, tail, tail_bytes);
    s_e2.vs_bytes = total_bytes;
    s_e2.vs_ranged = 1; s_e2.vs_lo = first; s_e2.vs_n = count; s_e2.vs_tail = tail_bytes;
}''',
     "vk vpc range: bind")
edit(VKB,
     '''    memcpy(vk_ring_alloc(vs_bytes, s_ubo_align, &vs_off), s_ubo_cpu, vs_bytes);''',
     '''    {   u8* const vd = (u8*)vk_ring_alloc(vs_bytes, s_ubo_align, &vs_off);
        if (s_e2.vs_ranged && s_e2.vs_bytes == vs_bytes) {   /* vk vpc range: only what the program reads */
            const u32 tail_off = RSX_MAX_VERTEX_CONSTANTS * 16u;
            if (s_e2.vs_n) memcpy(vd + s_e2.vs_lo * 16u, s_ubo_cpu + s_e2.vs_lo * 16u, s_e2.vs_n * 16u);
            if (s_e2.vs_tail) memcpy(vd + tail_off, s_ubo_cpu + tail_off, s_e2.vs_tail);
        } else
            memcpy(vd, s_ubo_cpu, vs_bytes);
    }''',
     "vk vpc range: ring copy")
edit(VKB,
     '''    .bind_vs_constants    = vk_eng_bind_vs_constants,''',
     '''    .bind_vs_constants    = vk_eng_bind_vs_constants,
    .bind_vs_constants_range = vk_eng_bind_vs_constants_range,''',
     "vk vpc range: hook")
# spu xv ftz: the AVX2 exact-float fast path (spu__xv_fa/fm/fma) now takes two more cases itself
# instead of the per-lane scalar fix-up (spu__xv_*_fix -> spu__fa/fm/fma_any), bit-identical to it:
#  - a denormal operand (biased exponent 0) is the SPU's zero (spu__sf_split): flushed to +0 first;
#  - a result below the normal range (|r| < 2^-126, not zero) is the SPU's +0 (truncation toward
#    zero; the fma boundary case -- a rounded double exactly at 2^-126 -- keeps its exact path).
# Counted on inFAMOUS 1's crater (BC-250, 2026-11-01): ~2.3M fix-up calls per second over the SPU
# threads; of the slow lanes 78% were plain operands with an underflowing result, 10% denormal
# operands. Extended-range lanes (exponent 255 in or out) still take the fix-up.
# Checked against spu_fa/fs/fm/fma/fms/fnms_ref on random and edge operands (tools/spu_xv_test.c).
H = "runtime/spu/spu_helpers.h"
edit(H,
     '''SPU__XV_INLINE __m256d spu__xv_wide(__m128i x) { return _mm256_cvtps_pd(_mm_castsi128_ps(x)); }''',
     '''SPU__XV_INLINE __m256d spu__xv_wide(__m128i x) { return _mm256_cvtps_pd(_mm_castsi128_ps(x)); }
/* spu xv ftz: a denormal operand is the SPU's zero (spu__sf_split): +0. */
SPU__XV_INLINE __m128i spu__xv_ftz(__m128i x) {
    return _mm_andnot_si128(_mm_cmpeq_epi32(spu__xv_bexp(x), _mm_setzero_si128()), x);
}''',
     "spu xv ftz: ftz")
edit(H,
     '''    const __m256i lo32 = _mm256_setr_epi32(0, 2, 4, 6, 0, 2, 4, 6);
    *ok = _mm256_castsi256_si128(_mm256_permutevar8x32_epi32(_mm256_or_si256(good, az), lo32));
    *zm = _mm256_castsi256_si128(_mm256_permutevar8x32_epi32(az, lo32));
    const __m256d t = _mm256_castsi256_pd(_mm256_and_si256(u, _mm256_set1_epi64x(~0x1FFFFFFFll)));
    return _mm_castps_si128(_mm256_cvtpd_ps(t));''',
     '''    /* spu xv ftz: below the normal range (and not zero) truncates to the SPU's +0 */
    const __m256i under = _mm256_andnot_si256(az, _mm256_cmpgt_epi64(_mm256_set1_epi64x(-126), e));
    const __m256i zero = _mm256_or_si256(az, under);
    const __m256i lo32 = _mm256_setr_epi32(0, 2, 4, 6, 0, 2, 4, 6);
    *ok = _mm256_castsi256_si128(_mm256_permutevar8x32_epi32(_mm256_or_si256(good, zero), lo32));
    *zm = _mm256_castsi256_si128(_mm256_permutevar8x32_epi32(zero, lo32));
    const __m256d t = _mm256_castsi256_pd(_mm256_andnot_si256(under, _mm256_and_si256(u, _mm256_set1_epi64x(~0x1FFFFFFFll))));
    return _mm_castps_si128(_mm256_cvtpd_ps(t));''',
     "spu xv ftz: underflow")
edit(H,
     '''    const __m128i xa = spu__xv_ld(a), yb = spu__xv_ld(b);
    const __m128i x = xa, y = _mm_xor_si128(yb, _mm_set1_epi32((int)negb));''',
     '''    const __m128i xa = spu__xv_ld(a), yb = spu__xv_ld(b);
    const __m128i x = spu__xv_ftz(xa), y = _mm_xor_si128(spu__xv_ftz(yb), _mm_set1_epi32((int)negb));''',
     "spu xv ftz: fa")
edit(H,
     '''SPU__FX u128 spu__xv_fm_x(u128 a, u128 b) {
    const __m128i x = spu__xv_ld(a), y = spu__xv_ld(b);''',
     '''SPU__FX u128 spu__xv_fm_x(u128 a, u128 b) {
    const __m128i x = spu__xv_ftz(spu__xv_ld(a)), y = spu__xv_ftz(spu__xv_ld(b));''',
     "spu xv ftz: fm")
edit(H,
     '''    const __m128i xa = spu__xv_ld(a), y = spu__xv_ld(b), zc = spu__xv_ld(c);
    const __m128i x = _mm_xor_si128(xa, _mm_set1_epi32((int)negp)), z = _mm_xor_si128(zc, _mm_set1_epi32((int)negc));
    const __m256d p = _mm256_mul_pd(spu__xv_wide(x), spu__xv_wide(y)), zd = spu__xv_wide(z);''',
     '''    const __m128i xa = spu__xv_ld(a), y = spu__xv_ftz(spu__xv_ld(b)), zc = spu__xv_ld(c);
    const __m128i x = _mm_xor_si128(spu__xv_ftz(xa), _mm_set1_epi32((int)negp)),
                  z = _mm_xor_si128(spu__xv_ftz(zc), _mm_set1_epi32((int)negc));
    const __m256d p = _mm256_mul_pd(spu__xv_wide(x), spu__xv_wide(y)), zd = spu__xv_wide(z);''',
     "spu xv ftz: fma")
# vk dset reuse: the engine's per-draw descriptor set is reused while nothing in it changes.
# Every draw allocated a descriptor set from the frame's pool and wrote 34 descriptors (two uniform
# buffers, 16 images, 16 samplers) although consecutive draws mostly bind the same textures: only
# the two uniform-buffer offsets into the ring differ. The two uniform buffers are now
# UNIFORM_BUFFER_DYNAMIC (offset 0 in the descriptor, the ring offset given at bind time), so a draw
# whose buffer, ranges, image views and samplers equal the previous draw's binds that draw's set
# again with its own offsets: no allocation, no vkUpdateDescriptorSets. The cached set is dropped
# whenever a descriptor pool is reset or swapped. inFAMOUS 1's crater: 13,500 draws per frame on an
# RSX thread at 98% of a core (BC-250, 2026-11-01). PS3RECOMP_VK_DSET_REUSE=0 turns reuse off.
VKB = "libs/video/rsx_vulkan_backend.c"
edit(VKB,
     '''        { RSX_SPIRV_VPCONST_BINDING, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1, both, NULL },
        { RSX_SPIRV_PSCONST_BINDING, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1, both, NULL },''',
     '''        { RSX_SPIRV_VPCONST_BINDING, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, 1, both, NULL },   /* vk dset reuse */
        { RSX_SPIRV_PSCONST_BINDING, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, 1, both, NULL },''',
     "vk dset reuse: layout")
edit(VKB,
     '''    VkDescriptorPoolSize ps[3] = {
        { VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 2 },''',
     '''    VkDescriptorPoolSize ps[3] = {
        { VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, 2 },''',
     "vk dset reuse: guest pool")
edit(VKB,
     '''            { VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 2u * VK_DPOOL_SETS },''',
     '''            { VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, 2u * VK_DPOOL_SETS },''',
     "vk dset reuse: batch pool")
# the old guest-program draw: offsets 0 / ps_off move to the bind
edit(VKB,
     '''    VkDescriptorBufferInfo bi[2] = {
        { s_g.ubo.buf, 0, VK_VPCONST_BYTES },
        { s_g.ubo.buf, s_g.ps_off, fp_len },
    };''',
     '''    VkDescriptorBufferInfo bi[2] = {   /* vk dset reuse: dynamic, offsets at the bind */
        { s_g.ubo.buf, 0, VK_VPCONST_BYTES },
        { s_g.ubo.buf, 0, fp_len },
    };''',
     "vk dset reuse: guest bi")
edit(VKB,
     '''          .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, .pBufferInfo = &bi[0] },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_g.set,
          .dstBinding = RSX_SPIRV_PSCONST_BINDING, .descriptorCount = 1,
          .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, .pBufferInfo = &bi[1] },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_g.set,
          .dstBinding = RSX_SPIRV_TEXTURE_BINDING, .descriptorCount = RSX_MAX_TEXTURES,
          .descriptorType = VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, .pImageInfo = ii },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_g.set,
          .dstBinding = RSX_SPIRV_SAMPLER_BINDING, .descriptorCount = RSX_MAX_TEXTURES,
          .descriptorType = VK_DESCRIPTOR_TYPE_SAMPLER, .pImageInfo = si },
    };
    pvkUpdateDescriptorSets(s_vk.device, 4, w, 0, NULL);''',
     '''          .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, .pBufferInfo = &bi[0] },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_g.set,
          .dstBinding = RSX_SPIRV_PSCONST_BINDING, .descriptorCount = 1,
          .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, .pBufferInfo = &bi[1] },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_g.set,
          .dstBinding = RSX_SPIRV_TEXTURE_BINDING, .descriptorCount = RSX_MAX_TEXTURES,
          .descriptorType = VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, .pImageInfo = ii },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_g.set,
          .dstBinding = RSX_SPIRV_SAMPLER_BINDING, .descriptorCount = RSX_MAX_TEXTURES,
          .descriptorType = VK_DESCRIPTOR_TYPE_SAMPLER, .pImageInfo = si },
    };
    pvkUpdateDescriptorSets(s_vk.device, 4, w, 0, NULL);''',
     "vk dset reuse: guest writes")
edit(VKB,
     '''    pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_g.pipe_layout,
                             0, 1, &s_g.set, 0, NULL);''',
     '''    {   const uint32_t dyn[2] = { 0u, (uint32_t)s_g.ps_off };   /* vk dset reuse */
        pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_g.pipe_layout,
                                 0, 1, &s_g.set, 2, dyn); }''',
     "vk dset reuse: guest bind")
edit(VKB,
     '''static VkDescriptorSet  s_wd_set;''',
     '''static unsigned s_dpool_epoch;                  /* vk dset reuse: bumped when a descriptor pool is reset/swapped */
static VkDescriptorSet  s_wd_set;''',
     "vk dset reuse: epoch decl")
# the engine's writes: offsets become the dynamic ones; reuse when unchanged
edit(VKB,
     '''static void vk_eng_write_descriptors(void)
{''',
     '''/* vk dset reuse (tools/patch_vk_dset_reuse.py) */
static uint32_t s_dyn[2];                       /* dynamic offsets of the set being bound */
static int vk_dset_reuse_on(void)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3RECOMP_VK_DSET_REUSE"); on = !(e && e[0] == '0'); }
    return on;
}
static struct {
    VkDescriptorSet set; VkDescriptorPool pool; unsigned epoch;
    VkBuffer buf; VkDeviceSize r0, r1;
    VkImageView view[RSX_MAX_TEXTURES]; VkSampler smp[RSX_MAX_TEXTURES];
} s_dlast;
static unsigned long s_dreuse_n, s_dwrite_n;
static int vk_eng_write_descriptors_ex(int may_reuse);
static void vk_eng_write_descriptors(void) { (void)vk_eng_write_descriptors_ex(0); }
static int vk_eng_write_descriptors_ex(int may_reuse)
{''',
     "vk dset reuse: state")
edit(VKB,
     '''    VkDescriptorBufferInfo bi[2] = {
        { s_wd_buf ? s_wd_buf : s_g.ubo.buf, s_wd_buf ? s_wd_vs : 0, s_e2.vs_bytes ? s_e2.vs_bytes : 16u },
        { s_wd_buf ? s_wd_buf : s_g.ubo.buf, s_wd_buf ? s_wd_ps : s_g.ps_off, s_e2.ps_bytes ? s_e2.ps_bytes : 16u },
    };''',
     '''    VkDescriptorBufferInfo bi[2] = {   /* vk dset reuse: offset 0, the real one is dynamic */
        { s_wd_buf ? s_wd_buf : s_g.ubo.buf, 0, s_e2.vs_bytes ? s_e2.vs_bytes : 16u },
        { s_wd_buf ? s_wd_buf : s_g.ubo.buf, 0, s_e2.ps_bytes ? s_e2.ps_bytes : 16u },
    };
    s_dyn[0] = (uint32_t)(s_wd_buf ? s_wd_vs : 0);
    s_dyn[1] = (uint32_t)(s_wd_buf ? s_wd_ps : s_g.ps_off);''',
     "vk dset reuse: offsets")
edit(VKB,
     '''          .dstBinding = RSX_SPIRV_VPCONST_BINDING, .descriptorCount = 1,
          .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, .pBufferInfo = &bi[0] },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_g.set,
          .dstBinding = RSX_SPIRV_PSCONST_BINDING, .descriptorCount = 1,
          .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, .pBufferInfo = &bi[1] },''',
     '''          .dstBinding = RSX_SPIRV_VPCONST_BINDING, .descriptorCount = 1,   /* vk dset reuse: engine */
          .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, .pBufferInfo = &bi[0] },
        { .sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = s_g.set,
          .dstBinding = RSX_SPIRV_PSCONST_BINDING, .descriptorCount = 1,
          .descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, .pBufferInfo = &bi[1] },''',
     "vk dset reuse: engine ubo types")
edit(VKB,
     '''    if (s_wd_set) for (int i = 0; i < 4; i++) w[i].dstSet = s_wd_set;
    pvkUpdateDescriptorSets(s_vk.device, 4, w, 0, NULL);''',
     '''    if (may_reuse) {
        /* the previous set fits when it lives in this pool epoch and every descriptor is the same */
        int same = s_dlast.set && s_dlast.pool == s_dpool && s_dlast.epoch == s_dpool_epoch &&
                   s_dlast.buf == bi[0].buffer && s_dlast.r0 == bi[0].range && s_dlast.r1 == bi[1].range;
        for (u32 u = 0; same && u < RSX_MAX_TEXTURES; u++)
            same = s_dlast.view[u] == ii[u].imageView && s_dlast.smp[u] == si[u].sampler;
        if (same) { s_wd_set = s_dlast.set; s_dreuse_n++; return 1; }
        return 0;   /* the caller allocates a set and calls again with may_reuse = 2 */
    }
    if (s_wd_set) for (int i = 0; i < 4; i++) w[i].dstSet = s_wd_set;
    pvkUpdateDescriptorSets(s_vk.device, 4, w, 0, NULL);
    s_dwrite_n++;
    if (s_wd_set) {
        s_dlast.set = s_wd_set; s_dlast.pool = s_dpool; s_dlast.epoch = s_dpool_epoch;
        s_dlast.buf = bi[0].buffer; s_dlast.r0 = bi[0].range; s_dlast.r1 = bi[1].range;
        for (u32 u = 0; u < RSX_MAX_TEXTURES; u++) { s_dlast.view[u] = ii[u].imageView; s_dlast.smp[u] = si[u].sampler; }
    }''',
     "vk dset reuse: compare + remember")
edit(VKB,
     '''            s_sub_cube = s_sub_vol = s_sub_kind = 0; s_sub_t0 = now;
        } }
}''',
     '''            s_sub_cube = s_sub_vol = s_sub_kind = 0; s_sub_t0 = now;
            { static int lg = -1; if (lg < 0) lg = getenv("PS3RECOMP_VK_DSET_LOG") ? 1 : 0;
              if (lg) fprintf(stderr, "[vk] descriptor sets: %lu reused, %lu written\\n", s_dreuse_n, s_dwrite_n); }
            s_dreuse_n = s_dwrite_n = 0;
        } }
    return 0;
}''',
     "vk dset reuse: report")
edit(VKB,
     '''    memcpy(vk_ring_alloc(ps_bytes, s_ubo_align, &ps_off), s_ubo_cpu + s_g.ps_off, ps_bytes);
    VkDescriptorSetAllocateInfo dai''',
     '''    memcpy(vk_ring_alloc(ps_bytes, s_ubo_align, &ps_off), s_ubo_cpu + s_g.ps_off, ps_bytes);
    /* vk dset reuse: the previous draw's set when nothing in it differs (offsets are dynamic) */
    s_wd_buf = s_ring.buf; s_wd_vs = vs_off; s_wd_ps = ps_off;
    if (vk_dset_reuse_on() && vk_eng_write_descriptors_ex(1)) return 0;
    VkDescriptorSetAllocateInfo dai''',
     "vk dset reuse: try reuse")
edit(VKB,
     '''    if (s_dpool && s_dsets) { pvkResetDescriptorPool(s_vk.device, s_dpool, 0); s_dsets = 0; }''',
     '''    if (s_dpool && s_dsets) { pvkResetDescriptorPool(s_vk.device, s_dpool, 0); s_dsets = 0; }
    s_dpool_epoch++;   /* vk dset reuse */''',
     "vk dset reuse: epoch 1")
edit(VKB,
     '''    if (s_dpool) pvkResetDescriptorPool(s_vk.device, s_dpool, 0);
    s_dsets = 0;''',
     '''    if (s_dpool) pvkResetDescriptorPool(s_vk.device, s_dpool, 0);
    s_dsets = 0;
    s_dpool_epoch++;   /* vk dset reuse */''',
     "vk dset reuse: epoch 2")
edit(VKB,
     '''    pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_g.pipe_layout,
                             0, 1, &dset, 0, NULL);''',
     '''    pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_g.pipe_layout,
                             0, 1, &dset, 2, s_dyn);   /* vk dset reuse: dynamic offsets */''',
     "vk dset reuse: engine bind")
# A destroyed image view's (or sampler's) handle value can come back for a new object, and the set
# holds the OLD descriptor bytes: every destroy ends reuse (first try: device lost on the crater).
edit(VKB,
     '''        memset(im, 0, sizeof *im);
        return;
    }
    if (im->view) pvkDestroyImageView(s_vk.device, im->view, NULL);''',
     '''        memset(im, 0, sizeof *im);
        return;
    }
    s_dpool_epoch++;   /* vk dset reuse: handles may come back */
    if (im->view) pvkDestroyImageView(s_vk.device, im->view, NULL);''',
     "vk dset reuse: destroy image")
edit(VKB,
     '''        vk_image* im = &s_gimg[i];
        if (im->view) pvkDestroyImageView(s_vk.device, im->view, NULL);''',
     '''        vk_image* im = &s_gimg[i];
        s_dpool_epoch++;   /* vk dset reuse */
        if (im->view) pvkDestroyImageView(s_vk.device, im->view, NULL);''',
     "vk dset reuse: garbage 1")
edit(VKB,
     '''        vk_image* im = &S->gimg[i];
        if (im->view) pvkDestroyImageView(s_vk.device, im->view, NULL);''',
     '''        vk_image* im = &S->gimg[i];
        s_dpool_epoch++;   /* vk dset reuse */
        if (im->view) pvkDestroyImageView(s_vk.device, im->view, NULL);''',
     "vk dset reuse: garbage 2")
edit(VKB,
     '''    pvkDestroyImageView(s_vk.device, o->im.view, NULL);
    if (vk_eng_make_view_layers(o->im.img, o->fmt, 1, id, 6, &o->im.view))''',
     '''    s_dpool_epoch++;   /* vk dset reuse */
    pvkDestroyImageView(s_vk.device, o->im.view, NULL);
    if (vk_eng_make_view_layers(o->im.img, o->fmt, 1, id, 6, &o->im.view))''',
     "vk dset reuse: dummy cube")
edit(VKB,
     '''    for (u32 i = 0; i < s_esamp_count; i++) pvkDestroySampler(s_vk.device, s_esamp[i].s, NULL);''',
     '''    s_dpool_epoch++;   /* vk dset reuse */
    for (u32 i = 0; i < s_esamp_count; i++) pvkDestroySampler(s_vk.device, s_esamp[i].s, NULL);''',
     "vk dset reuse: samplers")
# tdump regs: PS3_TDUMP_REGS=1 -- in the guest thread dump, a thread blocked in one syscall for more
# than 5 s also shows r3..r31 and, for each of r14..r31 that points into guest memory, the first
# 32 bytes of its 128-byte line. For a lost wake-up the waited-on object (an event flag, a queue
# owner) is in a callee-saved register of the waiting thread; its line shows who forgot whom.
# inFAMOUS 1's boot stall: fios tid 15 in sys_event_queue_receive(_spuEvF) for good (2026-11-02).
SPT = "runtime/syscalls/sys_ppu_thread.c"
edit(SPT,
     '''            tdump_wait_of(o, (unsigned)(i + 1));
            fputc('\\n', o);''',
     '''            tdump_wait_of(o, (unsigned)(i + 1));
            fputc('\\n', o);
            {   /* tdump regs (tools/patch_tdump_regs.py) */
                static int regs = -1;
                if (regs < 0) { const char* e = getenv("PS3_TDUMP_REGS"); regs = e && *e == '1'; }
                const unsigned tid = (unsigned)(i + 1);
                const uint64_t t0 = tid < TDW_MAX ? g_sc_inflight_t0[tid] : 0, now = ps3_ft_now();
                if (regs && tid < TDW_MAX && g_sc_inflight[tid] && t0 && now > t0 && now - t0 > 5000000000ull) {
                    fprintf(o, "[tdump]   regs:");
                    for (int r = 3; r < 32; r++) fprintf(o, " r%d=%08X", r, (uint32_t)c->gpr[r]);
                    fputc('\\n', o);
                    for (int r = 14; r < 32; r++) {
                        const uint32_t v = (uint32_t)c->gpr[r];
                        if (v < 0x10000u || v >= 0xE0000000u) continue;
                        const uint32_t l = v & ~127u;
                        fprintf(o, "[tdump]   r%d line 0x%08X:", r, l);
                        for (int k = 0; k < 32; k += 4) fprintf(o, " %08X", td_rd32(l + (uint32_t)k));
                        fputc('\\n', o);
                    }
                }
            }''',
     "tdump regs")
# rsx method histogram: RSX_METHOD_HIST=1 prints, every 10 s, how many FIFO method words of each
# kind the RSX thread processed (top 12 by count, NV4097 methods with the subchannel stripped) --
# what the per-word decode cost (rsx_process_method's compare chain + the draw engine's dispatch,
# ~30% of inFAMOUS 1's RSX thread at 13,500 draws per frame) is spent on.
GCM = "libs/video/cellGcmSys.c"
edit(GCM,
     '''                } else if (subch == 0 || (subch == 1 && !s1_2d)) {
                    rsx_process_method(&s_state, m, dw);''',
     '''                } else if (subch == 0 || (subch == 1 && !s1_2d)) {
                    { static int mh = -1;   /* rsx method histogram (tools/patch_rsx_mhist.py) */
                      if (mh < 0) mh = getenv("RSX_METHOD_HIST") ? 1 : 0;
                      if (mh) { static unsigned long long cnt[0x800], t0, tot; struct timespec ts;
                          cnt[(m & 0x1FFCu) >> 2]++; tot++;
                          if ((tot & 0xFFFF) == 0) { clock_gettime(CLOCK_MONOTONIC, &ts);
                              const unsigned long long now = (unsigned long long)ts.tv_sec;
                              if (!t0) t0 = now;
                              if (now - t0 >= 10) { t0 = now;
                                  fprintf(stderr, "[mhist] %llu words:", tot);
                                  for (int k = 0; k < 12; k++) { unsigned best = 0;
                                      for (unsigned j = 1; j < 0x800; j++) if (cnt[j] > cnt[best]) best = j;
                                      if (!cnt[best]) break;
                                      fprintf(stderr, " %04X=%llu", best << 2, cnt[best]); cnt[best] = 0; }
                                  fputc('\\n', stderr); memset(cnt, 0, sizeof cnt); tot = 0; } } } }
                    rsx_process_method(&s_state, m, dw);''',
     "rsx method histogram")
# spu putllc diff: a committing PUTLLC writes back only the 8-byte words the SPU changed against its
# GETLLAR snapshot, not the whole 128-byte line.
# A plain PPU store (inline vm_write*_inl and VM_WRITE_COH alike) takes the lock-line lock only when
# it sees an SPU reservation on the line; a store whose check came before the SPU's GETLLAR, but whose
# write lands after PUTLLC's compare (the PPU thread preempted between the two), was overwritten by
# the full-line copy -- a lost update hardware cannot produce. inFAMOUS 1's load-screen stall
# (BC-250, ~1 boot in 4, 2026-11-02): the game's zlib manager waits on an event flag for a job the
# WWS job manager on spu 2005 never sees; that SPU polls the job-list header at 0x9EAF00 ~3,700 times
# a second and finds it empty, i.e. the PPU's write to the list was lost.
# Writing only changed words keeps every other word's concurrent store: the result is the PPU store
# ordered after the PUTLLC, which hardware allows. A store to a word the SPU itself changed is still
# overwritten; that is counted ("[putllc] word conflicts").
# Alone it did not stop the stall (1 of 3 boots); together with tools/resv_note_first.py (reserve
# before load) 24 of 24 boots had no stall (that fix alone: 1 in 10). DEFAULT ON; PS3_SPU_PUTLLC_DIFF=0 = old copy.
CHN = "runtime/spu/spu_channels.c"
edit(CHN,
     '''            gm_copy_to(mem, ls, MFC_ATOMIC_LINE);      /* commit local store */
            /* A committing PUTLLC is a line write like any other, so every''',
     '''            {   /* spu putllc diff (tools/patch_spu_putllc_diff.py): only the words this SPU changed */
                static int s_full = -1;
                if (s_full < 0) { const char* e = getenv("PS3_SPU_PUTLLC_DIFF"); s_full = e && *e == '0'; }   /* default on since 2026-11-02 (24/24 boots without the stall) */
                if (s_full || ((uintptr_t)mem & 7u)) gm_copy_to(mem, ls, MFC_ATOMIC_LINE);
                else {
                    static unsigned long s_conf;
                    for (unsigned w = 0; w < MFC_ATOMIC_LINE; w += 8) {
                        uint64_t nv, ov;
                        memcpy(&nv, (const uint8_t*)ls + w, 8);
                        memcpy(&ov, (const uint8_t*)ctx->resv_line + w, 8);
                        if (nv == ov) continue;
                        uint64_t* p = (uint64_t*)((uint8_t*)mem + w);
                        uint64_t exp = ov;
                        if (!__atomic_compare_exchange_n(p, &exp, nv, 0, __ATOMIC_SEQ_CST, __ATOMIC_RELAXED)) {
                            __atomic_store_n(p, nv, __ATOMIC_SEQ_CST);   /* same word written by both: ours */
                            const unsigned long c = __atomic_add_fetch(&s_conf, 1, __ATOMIC_RELAXED);
                            if ((c & (c - 1)) == 0)
                                fprintf(stderr, "[putllc] word conflicts: %lu (ea 0x%08X +%u)\\n", c, ea, w);
                        }
                    }
                }
            }
            /* A committing PUTLLC is a line write like any other, so every''',
     "spu putllc diff")
# rsx const fast: transform-constant words go straight to their handler in rsx_process_method.
# The method is matched by a ~60-test if-chain; the constant window (0x1EFC load + 0x1F00..0x1F7C) sat
# near its end. inFAMOUS 1's crater sends ~405k FIFO words per frame, most of them constant uploads
# (RSX_METHOD_HIST, 2026-11-02: 0x1EFC and each of 0x1F00..0x1F0C 2.4M per 10 s). No test before
# those handlers matches 0x1EFC..0x1F7C, so the jump changes nothing but the order.
CMD = "libs/video/rsx_commands.c"
edit(CMD,
     '''      if(_rt){ static int _m=0; if(PS3_LOG_FIRST(_m, _rt)) fprintf(stderr,"[rsxm] method=0x%04X data=0x%08X\\n", method, data); } }''',
     '''      if(_rt){ static int _m=0; if(PS3_LOG_FIRST(_m, _rt)) fprintf(stderr,"[rsxm] method=0x%04X data=0x%08X\\n", method, data); } }
    /* rsx const fast (tools/patch_rsx_const_fast.py): the constant window first */
    if (method >= NV4097_SET_TRANSFORM_CONSTANT_LOAD &&
        method <  NV4097_SET_TRANSFORM_CONSTANT + NV4097_SET_TRANSFORM_CONSTANT_DWORDS * 4) {
        if (method == NV4097_SET_TRANSFORM_CONSTANT_LOAD) goto rsxm_const_load;
        goto rsxm_const;
    }''',
     "rsx const fast: jump")
edit(CMD,
     '''    if (method == NV4097_SET_TRANSFORM_CONSTANT_LOAD) {
        { static int _n=0, _e=-1;''',
     '''rsxm_const_load:   /* rsx const fast */
    if (method == NV4097_SET_TRANSFORM_CONSTANT_LOAD) {
        { static int _n=0, _e=-1;''',
     "rsx const fast: load label")
edit(CMD,
     '''     * SET_TRANSFORM_CONSTANT_LOAD before each block. */
    if (method >= NV4097_SET_TRANSFORM_CONSTANT &&''',
     '''     * SET_TRANSFORM_CONSTANT_LOAD before each block. */
rsxm_const:   /* rsx const fast */
    if (method >= NV4097_SET_TRANSFORM_CONSTANT &&''',
     "rsx const fast: const label")
# ovl lift index: spu_overlay_note_get (every DMA GET) walks only the sources that can still match.
# After the quick reject (ovl_cannot_match), a GET into the job-module area (LS 0x4000+: every lifted
# job module is a fixed-address source there) walked all registered overlay sources (up to 128).
# When the GET's first word cannot start any signature and its EA is no address source -- the same
# hash bits the quick reject uses -- only fixed-address lifts can match, and those are now walked
# from their own index list in the original order, so the first hit is the same one.
# inFAMOUS 1 crater gameplay (BC-250 perf, 2026-11-02): spu_overlay_note_get was the hottest single
# symbol over all SPU threads (2.8% of all samples), mostly the loop over the source table.
CHN = "runtime/spu/spu_channels.c"
edit(CHN,
     '''static uint64_t s_ovl_lift_pages[4];        /* 256 x 1 KB pages of LS */''',
     '''static uint64_t s_ovl_lift_pages[4];        /* 256 x 1 KB pages of LS */
static unsigned char s_ovl_lift_idx[SPU_OVL_SRC_MAX];   /* ovl lift index: the fixed-address sources, in order */
static int s_ovl_lift_n;''',
     "ovl lift index: decl")
edit(CHN,
     '''        if (o->lift_lsa) {
            if (o->lift_lsa < lo) lo = o->lift_lsa;''',
     '''        if (o->lift_lsa) {
            s_ovl_lift_idx[s_ovl_lift_n++] = (unsigned char)i;   /* ovl lift index */
            if (o->lift_lsa < lo) lo = o->lift_lsa;''',
     "ovl lift index: fill")
edit(CHN,
     '''    memset(s_ovl_lift_pages, 0, sizeof s_ovl_lift_pages);
    uint32_t lo = 0xFFFFFFFFu, hi = 0;''',
     '''    memset(s_ovl_lift_pages, 0, sizeof s_ovl_lift_pages);
    s_ovl_lift_n = 0;   /* ovl lift index */
    uint32_t lo = 0xFFFFFFFFu, hi = 0;''',
     "ovl lift index: reset")
edit(CHN,
     '''    if (ovl_cannot_match(ea, ls, lsa, size)) return;
    for (int i = 0; i < s_ovl_src_count; i++) {
        const spu_ovl_src* o = &s_ovl_src[i];''',
     '''    if (ovl_cannot_match(ea, ls, lsa, size)) return;
    /* ovl lift index (tools/patch_ovl_lift_index.py): no signature or address source can match ->
     * walk only the fixed-address lifts (summary is current: ovl_cannot_match rebuilt it) */
    int lift_only = 0;
    {   const unsigned he = ovl_ea_hash(ea);
        int sig_may = 0;
        if (size >= 512) { uint32_t w; memcpy(&w, ls, 4); const unsigned hs = ovl_ea_hash(w);
                           sig_may = (s_ovl_sig_bits[hs >> 6] >> (hs & 63)) & 1; }
        lift_only = !sig_may && !((s_ovl_ea_bits[he >> 6] >> (he & 63)) & 1) &&
                    __atomic_load_n(&s_ovl_summary_n, __ATOMIC_ACQUIRE) == s_ovl_src_count;
    }
    const int n_walk = lift_only ? s_ovl_lift_n : s_ovl_src_count;
    for (int ii = 0; ii < n_walk; ii++) {
        const int i = lift_only ? s_ovl_lift_idx[ii] : ii;
        const spu_ovl_src* o = &s_ovl_src[i];''',
     "ovl lift index: walk")
# lifter resv first: lwarx/ldarx register the line reservation before the load (see
# tools/resv_note_first.py, which rewrote the already-generated inFAMOUS 1 sources the same way):
# a writer committing between a load and a later registration was never seen by the
# store-conditional -> lost wake-ups (inFAMOUS 1 load-screen stall, 2026-11-02).
LIFT = "tools/ppu_lifter.py"
edit(LIFT,
     '''            return (f"{{ uint64_t ea = {ea}; "
                    f"ctx->gpr[{rd}] = vm_read32(ea); "
                    f"ctx->reserve_addr = (uint32_t)ea; ctx->reserve_value = ctx->gpr[{rd}]; "
                    f"ppu_resv_line_note(ea); }}")''',
     '''            return (f"{{ uint64_t ea = {ea}; ppu_resv_line_note(ea); "   # lifter resv first: reserve, then load
                    f"ctx->gpr[{rd}] = vm_read32(ea); "
                    f"ctx->reserve_addr = (uint32_t)ea; ctx->reserve_value = ctx->gpr[{rd}]; }}")''',
     "lifter resv first: lwarx")
edit(LIFT,
     '''            return (f"{{ uint64_t ea = {ea}; "
                    f"ctx->gpr[{rd}] = vm_read64(ea); "
                    f"ctx->reserve_addr = (uint32_t)ea; ctx->reserve_value = ctx->gpr[{rd}]; "
                    f"ppu_resv_line_note(ea); }}")''',
     '''            return (f"{{ uint64_t ea = {ea}; ppu_resv_line_note(ea); "   # lifter resv first: reserve, then load
                    f"ctx->gpr[{rd}] = vm_read64(ea); "
                    f"ctx->reserve_addr = (uint32_t)ea; ctx->reserve_value = ctx->gpr[{rd}]; }}")''',
     "lifter resv first: ldarx")
# spu evt fail log: an SPU user event (sys_spu_thread_send_event, port < 64) that could not be
# delivered -- empty outbound mailbox (EINVAL), no queue bound to the port (ENOTCONN), queue full
# (EBUSY) -- is logged (first 32, then every 1024th). Two of those paths were silent: the SPU gets
# the error in its inbound mailbox and libsre's event-flag set ignores it, so the PPU waiter sleeps
# forever. FoB's load-screen stall (2026-11-02): the flag's ppuWaitMask was cleared by the SPU set,
# yet the waiting thread never got its event and the queue held nothing.
LV2 = "runtime/syscalls/lv2_register.c"
edit(LV2,
     '''    if (code < 64) spu_channel_write(&spu->ch_in_mbox, result);
    return 1;
}''',
     '''    if (code < 64 && result != CELL_OK) {   /* spu evt fail log (tools/patch_spu_evt_fail_log.py) */
        static unsigned long n_fail;
        const unsigned long k = __atomic_add_fetch(&n_fail, 1, __ATOMIC_RELAXED);
        if (k <= 32 || (k & 1023) == 0)
            fprintf(stderr, "[spu-evt] FAILED #%lu: spu %X grp 0x%X img %d port %u value 0x%08X -> 0x%08X (out_mbox %u)\\n",
                    k, spu->spu_id, spu->spu_group_id, spu->image_id, code & 63, value, result,
                    (unsigned)spu_channel_count(&spu->ch_out_mbox));
    }
    if (code < 64) spu_channel_write(&spu->ch_in_mbox, result);
    return 1;
}''',
     "spu evt fail log")
# caswatch max: PPU_CASWATCH_MAX=<n> lifts the 200-line cap of the PPU_CASWATCH log (0 = unlimited).
# FoB's lost task wake-up happens after a few hundred commits on the taskset line (2026-11-02).
PPL = "runtime/ppu/ppu_loader.cpp"
edit(PPL,
     '''          static int n; if (PS3_LOG_FIRST(n, 200))''',
     '''          static int n; static int cap = -2;   /* caswatch max (tools/patch_caswatch_max.py) */
          if (cap == -2) { const char* m = getenv("PPU_CASWATCH_MAX"); cap = m ? atoi(m) : 200; if (cap <= 0) cap = 0x7FFFFFFF; }
          if (PS3_LOG_FIRST(n, cap))''',
     "caswatch max")
# spu fz: SPU single-precision fa/fs/fm/fma/fms/fnms as one native instruction, bit exact, under MXCSR RZ|FTZ|DAZ
# if2 boat-deck profile (2026-11-02): lifted SPU code is ~87% of the SPU threads' samples, and the
# hottest job module (jobmod_d0d15ec83992, 43% of them) is float code whose time is the AVX2 exact
# emulation (widen to double, truncate, range checks: ~25-35 instructions per op). The SPU rounds
# toward zero, flushes denormal operands and results to zero, and never returns -0. x86 does the
# same in hardware with MXCSR RC=toward zero, FTZ and DAZ (0xFFC0): a native addps/mulps/vfmadd*ps
# then gives the SPU's result for every operand except two cases, which take the exact path
# (with the default MXCSR restored around it):
#   - an operand with biased exponent 255 (SPU extended range; x86 Inf/NaN);
#   - a result of magnitude FLT_MAX (an RZ overflow; the SPU's extended range goes higher).
# A zero result is made +0. The instructions are inline asm so the compiler cannot constant-fold
# them in round-to-nearest. spu_run_with_halt (every lifted SPU run) sets the MXCSR on entry and
# restores the caller's on exit; the double-precision helpers (IEEE round to nearest) set the
# default MXCSR around themselves. SPU_FZ=0 = the previous exact AVX2 path (read once at startup).
# tools/test_spu_fz.c checks it bit for bit against the scalar exact forms (spu_*_ref).
SFH = "runtime/spu/spu_helpers.h"
edit(SFH,
     '''#else
SPU__XV_INLINE u128 spu_fa(u128 a, u128 b) { return spu__xv_fa_x(a, b, 0); }
SPU__XV_INLINE u128 spu_fs(u128 a, u128 b) { return spu__xv_fa_x(a, b, 0x80000000u); }
SPU__XV_INLINE u128 spu_fm(u128 a, u128 b) { return spu__xv_fm_x(a, b); }
SPU__XV_INLINE u128 spu_fma(u128 a, u128 b, u128 c)  { return spu__xv_fma_x(a, b, c, 0, 0); }
SPU__XV_INLINE u128 spu_fms(u128 a, u128 b, u128 c)  { return spu__xv_fma_x(a, b, c, 0, 0x80000000u); }
SPU__XV_INLINE u128 spu_fnms(u128 a, u128 b, u128 c) { return spu__xv_fma_x(a, b, c, 0x80000000u, 0); }
#endif''',
     '''#else
/* spu fz (tools/patch_spu_fz.py): native single precision under MXCSR RZ|FTZ|DAZ, bit exact. */
#define SPU_FZ_MXCSR 0xFFC0u
SPU_GATE int g_spu_fz = 0;   /* 1: lifted SPU runs set SPU_FZ_MXCSR (spu_run_with_halt); SPU_FZ=0 turns it off */
SPU__XV_INLINE __m128 spu__fz_m(u128 v) { __m128 r; memcpy(&r, &v, 16); return r; }
SPU__XV_INLINE u128 spu__fz_u(__m128 v) { u128 r; memcpy(&r, &v, 16); return r; }
/* any lane the hardware may get wrong: an operand with exponent 255, or a result of magnitude FLT_MAX */
SPU__XV_INLINE int spu__fz_bad(__m128 x, __m128 y, __m128 z, __m128 r) {
    const __m128i e = _mm_set1_epi32(0x7F800000);
    const __m128i bx = _mm_cmpeq_epi32(_mm_and_si128(_mm_castps_si128(x), e), e);
    const __m128i by = _mm_cmpeq_epi32(_mm_and_si128(_mm_castps_si128(y), e), e);
    const __m128i bz = _mm_cmpeq_epi32(_mm_and_si128(_mm_castps_si128(z), e), e);
    const __m128i br = _mm_cmpeq_epi32(_mm_and_si128(_mm_castps_si128(r), _mm_set1_epi32(0x7FFFFFFF)),
                                       _mm_set1_epi32(0x7F7FFFFF));
    const __m128i bad = _mm_or_si128(_mm_or_si128(bx, by), _mm_or_si128(bz, br));
    return !_mm_testz_si128(bad, bad);
}
SPU__XV_INLINE u128 spu__fz_pos0(__m128 r) {   /* the SPU never returns -0 (r is never NaN here) */
    return spu__fz_u(_mm_and_ps(r, _mm_cmpneq_ps(r, _mm_setzero_ps())));
}
/* the exact path, with the default MXCSR around it (it computes in double, round to nearest) */
SPU__XV_SLOW u128 spu__fz_slow(int op, u128 a, u128 b, u128 c) {
    const unsigned m = _mm_getcsr();
    _mm_setcsr(0x1F80u);
    u128 r;
    switch (op) {
    case 0: r = spu__xv_fa_x(a, b, 0); break;
    case 1: r = spu__xv_fa_x(a, b, 0x80000000u); break;
    case 2: r = spu__xv_fm_x(a, b); break;
    case 3: r = spu__xv_fma_x(a, b, c, 0, 0); break;
    case 4: r = spu__xv_fma_x(a, b, c, 0, 0x80000000u); break;
    default: r = spu__xv_fma_x(a, b, c, 0x80000000u, 0); break;
    }
    _mm_setcsr(m);
    return r;
}
#define SPU__FZ2(name, insn, op, exact)                                                        \\
SPU__XV_INLINE u128 name(u128 a, u128 b) {                                                     \\
    if (__builtin_expect(g_spu_fz != 0, 1)) {                                                  \\
        const __m128 x = spu__fz_m(a), y = spu__fz_m(b); __m128 r;                              \\
        __asm__(insn " %2, %1, %0" : "=x"(r) : "x"(x), "x"(y));                                 \\
        if (__builtin_expect(spu__fz_bad(x, y, y, r), 0)) return spu__fz_slow(op, a, b, b);     \\
        return spu__fz_pos0(r);                                                                \\
    }                                                                                          \\
    return exact;                                                                              \\
}
#define SPU__FZ3(name, insn, op, exact)                                                        \\
SPU__XV_INLINE u128 name(u128 a, u128 b, u128 c) {                                             \\
    if (__builtin_expect(g_spu_fz != 0, 1)) {                                                  \\
        const __m128 x = spu__fz_m(a), y = spu__fz_m(b), z = spu__fz_m(c); __m128 r;            \\
        __asm__(insn " %3, %2, %0" : "=x"(r) : "0"(x), "x"(y), "x"(z));                         \\
        if (__builtin_expect(spu__fz_bad(x, y, z, r), 0)) return spu__fz_slow(op, a, b, c);     \\
        return spu__fz_pos0(r);                                                                \\
    }                                                                                          \\
    return exact;                                                                              \\
}
SPU__FZ2(spu_fa, "vaddps", 0, spu__xv_fa_x(a, b, 0))
SPU__FZ2(spu_fs, "vsubps", 1, spu__xv_fa_x(a, b, 0x80000000u))
SPU__FZ2(spu_fm, "vmulps", 2, spu__xv_fm_x(a, b))
SPU__FZ3(spu_fma,  "vfmadd213ps",  3, spu__xv_fma_x(a, b, c, 0, 0))            /* a*b + c */
SPU__FZ3(spu_fms,  "vfmsub213ps",  4, spu__xv_fma_x(a, b, c, 0, 0x80000000u))  /* a*b - c */
SPU__FZ3(spu_fnms, "vfnmadd213ps", 5, spu__xv_fma_x(a, b, c, 0x80000000u, 0))  /* c - a*b */
#undef SPU__FZ2
#undef SPU__FZ3
#endif''',
     "spu fz: native float under RZ mxcsr")
# The double-precision helpers round to nearest: default MXCSR around them while spu fz is on.
edit(SFH,
     '''/* ---- double precision: IEEE, round to nearest (see the header of this section) ---- */''',
     '''/* ---- double precision: IEEE, round to nearest (see the header of this section) ---- */
#if defined(SPU_FLOAT_AVX2) && defined(SPU_FZ_MXCSR)   /* spu fz rn: default MXCSR around double math */
static inline unsigned spu__fz_rn_begin(void) {
    if (!g_spu_fz) return 0;
    const unsigned m = _mm_getcsr(); _mm_setcsr(0x1F80u); return m;
}
static inline void spu__fz_rn_end(unsigned m) { if (m) _mm_setcsr(m); }
#else
static inline unsigned spu__fz_rn_begin(void) { return 0; }
static inline void spu__fz_rn_end(unsigned m) { (void)m; }
#endif''',
     "spu fz: rn helpers")
edit(SFH,
     '''#define SPU__D_V2(name, op) static inline u128 name(u128 a, u128 b) { u128 r; for (int i = 0; i < 2; i++) { \\
    const uint64_t x = spu__dw_get(a, i), y = spu__dw_get(b, i); \\
    spu__dw_put(&r, i, (spu__d_isnan(x) || spu__d_isnan(y)) ? 0x7FF8000000000000ull \\
                       : spu__d_out(spu__d_in(x) op spu__d_in(y))); } return r; }''',
     '''#define SPU__D_V2(name, op) static inline u128 name(u128 a, u128 b) { u128 r; const unsigned fzm = spu__fz_rn_begin(); \\
    for (int i = 0; i < 2; i++) { /* spu fz rn: dfa/dfs/dfm */ \\
    const uint64_t x = spu__dw_get(a, i), y = spu__dw_get(b, i); \\
    spu__dw_put(&r, i, (spu__d_isnan(x) || spu__d_isnan(y)) ? 0x7FF8000000000000ull \\
                       : spu__d_out(spu__d_in(x) op spu__d_in(y))); } spu__fz_rn_end(fzm); return r; }''',
     "spu fz: rn dfa")
edit(SFH,
     '''static inline u128 spu__dfmx(u128 a, u128 b, u128 c, int negate, int subtract) { u128 r;
    for (int i = 0; i < 2; i++) {''',
     '''static inline u128 spu__dfmx(u128 a, u128 b, u128 c, int negate, int subtract) { u128 r;
    const unsigned fzm = spu__fz_rn_begin();   /* spu fz rn: dfma family */
    for (int i = 0; i < 2; i++) {''',
     "spu fz: rn dfmx begin")
edit(SFH,
     '''        spu__dw_put(&r, i, (negate && !spu__d_isnan(u)) ? u ^ 0x8000000000000000ull : u);
    }
    return r; }''',
     '''        spu__dw_put(&r, i, (negate && !spu__d_isnan(u)) ? u ^ 0x8000000000000000ull : u);
    }
    spu__fz_rn_end(fzm);   /* spu fz rn: dfma family end */
    return r; }''',
     "spu fz: rn dfmx end")
edit(SFH,
     '''static inline u128 spu_frds(u128 a) { u128 r;
    for (int i = 0; i < 2; i++) {''',
     '''static inline u128 spu_frds(u128 a) { u128 r;
    const unsigned fzm = spu__fz_rn_begin();   /* spu fz rn: frds */
    for (int i = 0; i < 2; i++) {''',
     "spu fz: rn frds begin")
edit(SFH,
     '''        r._u32[2*i] = w; r._u32[2*i+1] = 0;
    }
    return r; }''',
     '''        r._u32[2*i] = w; r._u32[2*i+1] = 0;
    }
    spu__fz_rn_end(fzm);   /* spu fz rn: frds end */
    return r; }''',
     "spu fz: rn frds end")
# The MXCSR for every lifted SPU run; SPU_FZ read before any SPU thread starts.
SCH = "runtime/spu/spu_channels.c"
edit(SCH,
     '''/* Run a lifted SPU entry with a halt landing pad. Returns 1 if the job halted
 * (via spu_halt), 0 if it returned normally. */
int spu_run_with_halt(void (*entry)(spu_context*), spu_context* ctx)
{
    int halted = 0;''',
     '''#if defined(SPU_FZ_MXCSR)   /* spu fz: SPU_FZ=0 keeps the exact AVX2 float path */
__attribute__((constructor)) static void spu_fz_init(void)
{
    const char* e = getenv("SPU_FZ");
    g_spu_fz = !(e && e[0] == '0');
    fprintf(stderr, "[spu] float: %s\\n", g_spu_fz ? "native, MXCSR round-toward-zero/FTZ/DAZ (SPU_FZ=0: exact AVX2 path)"
                                                  : "exact AVX2 path (SPU_FZ=0)");
}
#endif

/* Run a lifted SPU entry with a halt landing pad. Returns 1 if the job halted
 * (via spu_halt), 0 if it returned normally. */
int spu_run_with_halt(void (*entry)(spu_context*), spu_context* ctx)
{
    int halted = 0;
#if defined(SPU_FZ_MXCSR)
    const unsigned fz_outer = _mm_getcsr();   /* spu fz: the SPU's rounding for this run */
    if (g_spu_fz) _mm_setcsr(SPU_FZ_MXCSR);
#endif''',
     "spu fz: mxcsr in run_with_halt")
edit(SCH,
     '''    yz_lockstep_unregister(ctx);   /* leave the ring; hand the token onward */
    s_spu_halt_armed = outer_armed;
    if (outer_armed) memcpy(s_spu_halt_env, outer_env, sizeof(jmp_buf));
    return halted;''',
     '''    yz_lockstep_unregister(ctx);   /* leave the ring; hand the token onward */
    s_spu_halt_armed = outer_armed;
    if (outer_armed) memcpy(s_spu_halt_env, outer_env, sizeof(jmp_buf));
#if defined(SPU_FZ_MXCSR)
    _mm_setcsr(fz_outer);   /* spu fz: the caller's MXCSR back */
#endif
    return halted;''',
     "spu fz: mxcsr restore")
# spu vcvt: cflts/cfltu/csflt/cuflt, fi and the float compares as SSE vector code, bit exact (x86)
# After spu fz the scalar out-of-line helpers are the next float cost in the if2 SPU profile
# (spu_cflts 1.3%, spu_fi 0.8, spu_csflt 0.8, spu_cuflt 0.8 of all samples, called, not inlined).
#   cflts/cfltu: x * 2^scale is exact (or overflows/underflows, which saturates or truncates to 0
#     anyway); cvttps2dq truncates; positive overflow fixed to 0x7FFFFFFF, cfltu splits at 2^31;
#     exponent-0 lanes are the SPU's zero; exponent-255 lanes or a scale outside -126..127 take the
#     scalar path.
#   csflt/cuflt: cvtdq2ps under spu fz's round-toward-zero MXCSR is the SPU's truncation (cuflt:
#     hi*65536 + lo, one rounding); the 2^-scale is an exponent subtraction with the same
#     saturation and underflow as spu__sf_pack. Only with spu fz on (else the scalar path).
#   fi: the 33-bit fixed-point difference is formed as floor(m / 256) in 32-bit lanes, which keeps
#     every bit the truncated 23-bit fraction uses.
#   fceq/fcgt/fcmeq/fcmgt: zero/denormal -> 0, then sign-magnitude as two's complement.
# tools/test_spu_vcvt.c checks each against the scalar forms bit for bit.
SFH = "runtime/spu/spu_helpers.h"
edit(SFH,
     '''#else
static inline u128 spu_cflts(u128 a, int i8) { return spu_cflts_exact(a, i8); }
static inline u128 spu_cfltu(u128 a, int i8) { return spu_cfltu_exact(a, i8); }
#endif
static inline u128 spu_csflt(u128 a, int i8) { u128 r; for (int i = 0; i < 4; i++) { const int32_t v = a._s32[i];
    r._u32[i] = v ? spu__sf_pack(v < 0 ? 0x80000000u : 0, v < 0 ? 0u - (uint32_t)v : (uint32_t)v, -(155 - (i8 & 0xFF))) : 0; } return r; }
static inline u128 spu_cuflt(u128 a, int i8) { u128 r; for (int i = 0; i < 4; i++) { const uint32_t v = a._u32[i];
    r._u32[i] = v ? spu__sf_pack(0, v, -(155 - (i8 & 0xFF))) : 0; } return r; }''',
     '''#elif defined(SPU_FZ_MXCSR)   /* spu vcvt (tools/patch_spu_vcvt.py): SSE forms, bit exact */
static inline __m128i spu__vc_ld(u128 v) { __m128i r; memcpy(&r, &v, 16); return r; }
static inline u128 spu__vc_st(__m128i v) { u128 r; memcpy(&r, &v, 16); return r; }
static inline __m128i spu__vc_bexp(__m128i x) { return _mm_srli_epi32(_mm_slli_epi32(x, 1), 24); }
/* x * 2^scale, or 0 when a lane has exponent 255 or the scale is not a normal power of two */
static inline int spu__vc_scaled(__m128i x, int scale, __m128* f) {
    if (scale < -126 || scale > 127) return 0;
    const __m128i e255 = _mm_cmpeq_epi32(spu__vc_bexp(x), _mm_set1_epi32(255));
    if (!_mm_testz_si128(e255, e255)) return 0;
    *f = _mm_mul_ps(_mm_castsi128_ps(x), _mm_castsi128_ps(_mm_set1_epi32((127 + scale) << 23)));
    return 1;
}
static inline u128 spu_cflts(u128 a, int i8) {
    const __m128i x = spu__vc_ld(a); __m128 f;
    if (!spu__vc_scaled(x, 173 - (i8 & 0xFF), &f)) return spu_cflts_exact(a, i8);
    __m128i r = _mm_cvttps_epi32(f);
    const __m128i posov = _mm_and_si128(_mm_cmpeq_epi32(r, _mm_set1_epi32((int)0x80000000u)),
                                        _mm_cmpgt_epi32(x, _mm_set1_epi32(-1)));
    r = _mm_add_epi32(r, posov);                                          /* 0x80000000 -> 0x7FFFFFFF */
    return spu__vc_st(_mm_andnot_si128(_mm_cmpeq_epi32(spu__vc_bexp(x), _mm_setzero_si128()), r));
}
static inline u128 spu_cfltu(u128 a, int i8) {
    const __m128i x = spu__vc_ld(a); __m128 f;
    if (!spu__vc_scaled(x, 173 - (i8 & 0xFF), &f)) return spu_cfltu_exact(a, i8);
    const __m128 two31 = _mm_set1_ps(2147483648.0f);
    const __m128 big = _mm_cmpge_ps(f, two31);
    __m128i r = _mm_xor_si128(_mm_cvttps_epi32(_mm_sub_ps(f, _mm_and_ps(big, two31))),
                              _mm_and_si128(_mm_castps_si128(big), _mm_set1_epi32((int)0x80000000u)));
    r = _mm_or_si128(r, _mm_castps_si128(_mm_cmpge_ps(f, _mm_set1_ps(4294967296.0f))));
    const __m128i zero = _mm_or_si128(_mm_cmpeq_epi32(spu__vc_bexp(x), _mm_setzero_si128()),
                                      _mm_srai_epi32(x, 31));             /* SPU zero, or negative */
    return spu__vc_st(_mm_andnot_si128(zero, r));
}
static inline u128 spu_csflt_exact(u128 a, int i8) { u128 r; for (int i = 0; i < 4; i++) { const int32_t v = a._s32[i];
    r._u32[i] = v ? spu__sf_pack(v < 0 ? 0x80000000u : 0, v < 0 ? 0u - (uint32_t)v : (uint32_t)v, -(155 - (i8 & 0xFF))) : 0; } return r; }
static inline u128 spu_cuflt_exact(u128 a, int i8) { u128 r; for (int i = 0; i < 4; i++) { const uint32_t v = a._u32[i];
    r._u32[i] = v ? spu__sf_pack(0, v, -(155 - (i8 & 0xFF))) : 0; } return r; }
/* f = the truncated single of the integer (spu fz MXCSR); scaled by 2^-s as spu__sf_pack does */
static inline u128 spu__vc_unscale(__m128i v, __m128i fi, int s) {
    const __m128i e = _mm_sub_epi32(spu__vc_bexp(fi), _mm_set1_epi32(s));
    __m128i r = _mm_or_si128(_mm_and_si128(fi, _mm_set1_epi32((int)0x807FFFFFu)), _mm_slli_epi32(e, 23));
    const __m128i over = _mm_cmpgt_epi32(e, _mm_set1_epi32(255));
    r = _mm_blendv_epi8(r, _mm_or_si128(_mm_and_si128(fi, _mm_set1_epi32((int)0x80000000u)), _mm_set1_epi32(0x7FFFFFFF)), over);
    const __m128i under = _mm_or_si128(_mm_cmpgt_epi32(_mm_set1_epi32(1), e), _mm_cmpeq_epi32(v, _mm_setzero_si128()));
    return spu__vc_st(_mm_andnot_si128(under, r));
}
static inline u128 spu_csflt(u128 a, int i8) {
    if (!g_spu_fz) return spu_csflt_exact(a, i8);
    const __m128i v = spu__vc_ld(a);
    __m128 f; __asm__("vcvtdq2ps %1, %0" : "=x"(f) : "x"(v));        /* rounds per the MXCSR: toward zero */
    return spu__vc_unscale(v, _mm_castps_si128(f), 155 - (i8 & 0xFF));
}
static inline u128 spu_cuflt(u128 a, int i8) {
    if (!g_spu_fz) return spu_cuflt_exact(a, i8);
    const __m128i v = spu__vc_ld(a);
    const __m128i hi = _mm_srli_epi32(v, 16), lo = _mm_and_si128(v, _mm_set1_epi32(0xFFFF));
    __m128 fh, fl, f;
    __asm__("vcvtdq2ps %1, %0" : "=x"(fh) : "x"(hi));
    __asm__("vcvtdq2ps %1, %0" : "=x"(fl) : "x"(lo));
    fh = _mm_mul_ps(fh, _mm_set1_ps(65536.0f));                           /* exact */
    __asm__("vaddps %2, %1, %0" : "=x"(f) : "x"(fh), "x"(fl));            /* one rounding, toward zero */
    return spu__vc_unscale(v, _mm_castps_si128(f), 155 - (i8 & 0xFF));
}
#else
static inline u128 spu_cflts(u128 a, int i8) { return spu_cflts_exact(a, i8); }
static inline u128 spu_cfltu(u128 a, int i8) { return spu_cfltu_exact(a, i8); }
#endif
#ifndef SPU_FZ_MXCSR
static inline u128 spu_csflt(u128 a, int i8) { u128 r; for (int i = 0; i < 4; i++) { const int32_t v = a._s32[i];
    r._u32[i] = v ? spu__sf_pack(v < 0 ? 0x80000000u : 0, v < 0 ? 0u - (uint32_t)v : (uint32_t)v, -(155 - (i8 & 0xFF))) : 0; } return r; }
static inline u128 spu_cuflt(u128 a, int i8) { u128 r; for (int i = 0; i < 4; i++) { const uint32_t v = a._u32[i];
    r._u32[i] = v ? spu__sf_pack(0, v, -(155 - (i8 & 0xFF))) : 0; } return r; }
#endif''',
     "spu vcvt: cflt/csflt sse")
edit(SFH,
     '''static inline u128 spu_fi(u128 a, u128 b) {
    u128 r;''',
     '''static inline u128 spu_fi_exact(u128 a, u128 b) {   /* spu vcvt: the scalar form */
    u128 r;''',
     "spu vcvt: fi exact rename")
edit(SFH,
     '''        r._u32[i] = sign | ((uint32_t)exp << 23) | frac;
    }
    return r;
}''',
     '''        r._u32[i] = sign | ((uint32_t)exp << 23) | frac;
    }
    return r;
}
#if defined(SPU_FZ_MXCSR)   /* spu vcvt: fi in 32-bit lanes; m8 = floor(m / 256), m < 2^33 */
static inline u128 spu_fi(u128 a, u128 b) {
    const __m128i est = spu__vc_ld(b), y = _mm_and_si128(spu__vc_ld(a), _mm_set1_epi32(0x7FFFF));
    const __m128i exp = _mm_and_si128(_mm_srli_epi32(est, 23), _mm_set1_epi32(0xFF));
    const __m128i base = _mm_and_si128(_mm_srli_epi32(est, 10), _mm_set1_epi32(0x1FFF));
    const __m128i step = _mm_and_si128(est, _mm_set1_epi32(0x3FF));
    const __m128i a8 = _mm_slli_epi32(_mm_or_si128(base, _mm_set1_epi32(0x2000)), 11);
    const __m128i m8 = _mm_sub_epi32(a8, _mm_srli_epi32(_mm_add_epi32(_mm_mullo_epi32(step, y), _mm_set1_epi32(255)), 8));
    const __m128i lt1 = _mm_cmpgt_epi32(_mm_set1_epi32(1 << 24), m8);    /* magnitude below 1.0 */
    const __m128i frac = _mm_and_si128(_mm_blendv_epi8(_mm_srli_epi32(m8, 1), m8, lt1), _mm_set1_epi32(0x7FFFFF));
    const __m128i e2 = _mm_add_epi32(exp, lt1);
    const __m128i r = _mm_or_si128(_mm_or_si128(_mm_and_si128(est, _mm_set1_epi32((int)0x80000000u)), _mm_slli_epi32(e2, 23)), frac);
    const __m128i zero = _mm_or_si128(_mm_cmpeq_epi32(exp, _mm_setzero_si128()), _mm_cmpeq_epi32(e2, _mm_setzero_si128()));
    return spu__vc_st(_mm_andnot_si128(zero, r));
}
#else
static inline u128 spu_fi(u128 a, u128 b) { return spu_fi_exact(a, b); }
#endif''',
     "spu vcvt: fi sse")
edit(SFH,
     '''SPU__SF_V2(spu_fceq,  spu__sf_key(x) == spu__sf_key(y) ? 0xFFFFFFFFu : 0u)
SPU__SF_V2(spu_fcgt,  spu__sf_key(x) >  spu__sf_key(y) ? 0xFFFFFFFFu : 0u)
SPU__SF_V2(spu_fcmeq, spu__sf_mag(x) == spu__sf_mag(y) ? 0xFFFFFFFFu : 0u)
SPU__SF_V2(spu_fcmgt, spu__sf_mag(x) >  spu__sf_mag(y) ? 0xFFFFFFFFu : 0u)''',
     '''SPU__SF_V2(spu_fceq_ref,  spu__sf_key(x) == spu__sf_key(y) ? 0xFFFFFFFFu : 0u)   /* spu vcvt: scalar forms */
SPU__SF_V2(spu_fcgt_ref,  spu__sf_key(x) >  spu__sf_key(y) ? 0xFFFFFFFFu : 0u)
SPU__SF_V2(spu_fcmeq_ref, spu__sf_mag(x) == spu__sf_mag(y) ? 0xFFFFFFFFu : 0u)
SPU__SF_V2(spu_fcmgt_ref, spu__sf_mag(x) >  spu__sf_mag(y) ? 0xFFFFFFFFu : 0u)
#if defined(SPU_FZ_MXCSR)
static inline __m128i spu__fc_mag(u128 v) {   /* |x| with the SPU's zeros (exponent 0) as 0 */
    __m128i x; memcpy(&x, &v, 16);
    const __m128i m = _mm_and_si128(x, _mm_set1_epi32(0x7FFFFFFF));
    return _mm_and_si128(m, _mm_cmpgt_epi32(m, _mm_set1_epi32(0x7FFFFF)));
}
static inline __m128i spu__fc_key(u128 v) {   /* sign-magnitude as two's complement */
    __m128i x; memcpy(&x, &v, 16);
    const __m128i s = _mm_srai_epi32(x, 31);
    return _mm_sub_epi32(_mm_xor_si128(spu__fc_mag(v), s), s);
}
static inline u128 spu__fc_st(__m128i m) { u128 r; memcpy(&r, &m, 16); return r; }
static inline u128 spu_fceq(u128 a, u128 b)  { return spu__fc_st(_mm_cmpeq_epi32(spu__fc_key(a), spu__fc_key(b))); }
static inline u128 spu_fcgt(u128 a, u128 b)  { return spu__fc_st(_mm_cmpgt_epi32(spu__fc_key(a), spu__fc_key(b))); }
static inline u128 spu_fcmeq(u128 a, u128 b) { return spu__fc_st(_mm_cmpeq_epi32(spu__fc_mag(a), spu__fc_mag(b))); }
static inline u128 spu_fcmgt(u128 a, u128 b) { return spu__fc_st(_mm_cmpgt_epi32(spu__fc_mag(a), spu__fc_mag(b))); }
#else
static inline u128 spu_fceq(u128 a, u128 b)  { return spu_fceq_ref(a, b); }
static inline u128 spu_fcgt(u128 a, u128 b)  { return spu_fcgt_ref(a, b); }
static inline u128 spu_fcmeq(u128 a, u128 b) { return spu_fcmeq_ref(a, b); }
static inline u128 spu_fcmgt(u128 a, u128 b) { return spu_fcmgt_ref(a, b); }
#endif''',
     "spu vcvt: fc sse")
# spu fz: with SPU_FZ=0 the ops call the exact path out of line (spu__fz_slow: its MXCSR save/restore
# is a no-op then) instead of inlining it beside the native form at every site: inlined, every
# lifted float op carried ~40 instructions of dead code (the d0d15 chunk D8A8: ~4400 instructions).
edit(SFH,
     '''        return spu__fz_pos0(r);                                                                \\
    }                                                                                          \\
    return exact;                                                                              \\
}
#define SPU__FZ3(name, insn, op, exact)                                                        \\''',
     '''        return spu__fz_pos0(r);                                                                \\
    }                                                                                          \\
    return spu__fz_slow(op, a, b, b);   /* spu fz: exact path out of line */                    \\
}
#define SPU__FZ3(name, insn, op, exact)                                                        \\''',
     "spu fz: exact out of line 2")
edit(SFH,
     '''        return spu__fz_pos0(r);                                                                \\
    }                                                                                          \\
    return exact;                                                                              \\
}
SPU__FZ2(spu_fa,''',
     '''        return spu__fz_pos0(r);                                                                \\
    }                                                                                          \\
    return spu__fz_slow(op, a, b, c);   /* spu fz: exact path out of line (3) */                \\
}
SPU__FZ2(spu_fa,''',
     "spu fz: exact out of line 3")
# spu fz2: the native float ops' check on the result only, and the exact path returning in an XMM register
# Two costs left in every spu fz float op (d0d15 chunk D8A8, objdump):
#  - the range check tested all three operands and the result (13 instructions). Under round toward
#    zero a finite operand never gives Inf/NaN (an overflow is FLT_MAX), and an Inf/NaN operand
#    (exponent 255) always gives Inf/NaN in add/mul/fma. So |r| >= FLT_MAX (as integers) catches
#    every lane the exact path must redo: 3 instructions.
#  - spu__fz_slow returned a u128 by value, which the SysV ABI returns in rax:rdx; the merge of the
#    fast and slow results then kept every result as two i64 halves (vmovq + vpextrq + two 64-bit
#    stores per op). It now returns an __m128.
SFH = "runtime/spu/spu_helpers.h"
edit(SFH,
     '''/* the exact path, with the default MXCSR around it (it computes in double, round to nearest) */
SPU__XV_SLOW u128 spu__fz_slow(int op, u128 a, u128 b, u128 c) {''',
     '''/* spu fz2: lanes the hardware result may be wrong in: Inf/NaN (an operand of exponent 255) or
 * FLT_MAX (an overflow). */
SPU__XV_INLINE int spu__fz_bad_r(__m128 r) {
    const __m128i m = _mm_cmpgt_epi32(_mm_and_si128(_mm_castps_si128(r), _mm_set1_epi32(0x7FFFFFFF)),
                                      _mm_set1_epi32(0x7F7FFFFE));
    return !_mm_testz_si128(m, m);
}
/* the exact path, with the default MXCSR around it (it computes in double, round to nearest) */
SPU__XV_SLOW u128 spu__fz_slow(int op, u128 a, u128 b, u128 c);
SPU__XV_SLOW __m128 spu__fz_slowv(int op, u128 a, u128 b, u128 c) {   /* spu fz2: returns in xmm0 */
    const u128 r = spu__fz_slow(op, a, b, c);
    __m128 v; memcpy(&v, &r, 16); return v;
}
SPU__XV_SLOW u128 spu__fz_slow(int op, u128 a, u128 b, u128 c) {''',
     "spu fz2: result check + xmm slow")
edit(SFH,
     '''        __asm__(insn " %2, %1, %0" : "=x"(r) : "x"(x), "x"(y));                                 \\
        if (__builtin_expect(spu__fz_bad(x, y, y, r), 0)) return spu__fz_slow(op, a, b, b);     \\
        return spu__fz_pos0(r);                                                                \\
    }                                                                                          \\
    return spu__fz_slow(op, a, b, b);   /* spu fz: exact path out of line */                    \\''',
     '''        __asm__(insn " %2, %1, %0" : "=x"(r) : "x"(x), "x"(y));                                 \\
        if (__builtin_expect(spu__fz_bad_r(r), 0)) r = spu__fz_slowv(op, a, b, b);             \\
        else r = _mm_and_ps(r, _mm_cmpneq_ps(r, _mm_setzero_ps()));   /* spu fz2: +0 */         \\
        return spu__fz_u(r);                                                                   \\
    }                                                                                          \\
    return spu__fz_u(spu__fz_slowv(op, a, b, b));   /* spu fz: exact path out of line */        \\''',
     "spu fz2: FZ2 macro")
edit(SFH,
     '''        __asm__(insn " %3, %2, %0" : "=x"(r) : "0"(x), "x"(y), "x"(z));                         \\
        if (__builtin_expect(spu__fz_bad(x, y, z, r), 0)) return spu__fz_slow(op, a, b, c);     \\
        return spu__fz_pos0(r);                                                                \\
    }                                                                                          \\
    return spu__fz_slow(op, a, b, c);   /* spu fz: exact path out of line (3) */                \\''',
     '''        __asm__(insn " %3, %2, %0" : "=x"(r) : "0"(x), "x"(y), "x"(z));                         \\
        if (__builtin_expect(spu__fz_bad_r(r), 0)) r = spu__fz_slowv(op, a, b, c);             \\
        else r = _mm_and_ps(r, _mm_cmpneq_ps(r, _mm_setzero_ps()));   /* spu fz2: +0 (3) */     \\
        return spu__fz_u(r);                                                                   \\
    }                                                                                          \\
    return spu__fz_u(spu__fz_slowv(op, a, b, c));   /* spu fz: exact path out of line (3) */    \\''',
     "spu fz2: FZ3 macro")
# spu shufb2: shufb on host byte order: no byte swaps of the operands, control and result
# shufb is the most common SPU op in if2's job code (~20k sites). The SSE4.1 form swapped A, B, C into
# SPU byte order and the result back (4 pshufb) before selecting. SPU byte P is host byte P^3 and the
# control byte for result host byte h sits at host byte h, so selecting with (C & 0x0F) ^ 3 works in
# host order directly. pshufb already zeroes the bytes whose control has bit 7 set (the 10x
# selectors' 0x00); 110 -> 0xFF and 111 -> 0x80 are ORed in. ~12 instructions instead of ~20.
# tools/test_spu_shufb2.c checks it against spu_shufb_ref.
SFH = "runtime/spu/spu_helpers.h"
edit(SFH,
     '''static inline u128 spu_shufb(u128 a, u128 b, u128 c) {
    const __m128i sw = _mm_setr_epi8(3,2,1,0, 7,6,5,4, 11,10,9,8, 15,14,13,12);
    __m128i A, B, C; memcpy(&A, &a, 16); memcpy(&B, &b, 16); memcpy(&C, &c, 16);''',
     '''static inline u128 spu_shufb(u128 a, u128 b, u128 c) {   /* spu shufb2: host byte order */
    __m128i A, B, C; memcpy(&A, &a, 16); memcpy(&B, &b, 16); memcpy(&C, &c, 16);
    const __m128i idx = _mm_xor_si128(C, _mm_set1_epi8(3));           /* bit 7 kept: pshufb zeroes */
    __m128i r = _mm_blendv_epi8(_mm_shuffle_epi8(A, idx), _mm_shuffle_epi8(B, idx), _mm_slli_epi16(C, 3));
    const __m128i mC0 = _mm_cmpeq_epi8(_mm_and_si128(C, _mm_set1_epi8((char)0xC0)), _mm_set1_epi8((char)0xC0));
    const __m128i mE0 = _mm_cmpeq_epi8(_mm_and_si128(C, _mm_set1_epi8((char)0xE0)), _mm_set1_epi8((char)0xE0));
    r = _mm_or_si128(r, _mm_andnot_si128(_mm_and_si128(mE0, _mm_set1_epi8(0x7F)), mC0));
    u128 out; memcpy(&out, &r, 16); return out;
}
static inline u128 spu_shufb_sw(u128 a, u128 b, u128 c) {   /* spu shufb2: the previous form */
    const __m128i sw = _mm_setr_epi8(3,2,1,0, 7,6,5,4, 11,10,9,8, 15,14,13,12);
    __m128i A, B, C; memcpy(&A, &a, 16); memcpy(&B, &b, 16); memcpy(&C, &c, 16);''',
     "spu shufb2: host order")
# lwsync cv reuse: one condition variable per thread for lwmutex/lwcond waits (the PS5 pthread pool leak)
# The console runs died after 6-12 min with "[ScePthread/System] Internal Memory is running out." (if1
# 2026-11-02 15:55, if2 21:19). BC-250 count (tools/pthread_leakcount.c, LD_PRELOAD): in ~2 min of if2,
# SleepConditionVariableSRW (sys_lwsync.c) did 14,831 pthread_mutex_init + 14,830 pthread_cond_init and
# no destroy. Each lwmutex/lwcond wait puts a waiter on the stack whose CONDITION_VARIABLE is created
# lazily on its first sleep (calloc + mutex + cond, win32_compat.h ps3_cv) and never freed: Win32
# condition variables need no cleanup, so the emulation has no delete. On the PS5 every one holds a
# libkernel pthread object until the pool runs out (on Linux, heap). Now each thread creates one
# ps3_condvar on its first wait and every later wait of that thread reuses it. A thread is in at most
# one wait at a time, and wakers run under s_lock while the waiter is queued, so a reused object never
# gets a wake meant for an earlier wait that matters (a stray generation bump is a spurious wakeup,
# which the while (!w->woken) loops already allow).
LWS = "runtime/syscalls/sys_lwsync.c"
edit(LWS,
     '''static void waiter_init(waiter* w, ppu_context* ctx)
{
    memset(w, 0, sizeof *w);
    w->tid = ctx->thread_id;
    InitializeConditionVariable(&w->cv);
}''',
     '''static __thread CONDITION_VARIABLE t_lw_cv;   /* lwsync cv reuse: this thread's one condvar */
static void waiter_init(waiter* w, ppu_context* ctx)
{
    memset(w, 0, sizeof *w);
    w->tid = ctx->thread_id;
    InitializeConditionVariable(&w->cv);
    if (!t_lw_cv) WakeConditionVariable(&t_lw_cv);   /* creates it (a wake with no waiter is a no-op) */
    w->cv = t_lw_cv;
}''',
     "lwsync cv reuse")

# kb not connected: no keyboard until the host sends a key (inFAMOUS 2 showed PC mouse prompts)
# cellKbInit marked keyboard 0 connected unconditionally. if2 calls cellKbInit(7) and, seeing a keyboard,
# switches its button prompts to the keyboard/mouse set ("Use [mouse] to aim" instead of "Hold [L1] to
# aim"; console run 2026-11-02, work/console_if2_20261102/4_fight_mouse_prompts.jpg). The real PS3 has
# no keyboard. Now a port connects on its first cellKb_keyEvent (as cellMouse already did); nothing on
# the PS5 sends one. PS3_KB_CONNECTED=1 restores the old always-connected keyboard 0.
edit("libs/input/cellKb.c",
     '''    /* Assume keyboard 0 is always connected on the host */
    s_kb_ports[0].connected = 1;
''',
     '''    /* kb not connected: keyboard 0 connects on its first host key event (PS3_KB_CONNECTED=1: at once) */
    { const char* e = getenv("PS3_KB_CONNECTED"); s_kb_ports[0].connected = e && *e == '1'; }
''',
     "kb not connected")
edit("libs/input/cellKb.c",
     '''#include <string.h>
#include <stdint.h>
''',
     '''#include <string.h>
#include <stdint.h>
#include <stdlib.h>   /* kb not connected: getenv */
''',
     "kb not connected include")

# eng texwatch: log what watched texture addresses resolve to, for every draw (effects-buffer hunt)
# PS3RECOMP_ENG_TEXWATCH=<hex>[,<hex>...] (up to 8 guest offsets): once per (fragment program, unit,
# offset, target) a line with the target surface, the texture's size/format/filter/location, the
# backend handle it resolved to, and whether that handle is an engine colour surface (an RT) or not.
# For inFAMOUS 2's soft particles / quarter-res effects (real PS3 chain: 0xF770000 512x288 depth ->
# 0xB9E000 512x288 particles -> 0xE3C000 320x180 -> full-res composite, work/ps3_if2_20261103).
edit("libs/video/rsx_draw_engine.c",
     '''    /* PS3RECOMP_ENG_SKIP_FP=<hex>[,<hex>...]: drop draws whose fragment
     * program has that structural hash (TEXSTATE's fp=).''',
     '''    /* eng texwatch: PS3RECOMP_ENG_TEXWATCH=<hex>[,..] -- what a watched texture offset resolves to */
    { static u32 wo[8]; static int nw = -1;
      if (__builtin_expect(nw < 0, 0)) { nw = 0; const char* e = getenv("PS3RECOMP_ENG_TEXWATCH");
          while (e && *e && nw < 8) { char* x; wo[nw++] = (u32)strtoul(e, &x, 16); e = (*x == ',') ? x + 1 : NULL; } }
      if (nw && n_targets) {
          static u64 seen[512]; static u32 ns;
          const eng_fp_memo* fpm = NULL;
          const u64 fk = eng_guest_programs(NULL, &fpm) && fpm ? fpm->structural : 0;
          for (u32 u = 0; u < RSX_BE_MAX_TEXTURES; u++) {
              rsx_dsp_texture t; rsx_dsp_get_texture(&g.rsx, u, &t);
              if (!t.enabled) continue;
              int hit = 0; for (int i = 0; i < nw; i++) hit |= (t.offset == wo[i]);
              if (!hit) continue;
              const u64 key = fk ^ ((u64)t.offset << 20) ^ ((u64)u << 56) ^ ((u64)g.surfaces[targets[0]].offset << 4);
              u32 k = 0; while (k < ns && seen[k] != key) k++;
              if (k < ns || ns >= 512) continue;
              seen[ns++] = key;
              int rt = -1; for (u32 i = 0; i < g.n_surfaces; i++) if (textures[u] && g.surfaces[i].handle == textures[u]) rt = (int)i;
              fprintf(stderr, "[texwatch] frame %u fp %016llx into 0x%08X %ux%u: unit %u off 0x%08X loc %u fmt 0x%02X %ux%u filter 0x%08X (min_lin %u mag_lin %u) -> h%u %s",
                      g.frames, (unsigned long long)fk, g.surfaces[targets[0]].offset, g.surfaces[targets[0]].w, g.surfaces[targets[0]].h,
                      u, t.offset, t.location, t.format, t.width, t.height, t.filter,
                      samplers[u].min_linear, samplers[u].mag_linear, textures[u], rt >= 0 ? "RT" : "not-an-RT");
              if (rt >= 0) fprintf(stderr, " (surface 0x%08X %ux%u)", g.surfaces[rt].offset, g.surfaces[rt].w, g.surfaces[rt].h);
              fprintf(stderr, " verts %u\\n", dc.n_verts);
          } } }

    /* PS3RECOMP_ENG_SKIP_FP=<hex>[,<hex>...]: drop draws whose fragment
     * program has that structural hash (TEXSTATE's fp=).''',
     "eng texwatch")

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

# vk stage ring: texture uploads copy through the per-frame ring instead of a new staging buffer each
# A BC-250 if2 RSX-thread profile (kb1, 2026-11-03) had ~25% of the thread in the kernel and the
# driver, most of it vk_create_host_buffer (vkCreateBuffer + vkAllocateMemory + vkMapMemory: an
# amdgpu BO alloc ioctl, a VA alloc and an mmap) and the free after it -- one per texture upload and
# per mip level. The ring (s_ring) is host-visible and coherent and is reused only after the GPU has
# finished the submission that read it (vk_batch_after_flush after a fence wait, vk_slot_rotate after
# the slot's fence), so a copy recorded from it is safe like the vertex data in it. No ring yet, or
# full: the old path. PS3_VK_STAGE_RING=0: always the old path.
edit("libs/video/rsx_vulkan_backend.c",
     '''static vk_buffer        s_ring;                 /* per-frame vertices, indices, constants */
static VkDeviceSize     s_ring_off, s_ubo_align;
''',
     '''static vk_buffer        s_ring;                 /* per-frame vertices, indices, constants */
static VkDeviceSize     s_ring_off, s_ubo_align;
static void* vk_ring_alloc(VkDeviceSize bytes, VkDeviceSize align, VkDeviceSize* off);
/* vk stage ring: staging space for an upload from the ring (*buf = the ring) or a fresh buffer in *own. */
static void* vk_stage_alloc(VkDeviceSize bytes, vk_buffer* own, VkBuffer* buf, VkDeviceSize* off)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3_VK_STAGE_RING"); on = !(e && *e == '0'); }
    memset(own, 0, sizeof *own);
    if (on && s_ring.buf && s_ring.coherent) {
        void* p = vk_ring_alloc(bytes, 16u, off);
        if (p) { *buf = s_ring.buf; return p; }
    }
    if (vk_create_host_buffer(own, bytes, VK_BUFFER_USAGE_TRANSFER_SRC_BIT) || !own->coherent) {
        vk_destroy_buffer(own); return NULL;
    }
    *buf = own->buf; *off = 0;
    return own->ptr;
}
''',
     "vk stage ring decl")
# vk_create_host_buffer / vk_destroy_buffer are defined after the ring declarations: forward-declare them.
edit("libs/video/rsx_vulkan_backend.c",
     '''static void* vk_ring_alloc(VkDeviceSize bytes, VkDeviceSize align, VkDeviceSize* off);
/* vk stage ring:''',
     '''static void* vk_ring_alloc(VkDeviceSize bytes, VkDeviceSize align, VkDeviceSize* off);
static int vk_create_host_buffer(vk_buffer* b, VkDeviceSize size, VkBufferUsageFlags usage);
static void vk_destroy_buffer(vk_buffer* b);
/* vk stage ring:''',
     "vk stage ring fwd")
edit("libs/video/rsx_vulkan_backend.c",
     '''        if (vk_create_host_buffer(&s_ring, VK_RING_BYTES, VK_BUFFER_USAGE_VERTEX_BUFFER_BIT |
                                  VK_BUFFER_USAGE_INDEX_BUFFER_BIT | VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT) ||''',
     '''        if (vk_create_host_buffer(&s_ring, VK_RING_BYTES, VK_BUFFER_USAGE_VERTEX_BUFFER_BIT |
                                  VK_BUFFER_USAGE_INDEX_BUFFER_BIT | VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT |
                                  VK_BUFFER_USAGE_TRANSFER_SRC_BIT /* vk stage ring */) ||''',
     "vk stage ring usage")
# vk_eng_upload_rows
edit("libs/video/rsx_vulkan_backend.c",
     '''    if (tight > row_bytes) tight = row_bytes;
    vk_buffer st = {0};
    if (vk_create_host_buffer(&st, (VkDeviceSize)tight * rows, VK_BUFFER_USAGE_TRANSFER_SRC_BIT) ||
        !st.coherent) { vk_destroy_buffer(&st); return -1; }
    for (u32 y = 0; y < rows; y++)
        memcpy((u8*)st.ptr + (size_t)y * tight, (const u8*)src + (size_t)y * row_bytes, tight);
    int rc = vk_begin();
    if (!rc) {
        vk_barrier_image(img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);
        VkBufferImageCopy region = {
            .imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, mip, layer, 1 },
            .imageExtent = { w, h, 1 },
        };
        pvkCmdCopyBufferToImage(s_vk.cmd, st.buf, img, VK_IMAGE_LAYOUT_GENERAL, 1, &region);''',
     '''    if (tight > row_bytes) tight = row_bytes;
    vk_buffer st; VkBuffer sb; VkDeviceSize so;   /* vk stage ring */
    u8* sp = (u8*)vk_stage_alloc((VkDeviceSize)tight * rows, &st, &sb, &so);
    if (!sp) return -1;
    for (u32 y = 0; y < rows; y++)
        memcpy(sp + (size_t)y * tight, (const u8*)src + (size_t)y * row_bytes, tight);
    int rc = vk_begin();
    if (!rc) {
        vk_barrier_image(img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_GENERAL);
        VkBufferImageCopy region = {
            .bufferOffset = so,
            .imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, mip, layer, 1 },
            .imageExtent = { w, h, 1 },
        };
        pvkCmdCopyBufferToImage(s_vk.cmd, sb, img, VK_IMAGE_LAYOUT_GENERAL, 1, &region);''',
     "vk stage ring rows")
# vk_upload_texture_levels
edit("libs/video/rsx_vulkan_backend.c",
     '''    vk_buffer staging = {0};
    if (vk_create_host_buffer(&staging, total, VK_BUFFER_USAGE_TRANSFER_SRC_BIT) ||
        !staging.coherent) {
        vk_destroy_buffer(&staging); return -1;
    }
    memcpy(staging.ptr, rgba, (size_t)total);
''',
     '''    vk_buffer staging; VkBuffer sb; VkDeviceSize so;   /* vk stage ring */
    u8* sp = (u8*)vk_stage_alloc(total, &staging, &sb, &so);
    if (!sp) return -1;
    memcpy(sp, rgba, (size_t)total);
    for (u32 m = 0; m < nlv; m++) regions[m].bufferOffset += so;
''',
     "vk stage ring levels")
edit("libs/video/rsx_vulkan_backend.c",
     '''        pvkCmdCopyBufferToImage(s_vk.cmd, staging.buf, fresh.img, VK_IMAGE_LAYOUT_GENERAL,
                                nlv, regions);''',
     '''        pvkCmdCopyBufferToImage(s_vk.cmd, sb, fresh.img, VK_IMAGE_LAYOUT_GENERAL,
                                nlv, regions);   /* vk stage ring */''',
     "vk stage ring levels 2")

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

# vk readback view: engine readback of a VIEW handle reads its colour surface (diagnostic dumps)
# PS3RECOMP_ENG_OCCDUMP read texture units back with be->readback, which accepted only colour
# targets; a unit bound through surface_view (every depth->RGBA8 copy with a crossbar) returned
# nothing and the dump file held whatever malloc gave back -- the previous dump's bytes (2026-11-03,
# a "particle depth == particle colour" false lead). Views now read their surface; the dump buffer
# is zeroed first.
edit("libs/video/rsx_vulkan_backend.c",
     '''    (void)user;
    vk_eng_obj* o = vk_eng_get(surface, VK_ENG_COLOR);
    if (!o || !out || !out_pitch || !w || !h || x + w > o->w || y + h > o->h) return;''',
     '''    (void)user;
    if (vk_eng_get(surface, VK_ENG_VIEW)) surface = s_eobj[surface].surface;   /* vk readback view */
    vk_eng_obj* o = vk_eng_get(surface, VK_ENG_COLOR);
    if (!o || !out || !out_pitch || !w || !h || x + w > o->w || y + h > o->h) return;''',
     "vk readback view")
edit("libs/video/rsx_draw_engine.c",
     '''                  u8* tp = (u8*)malloc((size_t)t.width * t.height * 4);
                  if (!tp) continue;
                  g.be->readback(g.be->user, textures[u], 0, 0, t.width, t.height, tp, t.width * obpp);''',
     '''                  u8* tp = (u8*)calloc((size_t)t.width * t.height, 4);   /* vk readback view: zeroed */
                  if (!tp) continue;
                  g.be->readback(g.be->user, textures[u], 0, 0, t.width, t.height, tp, t.width * obpp);''',
     "vk readback view calloc")

# eng zprobe: PS3RECOMP_ENG_ZPROBE=<sec>:<zeta hex>:<x>:<y> -- one frame, which draw changes the depth at one pixel
# DIAGNOSTIC (inFAMOUS 2 sky depth hunt, 2026-11-03: the sky reads 0 in our full-res depth, 1.0 on the
# real RSX). <sec> seconds into the run, for one frame: before every draw into that zeta, the depth at
# (x, y) is read back through the depth->RGBA8 copy (a flush per draw: debugging only) and every change
# is printed with the previous draw's fragment program, depth func/write/clamp state and vertex count.
edit("libs/video/rsx_draw_engine.c",
     '''    const u32 depth_handle = (zslot != ENG_INVALID) ? g.zdepths[zslot].handle : 0;
    if (zslot != ENG_INVALID && !g.zdepths[zslot].cleared) {''',
     '''    /* eng zprobe */
    { static int zi; static long zsec = -1; static u32 zoff, zx, zy, zframe = ~0u; static int zdone;
      static unsigned long long zt0; static float zlast = -1.0f; static u64 zprev_fp; static u32 zprev_n, zprev_zs;
      if (!zi) { zi = 1; const char* e = getenv("PS3RECOMP_ENG_ZPROBE");
          if (e) { char* d; zsec = strtol(e, &d, 10); if (*d == ':') zoff = (u32)strtoul(d + 1, &d, 16);
                   if (*d == ':') zx = (u32)strtoul(d + 1, &d, 10); if (*d == ':') zy = (u32)strtoul(d + 1, &d, 10); } }
      if (zsec >= 0 && !zdone && zslot != ENG_INVALID && g.be->readback) {
          extern unsigned long long ps3_ms_now(void);
          if (!zt0) zt0 = ps3_ms_now();
          if (zframe == ~0u && ps3_ms_now() - zt0 >= (unsigned long long)zsec * 1000ull) zframe = g.frames + 1u;
          if (zframe != ~0u && g.frames > zframe) { zdone = 1; fprintf(stderr, "[zprobe] frame %u done\\n", zframe); }
          else if (g.frames == zframe && g.zdepths[zslot].offset == zoff) {
              const eng_zdepth* z = &g.zdepths[zslot];
              float v = -2.0f;   /* -2: no copy (nothing written since the clear) */
              if (zx < z->w && zy < z->h) {
                  eng_zdepth* zw = &g.zdepths[zslot]; const int hw = zw->had_write;
                  if (!hw) { zw->had_write = 1; zw->snapshot_rgba_valid = 0; }   /* eng zprobe: read the cleared image too */
                  const u32 snap = eng_zdepth_snapshot_rgba8(zslot);
                  if (!hw) { zw->had_write = 0; zw->snapshot_rgba_valid = 0; }
                  u8 px[4] = { 0 };
                  if (snap) { g.be->readback(g.be->user, snap, zx, zy, 1, 1, px, 4);
                              v = px[3] / 256.0f + px[0] / 65536.0f + px[1] / 16777216.0f; }
              }
              if (v != zlast)
                  fprintf(stderr, "[zprobe] frame %u depth at (%u,%u) %.6f -> %.6f after fp %016llx (n %u, ztest/zwrite/zfunc/clamp 0x%X)\\n",
                          g.frames, zx, zy, zlast, v, (unsigned long long)zprev_fp, zprev_n, zprev_zs);
              zlast = v;
              zprev_fp = eng_current_fp_structural(); zprev_n = dc.n_verts;
              zprev_zs = (rs.depth_test << 24) | (rs.depth_write << 20) | (rs.depth_func & 0xFFFu) << 4 | (rsx_dsp_reg(&g.rsx, 0x1D78) & 0xFu);
          } } }
    const u32 depth_handle = (zslot != ENG_INVALID) ? g.zdepths[zslot].handle : 0;
    if (zslot != ENG_INVALID && !g.zdepths[zslot].cleared) {''',
     "eng zprobe")

# eng clearlog: PS3RECOMP_ENG_CLEARLOG=<n> -- the first n depth/stencil clears: mask, colour targets, zeta, value, frame
# DIAGNOSTIC for the inFAMOUS 2 sky-depth hunt (2026-11-03): reports a depth clear that sink_clear drops
# because no colour target is bound (the early return), as well as the ones it applies.
edit("libs/video/rsx_draw_engine.c",
     '''    u32 targets[RSX_BE_MAX_COLOR_TARGETS];
    const u32 n_targets = eng_current_target_set(targets);
    if (!n_targets) return;

    /* PS3RECOMP_ENG_MRTLOG=2: each distinct colour clear''',
     '''    u32 targets[RSX_BE_MAX_COLOR_TARGETS];
    const u32 n_targets = eng_current_target_set(targets);
    { static int cl = -1; if (cl < 0) { const char* e = getenv("PS3RECOMP_ENG_CLEARLOG"); cl = e ? atoi(e) : 0; }   /* eng clearlog */
      if (cl > 0 && (mask & (RSX_CLEAR_DEPTH | RSX_CLEAR_STENCIL))) { cl--;
          rsx_dsp_surface sf; rsx_dsp_get_surface(&g.rsx, &sf);
          fprintf(stderr, "[clearlog] frame %u mask 0x%02X targets %u zeta 0x%08X clip %ux%u value 0x%08X%s\\n", g.frames, mask,
                  n_targets, sf.zeta_offset, sf.clip_w, sf.clip_h, rsx_dsp_reg(&g.rsx, M_ZSTENCIL_CLEAR), n_targets ? "" : " DROPPED (no colour target)"); } }
    if (!n_targets) return;

    /* PS3RECOMP_ENG_MRTLOG=2: each distinct colour clear''',
     "eng clearlog")

# vk d24 clamp: depth 1.0 -> 0xFFFFFF in the depth->A8R8G8B8 copies (it wrapped to 0: the sky read as nearest)
# Both copies computed (uint)(d * 16777215 + 0.5); for d = 1.0 that is 16777215.5, which in float32
# rounds to 16777216 = 0x1000000, whose low 24 bits are 0. Every far-plane / cleared pixel (the whole
# sky) came out as depth 0 in the A8R8G8B8 view inFAMOUS 2 decodes: its soft particles discard where
# scene <= particle depth, so all smoke, fire and glow in front of the sky was thrown away and the rest
# was cut along building silhouettes at the 512x288 grid -- the console's "solid blocks with
# stair-stepped edges" (BC-250 proof: work/occ6 depth copy 0 in the sky, real RSX 1.0 there;
# PS3RECOMP_ENG_ZPROBE read 0 right after the 1.0 clear). Clamped to 0xFFFFFF.
# PS3_VK_D24_CLAMP=0 is the old (wrapping) GPU shader; the CPU fallback is always fixed.
edit("libs/video/rsx_vulkan_backend.c",
     '''            const u32 d24 = (u32)(v * 16777215.0f + 0.5f);''',
     '''            u32 d24 = (u32)(v * 16777215.0f + 0.5f);
            if (d24 > 0xFFFFFFu) d24 = 0xFFFFFFu;   /* vk d24 clamp: 1.0 rounded to 0x1000000 */''',
     "vk d24 clamp cpu")
edit("libs/video/rsx_vulkan_backend.c",
     '''    "    uint v = (uint)(d * 16777215.0 + 0.5);\\n"
    "    return float4((float)((v >> 8) & 255u), (float)(v & 255u), 0.0, (float)((v >> 16) & 255u)) / 255.0;\\n"
    "}\\n";''',
     '''    "    uint v = min((uint)(d * 16777215.0 + 0.5), 16777215u);\\n"   /* vk d24 clamp */
    "    return float4((float)((v >> 8) & 255u), (float)(v & 255u), 0.0, (float)((v >> 16) & 255u)) / 255.0;\\n"
    "}\\n";
static const char* const s_dz_ps_old =   /* PS3_VK_D24_CLAMP=0: the wrapping original */
    "Texture2D    rsx_tex[16] : register(t0);\\n"
    "SamplerState rsx_samp[16] : register(s0);\\n"
    "struct PSInput { float4 pos:SV_Position; };\\n"
    "float4 main(PSInput input) : SV_TARGET {\\n"
    "    float d = saturate(rsx_tex[0].Load(int3(int2(input.pos.xy), 0)).x);\\n"
    "    uint v = (uint)(d * 16777215.0 + 0.5);\\n"
    "    return float4((float)((v >> 8) & 255u), (float)(v & 255u), 0.0, (float)((v >> 16) & 255u)) / 255.0;\\n"
    "}\\n";''',
     "vk d24 clamp gpu")
edit("libs/video/rsx_vulkan_backend.c",
     '''        s_dz_pipe = vk_eng_pipeline_create(user, s_lp_vs, s_dz_ps, &rs, &lay, 16u, RSX_BE_FMT_R8G8B8A8, 1u);''',
     '''        { const char* e = getenv("PS3_VK_D24_CLAMP");   /* vk d24 clamp */
          s_dz_pipe = vk_eng_pipeline_create(user, s_lp_vs, (e && *e == '0') ? s_dz_ps_old : s_dz_ps, &rs, &lay, 16u, RSX_BE_FMT_R8G8B8A8, 1u); }''',
     "vk d24 clamp switch")

# vk mrt mask: targets 1-3 take COLOR_MASK_MRT (0x0370) and BLEND_ENABLE_MRT (0x036C), as the RSX does
# The Vulkan engine pipeline gave every attachment target A's blend and write mask. The real PS3
# (snap_004149, 2026-11-03 PS3MAPI capture) draws inFAMOUS 2's glass/decal materials into its 3-target
# G-buffer with blend on for A (SRC_ALPHA / ONE_MINUS_SRC_ALPHA), BLEND_ENABLE_MRT = 0 and
# COLOR_MASK_MRT = 0: they change the albedo only. Ours blended their output into the normals and
# material planes as well, so whatever lies under a transparent surface (Zeke's sunglass lenses, decals)
# was lit with the glass's normals/gloss. Now the Metal backend's rule (rsx_metal_backend.m, mode 1):
# nibble r of color_mask_mrt (bit 0 A, 1 R, 2 G, 3 B) and bit r of blend_mrt for target r > 0.
# PS3_VK_MRT_MASK=0: target A's state everywhere (old).
edit("libs/video/rsx_vulkan_backend.c",
     '''    VkPipelineColorBlendAttachmentState cba[RSX_BE_MAX_COLOR_TARGETS];
    for (u32 r = 0; r < P->rt_count; r++)
        cba[r] = (VkPipelineColorBlendAttachmentState){
            .blendEnable = rs->blend_enable ? VK_TRUE : VK_FALSE,''',
     '''    VkPipelineColorBlendAttachmentState cba[RSX_BE_MAX_COLOR_TARGETS];
    static int mrt_mask = -1;   /* vk mrt mask */
    if (mrt_mask < 0) { const char* e = getenv("PS3_VK_MRT_MASK"); mrt_mask = !(e && *e == '0'); }
    for (u32 r = 0; r < P->rt_count; r++) {
        VkColorComponentFlags twm = wm; int tblend = rs->blend_enable != 0;
        if (r > 0 && mrt_mask) {
            const u32 nib = (rs->color_mask_mrt >> (r * 4)) & 0xFu;
            twm = 0;
            if (nib & 1u) twm |= VK_COLOR_COMPONENT_A_BIT;
            if (nib & 2u) twm |= VK_COLOR_COMPONENT_R_BIT;
            if (nib & 4u) twm |= VK_COLOR_COMPONENT_G_BIT;
            if (nib & 8u) twm |= VK_COLOR_COMPONENT_B_BIT;
            tblend = (rs->blend_mrt >> r) & 1u;
        }
        cba[r] = (VkPipelineColorBlendAttachmentState){
            .blendEnable = tblend ? VK_TRUE : VK_FALSE,''',
     "vk mrt mask")
edit("libs/video/rsx_vulkan_backend.c",
     '''            .alphaBlendOp = vk_gcm_blend_op(rs->eq_a),
            .colorWriteMask = wm };
    VkPipelineColorBlendStateCreateInfo cb = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,
        .attachmentCount = P->rt_count, .pAttachments = cba };''',
     '''            .alphaBlendOp = vk_gcm_blend_op(rs->eq_a),
            .colorWriteMask = twm };   /* vk mrt mask */
    }
    VkPipelineColorBlendStateCreateInfo cb = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,
        .attachmentCount = P->rt_count, .pAttachments = cba };''',
     "vk mrt mask 2")

# gcm const engine only: with the draw engine on, constant data words skip the legacy rsx_process_method
# Every FIFO word went through two dispatchers: the draw engine (rsx_draw_engine_method ->
# rsx_dispatch_method) and the legacy state (rsx_process_method). The real PS3 frame
# (work/ps3_if2_20261103, frame.py) is mostly vertex-program constant uploads: 0x1EFC load slot then
# 0x1F00..0x1F7C data, ~4200 runs a frame. The legacy copy of those constants is read only by the
# vtable guest-draw path (rsx_vulkan_backend.c vk guest draw, D3D12), which is not used when the engine
# drives the backend. So with the engine on, a data word in 0x1F00..0x1F7C on subchannel 0 goes to the
# engine only. GCM_CONST_LEGACY=1: both, as before.
edit("libs/video/cellGcmSys.c",
     '''                    rsx_process_method(&s_state, m, dw);
                    /* NV406E_SET_REFERENCE: queue the fence value for PACED''',
     '''                    { static int legacy = -1;   /* gcm const engine only */
                      if (legacy < 0) { const char* e = getenv("GCM_CONST_LEGACY"); legacy = (e && *e == '1') || !rsx_draw_engine_enabled(); }
                      if (legacy || subch != 0 || m < 0x1F00u || m >= 0x1F80u)
                          rsx_process_method(&s_state, m, dw); }
                    /* NV406E_SET_REFERENCE: queue the fence value for PACED''',
     "gcm const engine only")

# icons ps5 default: on the PS5, "auto" button icons with no detected device are the PlayStation set
# The console run 2026-11-03 07:27 drew the prompt atlas in keyboard mode ("[button icons] prompt atlas
# found (mode keyboard)": mouse glyphs in "Hold [mouse] to aim"). The PS5 app sets
# PS3_BUTTON_ICONS=playstation, but with PS3_TOGGLE_FILE in env.txt the knob read back empty = auto,
# and auto with no SDL controller (the PS5 has none: cellPad reads the DualSense directly) resolved
# to KEYBOARD. On the PS5 there is no keyboard or mouse to follow: auto without a device = PlayStation.
edit("libs/video/rsx_button_icons.c",
     '''    static int headless = -1;
    if (headless < 0) { const char* hl = getenv("PS3RECOMP_METAL_HEADLESS"); headless = hl && *hl && *hl != '0'; }
    return headless ? PS3_ICONS_PLAYSTATION : PS3_ICONS_KEYBOARD;''',
     '''#if defined(__PROSPERO__)
    return PS3_ICONS_PLAYSTATION;   /* icons ps5 default: no keyboard/mouse on the console */
#endif
    static int headless = -1;
    if (headless < 0) { const char* hl = getenv("PS3RECOMP_METAL_HEADLESS"); headless = hl && *hl && *hl != '0'; }
    return headless ? PS3_ICONS_PLAYSTATION : PS3_ICONS_KEYBOARD;''',
     "icons ps5 default")
# eng passlog: PS3RECOMP_ENG_PASSLOG=<sec> -- DIAGNOSTIC: one world frame (> 2500 draws) after <sec> s, every
# render-target pass in order: colour A offset / format / clip size, zeta offset, clears, draws issued and
# draws drawn -- the same columns as work/ps3tools/frame.py prints for a real PS3 frame, to diff the two
# (inFAMOUS 1 glow/blur chain, 2026-11-03). Lines are buffered per frame; only a world frame is printed.
edit("libs/video/rsx_draw_engine.c",
     '''static void sink_end(void* user, const rsx_dispatch* r)
{
    (void)user; (void)r;
    if (!g.ready) return;
    if (++s_draw_serial == 0) s_draw_serial = 1;''',
     '''/* eng passlog */
static int s_pl_on = -1, s_pl_done, s_pl_rec; static long s_pl_sec; static unsigned long long s_pl_t0;
static char* s_pl_buf; static size_t s_pl_len; static u32 s_pl_key[4], s_pl_issued, s_pl_drawn, s_pl_clear, s_pl_n;
static int eng_pl_active(void)
{
    if (s_pl_on < 0) { const char* e = getenv("PS3RECOMP_ENG_PASSLOG"); s_pl_on = e ? 1 : 0; s_pl_sec = e ? atol(e) : 0;
        if (s_pl_on) s_pl_buf = (char*)malloc(1 << 20); if (!s_pl_buf) s_pl_on = 0; }
    return s_pl_on && s_pl_rec && !s_pl_done;   /* recording: armed at a frame end, so the frame is whole */
}
static void eng_pl_flush_pass(void)
{
    if (!s_pl_key[3] && !s_pl_issued && !s_pl_clear) return;
    if (s_pl_len + 256 < (1u << 20))
        s_pl_len += (size_t)snprintf(s_pl_buf + s_pl_len, 256, "== colorA 0x%x fmt 0x%x %ux%u zeta 0x%x%s%s draws %u (drawn %u)\\n",
            s_pl_key[0], s_pl_key[1], s_pl_key[2] >> 16, s_pl_key[2] & 0xFFFF, s_pl_key[3],
            s_pl_clear ? " CLEAR" : "", (s_pl_clear & 0xF0u) ? (s_pl_clear & 1u ? " color+z" : " color") : (s_pl_clear ? " z" : ""),
            s_pl_issued, s_pl_drawn);
    s_pl_n++; s_pl_issued = s_pl_drawn = s_pl_clear = 0;
}
static void eng_pl_note(int ev, u32 mask)   /* ev 0 draw issued, 1 drawn, 2 clear */
{
    if (!eng_pl_active()) return;
    rsx_dsp_surface sf; rsx_dsp_get_surface(&g.rsx, &sf);
    const u32 key[4] = { sf.color_offset[0], sf.color_format | (sf.depth_format << 8) | (sf.color_target << 16),
                         (sf.clip_w << 16) | (sf.clip_h & 0xFFFF), sf.zeta_offset };
    if (memcmp(key, s_pl_key, sizeof key) || (ev == 2 && s_pl_issued)) { eng_pl_flush_pass(); memcpy(s_pl_key, key, sizeof key); }
    if (ev == 0) s_pl_issued++; else if (ev == 1) s_pl_drawn++; else s_pl_clear |= mask;
}
static void eng_pl_frame_end(u32 frame_draws)
{
    if (s_pl_on < 0) (void)eng_pl_active();
    if (!s_pl_on || s_pl_done) return;
    if (!s_pl_rec) {
        extern unsigned long long ps3_ms_now(void);
        if (!s_pl_t0) s_pl_t0 = ps3_ms_now();
        if (ps3_ms_now() - s_pl_t0 >= (unsigned long long)s_pl_sec * 1000ull) s_pl_rec = 1;
        return;
    }
    eng_pl_flush_pass();
    if (frame_draws > 2500) {
        fprintf(stderr, "[passlog] frame %u: %u draws, %u passes\\n%.*s[passlog] end\\n", g.frames, frame_draws, s_pl_n, (int)s_pl_len, s_pl_buf);
        s_pl_done = 1;
    }
    s_pl_len = 0; s_pl_n = 0; memset(s_pl_key, 0, sizeof s_pl_key);
}

static void sink_end(void* user, const rsx_dispatch* r)
{
    (void)user; (void)r;
    if (!g.ready) return;
    if (s_pl_on) eng_pl_note(0, 0);
    if (++s_draw_serial == 0) s_draw_serial = 1;''',
     "eng passlog")
edit("libs/video/rsx_draw_engine.c",
     '''    if (!pipeline_is_fixed) g.guest_draws++;
    if (ds_t0) {''',
     '''    if (!pipeline_is_fixed) g.guest_draws++;
    if (s_pl_on) eng_pl_note(1, 0);   /* eng passlog */
    if (ds_t0) {''',
     "eng passlog drawn")
edit("libs/video/rsx_draw_engine.c",
     '''    u32 targets[RSX_BE_MAX_COLOR_TARGETS];
    const u32 n_targets = eng_current_target_set(targets);
    { static int cl = -1;''',
     '''    u32 targets[RSX_BE_MAX_COLOR_TARGETS];
    const u32 n_targets = eng_current_target_set(targets);
    if (s_pl_on) eng_pl_note(2, mask);   /* eng passlog */
    { static int cl = -1;''',
     "eng passlog clear")
edit("libs/video/rsx_draw_engine.c",
     '''    s_icon_gen = rsx_button_icons_frame();
    eng_ds_frame_end(g.guest_draws);''',
     '''    s_icon_gen = rsx_button_icons_frame();
    eng_pl_frame_end(g.guest_draws);   /* eng passlog */
    eng_ds_frame_end(g.guest_draws);''',
     "eng passlog frame")
# eng passlog dump: PS3RECOMP_ENG_PASSLOG_DIR=<dir> (with PS3RECOMP_ENG_PASSLOG) -- each pass's colour target A
# as it ends, read back to <dir>/p<NN>_<offset>_<w>x<h>.rgba (clip size, 4 bytes/pixel as the backend stores it),
# to compare with the same target in a real PS3 RSX local-memory dump. Every readback waits for the GPU: one frame.
edit("libs/video/rsx_draw_engine.c",
     '''static void eng_pl_flush_pass(void)
{
    if (!s_pl_key[3] && !s_pl_issued && !s_pl_clear) return;''',
     '''static u32 s_pl_handle;   /* eng passlog dump */
static void eng_pl_dump(void)
{
    static const char* dir = (const char*)-1;
    if (dir == (const char*)-1) dir = getenv("PS3RECOMP_ENG_PASSLOG_DIR");
    const u32 w = s_pl_key[2] >> 16, h = s_pl_key[2] & 0xFFFF;
    if (!dir || !s_pl_handle || !w || !h || !g.be->readback || !g.be->submit_and_wait) return;
    u8* px = (u8*)calloc((size_t)w * h, 4);
    if (!px) return;
    g.be->submit_and_wait(g.be->user, RSX_BE_FLUSH_GUEST_REFERENCE);
    g.be->readback(g.be->user, s_pl_handle, 0, 0, w, h, px, w * 4);
    char path[512]; snprintf(path, sizeof path, "%s/p%02u_%07x_%ux%u.rgba", dir, s_pl_n, s_pl_key[0], w, h);
    FILE* f = fopen(path, "wb"); if (f) { fwrite(px, 1, (size_t)w * h * 4, f); fclose(f); }
    free(px);
}
static void eng_pl_flush_pass(void)
{
    if (!s_pl_key[3] && !s_pl_issued && !s_pl_clear) return;
    eng_pl_dump();''',
     "eng passlog dump")
edit("libs/video/rsx_draw_engine.c",
     '''    if (memcmp(key, s_pl_key, sizeof key) || (ev == 2 && s_pl_issued)) { eng_pl_flush_pass(); memcpy(s_pl_key, key, sizeof key); }''',
     '''    if (memcmp(key, s_pl_key, sizeof key) || (ev == 2 && s_pl_issued)) { eng_pl_flush_pass(); memcpy(s_pl_key, key, sizeof key);
        const u32 slot = eng_current_surface(); s_pl_handle = slot == ENG_INVALID ? 0 : g.surfaces[slot].handle; }''',
     "eng passlog dump handle")
# spu unlifted lsdump: SPU_UNLIFTED_LSDUMP=<dir> -- DIAGNOSTIC: the first time each 16 KB LS page is branched into
# unlifted, the whole 256 KB local store to <dir>/ls_img<id>_ovl<ovl>_pc<pc>.bin, so code a job loads at run time
# can be found in guest memory/game files and lifted (inFAMOUS 1 rooftop: LS 0x31000-0x35000, 84% of interpreted steps).
edit("runtime/spu/spu_channels.c",
     '''            const char* e_iu = getenv("SPU_INTERP_UNLIFTED");
            int interp = !(e_iu && e_iu[0] == '0') && w0;''',
     '''            const char* e_iu = getenv("SPU_INTERP_UNLIFTED");
            int interp = !(e_iu && e_iu[0] == '0') && w0;
            { static const char* ud = (const char*)-1; static uint32_t pages;   /* spu unlifted lsdump */
              if (ud == (const char*)-1) ud = getenv("SPU_UNLIFTED_LSDUMP");
              const uint32_t bit = 1u << ((p0 >> 14) & 15);
              if (ud && !(__atomic_fetch_or(&pages, bit, __ATOMIC_ACQ_REL) & bit)) {
                  char path[512]; snprintf(path, sizeof path, "%s/ls_img%d_ovl%d_pc%05X.bin", ud, ctx->image_id, ctx->resident_ovl, p0);
                  FILE* f = fopen(path, "wb"); if (f) { fwrite(ctx->ls, 1, SPU_LS_SIZE, f); fclose(f); } } }''',
     "spu unlifted lsdump")
# spu reloc sig: position-independent job modules found by CONTENT at branch-in time (inFAMOUS 1, 2026-11-03).
# inFAMOUS 1's job 209 copies twelve small WWS job modules (EBOOT 0x670100-0x684100: 4 x ila signature, header,
# code at +0x30) into its own LS buffer wherever there is room (seen at 0x31000-0x35FFF) and calls into them;
# none was lifted, so on the rooftop 84% of all interpreted SPU steps were theirs, and the interpreter's
# per-step lifted lookup was the hottest SPU leaf. They are lifted at LS 0 --relocatable
# (tools/lift_if1_plugmods.py) and registered with spu_overlay_register_reloc_sig. When dispatch finds no lift
# at pc, spu_reloc_sig_adopt looks back from pc for a registered signature at a 16-byte boundary, checks the
# module's code bytes against its EBOOT copy, and makes the lift resident there as a relocatable code slot
# (source_ea = the module, so the per-dispatch stale-word check still guards it). PS3_SPU_RELOC_SIG=0 = off.
edit("runtime/spu/spu_channels.c",
     '''/* Register one-way runtime entries that replace the guest call stack.''',
     '''/* spu reloc sig */
typedef struct { uint8_t sig[16]; uint32_t sig_off, ea, span, code_len; int image_id; } spu_rsig;
static spu_rsig s_rsig[32];
static int s_rsig_n;
/* sig = the module's 16 bytes at sig_off: job 209 copies from the code (+0x30), not the header. */
void spu_overlay_register_reloc_sig(const uint8_t sig[16], uint32_t sig_off, uint32_t content_ea, uint32_t span, uint32_t code_len, int image_id)
{
    if (s_rsig_n >= 32 || image_id <= 0 || image_id >= 4096 || sig_off + 16 > code_len) return;
    memcpy(s_rsig[s_rsig_n].sig, sig, 16); s_rsig[s_rsig_n].sig_off = sig_off;
    s_rsig[s_rsig_n].ea = content_ea; s_rsig[s_rsig_n].span = span;
    s_rsig[s_rsig_n].code_len = code_len < span ? code_len : span; s_rsig[s_rsig_n].image_id = image_id;
    s_rsig_n++;
    s_reloc_img[image_id] = 1;
    __atomic_add_fetch(&g_spu_reg_gen, 1, __ATOMIC_RELEASE);
}
/* Returns the slot + 1 the module covering pc was made resident in, or 0. */
int spu_reloc_sig_adopt(spu_context* ctx, uint32_t pc)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3_SPU_RELOC_SIG"); on = !(e && e[0] == '0'); }
    if (!on || !s_rsig_n || !ctx->ls) return 0;
    pc &= SPU_LS_MASK;
    const uint32_t lo = pc > 0x8000u ? pc - 0x8000u : 0u;
    for (uint32_t pos = pc & ~15u; ; pos -= 16) {
        uint32_t w; memcpy(&w, ctx->ls + pos, 4);
        for (int i = 0; i < s_rsig_n; i++) {
            const spu_rsig* r = &s_rsig[i];
            uint32_t sw; memcpy(&sw, r->sig, 4);
            if (w != sw || pos < r->sig_off || memcmp(ctx->ls + pos, r->sig, 16)) continue;
            const uint32_t base = pos - r->sig_off;   /* the module's offset 0, where its lift's addresses start */
            if (pc - base >= r->span || base + r->code_len > SPU_LS_SIZE) continue;
            if (!gm_equal(vm_base + r->ea + r->sig_off + 16, ctx->ls + pos + 16, r->code_len - r->sig_off - 16)) continue;
            unsigned pick = SPU_RESIDENT_CODE_SLOTS;
            for (unsigned s = 0; s < SPU_RESIDENT_CODE_SLOTS; ++s)   /* same place first, then a free one */
                if (ctx->resident_code[s].image_id && ctx->resident_code[s].lsa == base) { pick = s; break; }
            for (unsigned s = 0; s < SPU_RESIDENT_CODE_SLOTS && pick == SPU_RESIDENT_CODE_SLOTS; ++s)
                if (!ctx->resident_code[s].image_id) pick = s;
            for (unsigned s = 0; s < SPU_RESIDENT_CODE_SLOTS && pick == SPU_RESIDENT_CODE_SLOTS; ++s)   /* else another adopted module */
                for (int k = 0; k < s_rsig_n; k++) if (ctx->resident_code[s].image_id == s_rsig[k].image_id) { pick = s; break; }
            if (pick == SPU_RESIDENT_CODE_SLOTS) return 0;
            /* an adopted module overlapping this one is gone (its bytes were overwritten) */
            for (unsigned s = 0; s < SPU_RESIDENT_CODE_SLOTS; ++s)
                if (s != pick && ctx->resident_code[s].image_id && ctx->resident_code[s].reloc &&
                    ctx->resident_code[s].lsa < base + r->span && base < ctx->resident_code[s].lsa + ctx->resident_code[s].size)
                    ctx->resident_code[s].image_id = 0;
            ctx->resident_code[pick].lsa = base; ctx->resident_code[pick].size = r->span;
            ctx->resident_code[pick].source_ea = r->ea; ctx->resident_code[pick].image_id = r->image_id;
            ctx->resident_code[pick].reloc = 1;
            ctx->ib_gen++;
            { static int _n = 0; if (PS3_LOG_FIRST(_n, 16))
                fprintf(stderr, "[spu-ovl] img=%d reloc sig: module ea=0x%08X resident at LS 0x%05X+0x%X as image %d (slot %u, pc 0x%05X)\\n",
                        ctx->image_id, r->ea, base, r->span, r->image_id, pick, pc); }
            return (int)pick + 1;
        }
        if (pos <= lo || pos < 16) return 0;
    }
}

/* Register one-way runtime entries that replace the guest call stack.''',
     "spu reloc sig")
edit("runtime/spu/spu_channels.c",
     '''    for (unsigned slot = 0; slot < SPU_RESIDENT_CODE_SLOTS && !fn && code_owner >= 0; ++slot)
        if (ctx->resident_code[slot].image_id && !ctx->resident_code[slot].reloc)
            fn = spu_lookup(ctx->pc, ctx->resident_code[slot].image_id);
    /* The job returned through the link register we planted: it is finished.''',
     '''    for (unsigned slot = 0; slot < SPU_RESIDENT_CODE_SLOTS && !fn && code_owner >= 0; ++slot)
        if (ctx->resident_code[slot].image_id && !ctx->resident_code[slot].reloc)
            fn = spu_lookup(ctx->pc, ctx->resident_code[slot].image_id);
    if (!fn && code_owner >= 0) {   /* spu reloc sig: a position-independent module copied here */
        extern int spu_reloc_sig_adopt(spu_context*, uint32_t);
        const int s1 = spu_reloc_sig_adopt(ctx, ctx->pc);
        if (s1 && (fn = spu_lookup(ctx->pc - ctx->resident_code[s1 - 1].lsa, ctx->resident_code[s1 - 1].image_id)))
            ctx->code_base = ctx->resident_code[s1 - 1].lsa;
    }
    /* The job returned through the link register we planted: it is finished.''',
     "spu reloc sig adopt")
# spu interp lsdump: SPU_INTERP_LSDUMP=<dir>:<lo hex>:<hi hex> -- DIAGNOSTIC: the first 4 times the interpreter steps
# at a pc in [lo, hi) (one every 2^24 such steps), the whole local store to <dir>/interp_<n>_pc<pc>_img<id>_ovl<ovl>.bin,
# to identify the code a job runs there that nothing lifted (inFAMOUS 1 rooftop: LS 0x31000-0x34FFF).
edit("runtime/spu/spu_interp.c",
     '''        /* SPU_INTERP_WHERE=<n>: every n interpreted steps (all SPUs), print the''',
     '''        { static const char* d = (const char*)-1; static uint32_t lo, hi; static _Atomic unsigned long long cnt; static _Atomic int nd;   /* spu interp lsdump */
          if (d == (const char*)-1) { const char* e = getenv("SPU_INTERP_LSDUMP"); d = 0;
              if (e) { static char dir[400]; const char* c = strchr(e, ':');
                  if (c && (size_t)(c - e) < sizeof dir) { memcpy(dir, e, (size_t)(c - e)); dir[c - e] = 0; d = dir;
                      lo = (uint32_t)strtoul(c + 1, (char**)&c, 16); hi = (*c == ':') ? (uint32_t)strtoul(c + 1, 0, 16) : lo + 0x1000; } } }
          if (d && _tpc >= lo && _tpc < hi && nd < 4 && (cnt++ & ((1ull << 24) - 1)) == 0) {
              int k = nd++; char path[512];
              snprintf(path, sizeof path, "%s/interp_%d_pc%05X_img%d_ovl%d.bin", d, k, _tpc, ctx->image_id, ctx->resident_ovl);
              FILE* f = fopen(path, "wb"); if (f) { fwrite(ctx->ls, 1, SPU_LS_SIZE, f); fclose(f); } } }
        /* SPU_INTERP_WHERE=<n>: every n interpreted steps (all SPUs), print the''',
     "spu interp lsdump")
# spu reloc sig fast: (1) the indirect-branch fast path adopts too (job 209's lifted code calls the modules through
# bisl; that path went straight to the interpreter on a miss, so the first version adopted almost nothing and its
# scan, run on every drain-path miss, cost 28% of the run: rooftop 15.5 -> 11.8 fps); (2) the scan is cheap: window =
# the largest registered span, a 1024-bit prefilter on each candidate word, and a 512-entry negative cache keyed by
# (pc, the two words at pc) -- a stale entry can only mean interpreting, never running the wrong lift.
edit("runtime/spu/spu_channels.c",
     '''int spu_reloc_sig_adopt(spu_context* ctx, uint32_t pc)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3_SPU_RELOC_SIG"); on = !(e && e[0] == '0'); }
    if (!on || !s_rsig_n || !ctx->ls) return 0;
    pc &= SPU_LS_MASK;
    const uint32_t lo = pc > 0x8000u ? pc - 0x8000u : 0u;
    for (uint32_t pos = pc & ~15u; ; pos -= 16) {
        uint32_t w; memcpy(&w, ctx->ls + pos, 4);
        for (int i = 0; i < s_rsig_n; i++) {''',
     '''static uint64_t s_rsig_bits[16]; static uint32_t s_rsig_maxspan;   /* spu reloc sig fast */
static struct { uint32_t pc, w0, w1; } s_rsig_neg[512];
static inline unsigned rsig_h(uint32_t w) { return (w * 2654435761u) >> 22; }
int spu_reloc_sig_adopt(spu_context* ctx, uint32_t pc)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3_SPU_RELOC_SIG"); on = !(e && e[0] == '0'); }
    if (!on || !s_rsig_n || !ctx->ls) return 0;
    pc &= SPU_LS_MASK;
    if (pc + 8 > SPU_LS_SIZE) return 0;
    if (!s_rsig_maxspan) {   /* registration is done before any SPU runs */
        for (int i = 0; i < s_rsig_n; i++) { uint32_t sw; memcpy(&sw, s_rsig[i].sig, 4);
            const unsigned h = rsig_h(sw); s_rsig_bits[h >> 6] |= 1ull << (h & 63);
            if (s_rsig[i].span > s_rsig_maxspan) s_rsig_maxspan = s_rsig[i].span; } }
    uint32_t w0, w1; memcpy(&w0, ctx->ls + pc, 4); memcpy(&w1, ctx->ls + pc + 4, 4);
    const unsigned nk = ((pc >> 2) ^ w0) & 511u;
    if (s_rsig_neg[nk].pc == pc && s_rsig_neg[nk].w0 == w0 && s_rsig_neg[nk].w1 == w1) return 0;
    const uint32_t lo = pc > s_rsig_maxspan ? pc - s_rsig_maxspan : 0u;
    for (uint32_t pos = pc & ~15u; ; pos -= 16) {
        uint32_t w; memcpy(&w, ctx->ls + pos, 4);
        { const unsigned h = rsig_h(w);
          if (!((s_rsig_bits[h >> 6] >> (h & 63)) & 1)) { if (pos <= lo || pos < 16) break; continue; } }
        for (int i = 0; i < s_rsig_n; i++) {''',
     "spu reloc sig fast: scan")
edit("runtime/spu/spu_channels.c",
     '''            return (int)pick + 1;
        }
        if (pos <= lo || pos < 16) return 0;
    }
}''',
     '''            return (int)pick + 1;
        }
        if (pos <= lo || pos < 16) break;
    }
    s_rsig_neg[nk].pc = pc; s_rsig_neg[nk].w0 = w0; s_rsig_neg[nk].w1 = w1;
    return 0;
}''',
     "spu reloc sig fast: negative cache")
edit("runtime/spu/spu_channels.c",
     '''        if (!fn && (fn = spu_lazy_ovl_adopt(ctx, pc))) stale_seen = 1;   /* not cached: ovl changed */''',
     '''        if (!fn && (fn = spu_lazy_ovl_adopt(ctx, pc))) stale_seen = 1;   /* not cached: ovl changed */
        if (!fn && code_owner >= 0) {   /* spu reloc sig fast: a module job 209 copied here, called through bisl */
            extern int spu_reloc_sig_adopt(spu_context*, uint32_t);
            const int s1 = spu_reloc_sig_adopt(ctx, pc);
            if (s1 && (fn = spu_lookup(pc - ctx->resident_code[s1 - 1].lsa, ctx->resident_code[s1 - 1].image_id))) {
                ctx->code_base = ctx->resident_code[s1 - 1].lsa; stale_seen = 1; }
        }''',
     "spu reloc sig fast: indirect branch")
# spu reloc sig interp: the interpreter adopts as well, at every taken branch (pc != previous + 4). Job 209 calls the
# modules from its own unlifted code too (its LS 0xE000 page runs interpreted), and the interpreter follows those
# calls by itself: neither dispatch hook ever saw them, so modules 331/334 at LS 0x30F30.. stayed interpreted.
edit("runtime/spu/spu_interp.c",
     '''    uint32_t ring[64]; int rc=0, rn=0;
    for (;;) {''',
     '''    uint32_t ring[64]; int rc=0, rn=0;
    uint32_t _ra_prev = ~0u;   /* spu reloc sig interp */
    for (;;) {
        if (ctx->pc != _ra_prev + 4u && ctx->image_id >= 0) {
            extern int spu_reloc_sig_adopt(spu_context*, uint32_t);
            (void)spu_reloc_sig_adopt(ctx, ctx->pc);
        }
        _ra_prev = ctx->pc;''',
     "spu reloc sig interp")

# timer absolute: periodic lv2 timers (sys_timer_start) fire on a fixed schedule instead of drifting.
# The POSIX timer thread waited "now + period" after handling each tick, so every tick ran late by the
# wake-up latency plus the event push, and the error added up: the timer ran slower than real time by
# that latency every period. inFAMOUS 1's sound driver (brbDriver, queue 9, src 0 d1 0) is woken by such
# a timer and refills its 8-block cellAudio port from it; the cellAudio consumer runs on the device
# clock. On the PS5 (larger wake latency under load) the driver fell a whole ring behind again and
# again: the console recording (work/live/if1_live_1103_audio) has ~1250 exact-silence gaps in 10 min,
# 743 of them exactly 8 blocks (42.7 ms) long = the user's "distorted audio". Now deadline += period,
# resynced only when more than 100 ms behind (a debugger stop). One "[timer] start" line per start.
# PS3_TIMER_ABS=0 = the old relative wait.
edit("runtime/syscalls/sys_timer.c",
     '''    pthread_mutex_lock(&t->mtx);
    while (!t->stop_flag) {
        struct timespec ts;
        clock_gettime(CLOCK_REALTIME, &ts);
        ts.tv_sec  += (time_t)(t->period_usec / 1000000);
        ts.tv_nsec += (long)((t->period_usec % 1000000) * 1000);
        if (ts.tv_nsec >= 1000000000L) {
            ts.tv_sec++;
            ts.tv_nsec -= 1000000000L;
        }
''',
     '''    pthread_mutex_lock(&t->mtx);
    /* timer absolute: a fixed schedule (deadline += period), not "now + period" after each tick */
    static int s_abs = -1;
    if (s_abs < 0) { const char* e = getenv("PS3_TIMER_ABS"); s_abs = (e && *e == '0') ? 0 : 1; }
    struct timespec next;
    clock_gettime(CLOCK_REALTIME, &next);
    while (!t->stop_flag) {
        struct timespec ts;
        if (s_abs) {
            next.tv_sec  += (time_t)(t->period_usec / 1000000);
            next.tv_nsec += (long)((t->period_usec % 1000000) * 1000);
            if (next.tv_nsec >= 1000000000L) { next.tv_sec++; next.tv_nsec -= 1000000000L; }
            struct timespec now;
            clock_gettime(CLOCK_REALTIME, &now);
            const long long late_us = (long long)(now.tv_sec - next.tv_sec) * 1000000LL
                                    + (now.tv_nsec - next.tv_nsec) / 1000;
            if (late_us > 100000) next = now;   /* far behind (a debugger stop): start over from now */
            ts = next;
        } else {
        clock_gettime(CLOCK_REALTIME, &ts);
        ts.tv_sec  += (time_t)(t->period_usec / 1000000);
        ts.tv_nsec += (long)((t->period_usec % 1000000) * 1000);
        if (ts.tv_nsec >= 1000000000L) {
            ts.tv_sec++;
            ts.tv_nsec -= 1000000000L;
        }
        }
''',
     "timer absolute")
edit("runtime/syscalls/sys_timer.c",
     '''    t->period_usec = period;
    t->running     = 1;
''',
     '''    t->period_usec = period;
    t->running     = 1;
    printf("[timer] start id=%u period=%llu us queue=%d\\n", timer_id,   /* timer absolute */
           (unsigned long long)period, (int)t->event_queue_id);
''',
     "timer absolute log")

# audio hold: wait for a late guest block instead of playing it as silence (POSIX mixer loop).
# The mixer consumed one block per 5.33 ms of device time whether or not the title had written it,
# and zeroed it after. When the title's sound driver ran late (inFAMOUS 1's brbDriver, woken by a
# 5.33 ms lv2 timer), every block it had not written yet became silence: the console recording
# (work/live/if1_live_1103_audio) has ~1250 exact-silence gaps in 10 min, 743 of them a whole
# 8-block ring. Now, when every running port's next block is still all zero right after a block that
# had sound, the mixer holds the read index while the host queue still has more than
# PS3_AUDIO_HOLD_MIN blocks (default 2) to play; the reserve covers the wait. One hold per silent run
# (real silence costs one reserve's worth of delay, once). The host queue target is
# PS3_AUDIO_QUEUE blocks (default 8 on the PS5 = 43 ms, 4 elsewhere as before).
# PS3_AUDIO_HOLD=0 = off (default on on the PS5, off elsewhere; PS3_AUDIO_HOLD=1 turns it on).
edit("libs/audio/cellAudio.c",
     '''static void audio_mix_one_block(void)
{''',
     '''/* audio hold: is the next block of every running port still all zero (not written yet)?
 * 0 when no port is running. */
static int s_audio_last_had_data;
static int audio_next_blocks_empty(void)
{
    int running = 0;
    mutex_lock(&s_audio_mutex);
    for (int p = 0; p < CELL_AUDIO_PORT_MAX; p++) {
        AudioPortSlot* port = &s_ports[p];
        if (!port->in_use || !port->running || !port->buffer) continue;
        const u32 nch = (u32)port->param.nChannel, nblock = (u32)port->param.nBlock;
        if (!nblock) continue;
        running = 1;
        const u32* w = (const u32*)(port->buffer + (u32)(port->read_index % nblock) * CELL_AUDIO_BLOCK_SAMPLES * nch);
        for (u32 i = 0; i < CELL_AUDIO_BLOCK_SAMPLES * nch; i++)
            if (w[i]) { mutex_unlock(&s_audio_mutex); return 0; }
    }
    mutex_unlock(&s_audio_mutex);
    return running;
}

static void audio_mix_one_block(void)
{''',
     "audio hold helper")
edit("libs/audio/cellAudio.c",
     '''    /* Clip to [-1.0, 1.0] */
    for (u32 i = 0; i < CELL_AUDIO_BLOCK_SAMPLES * 2; i++) {
        if (s_mix_buffer[i] > 1.0f) s_mix_buffer[i] = 1.0f;
        if (s_mix_buffer[i] < -1.0f) s_mix_buffer[i] = -1.0f;
    }
}''',
     '''    /* Clip to [-1.0, 1.0] */
    int had = 0;   /* audio hold */
    for (u32 i = 0; i < CELL_AUDIO_BLOCK_SAMPLES * 2; i++) {
        if (s_mix_buffer[i] > 1.0f) s_mix_buffer[i] = 1.0f;
        if (s_mix_buffer[i] < -1.0f) s_mix_buffer[i] = -1.0f;
        if (s_mix_buffer[i] != 0.0f) had = 1;
    }
    s_audio_last_had_data = had;
}''',
     "audio hold track")
edit("libs/audio/cellAudio.c",
     '''    struct timespec t0; clock_gettime(CLOCK_MONOTONIC, &t0);
    unsigned long long mixed = 0;
    while (s_mix_thread_running) {
        struct timespec now; clock_gettime(CLOCK_MONOTONIC, &now);
        unsigned long long el_us = (unsigned long long)(now.tv_sec - t0.tv_sec) * 1000000ull
                                 + (unsigned long long)((now.tv_nsec - t0.tv_nsec) / 1000);
        unsigned long long ahead_us = mixed * CELL_AUDIO_BLOCK_SAMPLES * 1000000ull / 48000ull;
        if (audio_backend_queued_samples() >= CELL_AUDIO_BLOCK_SAMPLES * 4 ||
            ahead_us > el_us + 4ull * CELL_AUDIO_BLOCK_SAMPLES * 1000000ull / 48000ull) {
            usleep(1000);
            continue;
        }
        mixed++;''',
     '''    struct timespec t0; clock_gettime(CLOCK_MONOTONIC, &t0);
    unsigned long long mixed = 0;
    /* audio hold: queue target and hold settings (see tools/patch_audio_hold.py) */
#if defined(__PROSPERO__)
    int hold_on = 1; unsigned qblocks = 8;
#else
    int hold_on = 0; unsigned qblocks = 4;
#endif
    { const char* e = getenv("PS3_AUDIO_HOLD"); if (e && *e) hold_on = *e != '0';
      e = getenv("PS3_AUDIO_QUEUE"); if (e && atoi(e) >= 2 && atoi(e) <= 24) qblocks = (unsigned)atoi(e); }
    unsigned hold_min = 2;
    { const char* e = getenv("PS3_AUDIO_HOLD_MIN"); if (e && atoi(e) >= 0 && (unsigned)atoi(e) < qblocks) hold_min = (unsigned)atoi(e); }
    printf("[cellAudio] host queue %u blocks, hold %s (min %u)\\n", qblocks, hold_on ? "on" : "off", hold_min);
    int held = 0;                          /* this silent run was already waited for */
    unsigned long long n_hold = 0, n_hold_ok = 0, n_hold_gaveup = 0;
    struct timespec tr; clock_gettime(CLOCK_MONOTONIC, &tr);
    while (s_mix_thread_running) {
        struct timespec now; clock_gettime(CLOCK_MONOTONIC, &now);
        unsigned long long el_us = (unsigned long long)(now.tv_sec - t0.tv_sec) * 1000000ull
                                 + (unsigned long long)((now.tv_nsec - t0.tv_nsec) / 1000);
        unsigned long long ahead_us = mixed * CELL_AUDIO_BLOCK_SAMPLES * 1000000ull / 48000ull;
        if (audio_backend_queued_samples() >= CELL_AUDIO_BLOCK_SAMPLES * qblocks ||
            ahead_us > el_us + (unsigned long long)qblocks * CELL_AUDIO_BLOCK_SAMPLES * 1000000ull / 48000ull) {
            usleep(1000);
            continue;
        }
        if (hold_on && s_audio_last_had_data && audio_next_blocks_empty()) {
            if (!held) { held = 1; n_hold++; }
            if (audio_backend_queued_samples() > CELL_AUDIO_BLOCK_SAMPLES * hold_min) {
                usleep(500);               /* the title is late: let the reserve play while it writes */
                continue;
            }
            n_hold_gaveup++;               /* reserve used up: play it as silence */
        } else if (held && s_audio_last_had_data) {
            n_hold_ok++;                   /* the block arrived during the wait */
        }
        if (!hold_on || !s_audio_last_had_data || !audio_next_blocks_empty()) held = 0;
        if (hold_on && now.tv_sec - tr.tv_sec >= 30) {
            tr = now;
            printf("[cellAudio] hold: %llu late blocks waited for, %llu arrived in time, %llu played as silence\\n",
                   n_hold, n_hold_ok, n_hold_gaveup);
        }
        mixed++;''',
     "audio hold loop")

# remap scan vec: rsx_vertex_remap_build_range's min/max scan without the early exit, so clang
# vectorises it (AVX2). The loop returned inside on a base_index mismatch, which kept it scalar: one
# cmov chain per reference, ~70% of the function's samples (perf annotate, crater run cr1), and the
# function was 6.5 ms of the RSX thread's ~65 ms frame there (PS3RECOMP_ENG_DRAWSTATS, run ds1:
# 4.26 M references a frame). Same result: a mismatch anywhere still returns 0, after the scan.
edit("libs/video/rsx_vertex_compact.c",
     '''    const u32 base = refs[0].base_index;
    u32 lo = refs[0].vertex_id, hi = lo;
    for (u32 i = 1; i < count; i++) {
        const u32 v = refs[i].vertex_id;
        if (refs[i].base_index != base) return 0;
        if (v < lo) lo = v;
        if (v > hi) hi = v;
    }
    const u64 span = (u64)hi - lo + 1u;''',
     '''    const u32 base = refs[0].base_index;
    u32 lo = refs[0].vertex_id, hi = lo, diff = 0;
    for (u32 i = 1; i < count; i++) {   /* remap scan vec: no early exit, so it vectorises */
        const u32 v = refs[i].vertex_id;
        diff |= refs[i].base_index ^ base;
        lo = v < lo ? v : lo;
        hi = v > hi ? v : hi;
    }
    if (diff) return 0;
    const u64 span = (u64)hi - lo + 1u;''',
     "remap scan vec")

# vc sparse: cheaper content checks for vertex-cache entries that already draw from a cached buffer.
# Every draw hashed its whole vertex spans (eng_hash_span) even when 99% of draws hit the cache:
# crater (run ds1, PS3RECOMP_ENG_DRAWSTATS): 13,322 hits / 136 misses a frame, 28.8 MB hashed in
# 4.2 ms of the RSX thread's ~65 ms -- and the same mesh is hashed again for each shadow cascade.
# Now, for an entry with a cached buffer whose bytes matched on its last full check:
#   - a second probe of the key in the same frame reuses that frame's hash;
#   - after 4 matching full checks, frames other than every 8th (staggered by key) take a sampled
#     hash (64 bytes of every 2 KB + the last 64 of each span, as eng_texture_sparse_hash); equal
#     to the sampled hash of the last full check = unchanged; different = full hash as before.
# A rewrite of a stable mesh is seen at once if it touches a sampled block, else within 8 frames.
# PS3RECOMP_ENG_VCACHE_SPARSE=0 = full hash on every probe (old).
edit("libs/video/rsx_draw_engine.c",
     '''typedef struct {
    u64 key, content;
    u32 vbuf, bytes, n, stride;
    u32 last_frame, seen_frame, skip_until;
    u8 seen, changes;
} eng_vc_entry;''',
     '''typedef struct {
    u64 key, content;
    u32 vbuf, bytes, n, stride;
    u32 last_frame, seen_frame, skip_until;
    u8 seen, changes;
    u8 stable;              /* vc sparse: full checks in a row that matched */
    u32 hashed_frame;       /* vc sparse: frame of the last hash, + 1 (0 = none) */
    u64 frame_hash, sparse; /* vc sparse: that hash; sampled hash at the last full check */
} eng_vc_entry;''',
     "vc sparse struct")
edit("libs/video/rsx_draw_engine.c",
     '''    u64 c = 0x51ED270B27A3F5E1ull;
    for (u32 i = 0; i < nr; ) {
        const u8* a0 = lo[i]; const u8* a1 = hi[i];
        for (i++; i < nr && lo[i] <= a1 + 64; i++) if (hi[i] > a1) a1 = hi[i];
        c = eng_hash_span(a0, (u64)(a1 - a0), c);
        ds_vc_hashed += (u64)(a1 - a0);
    }
    *content = c;
    return e;
}''',
     '''    /* vc sparse: merge the spans once; sampled / same-frame checks for settled entries */
    const u8* m0[RSX_DSP_NUM_VERTEX_ATTR]; const u8* m1[RSX_DSP_NUM_VERTEX_ATTR];
    u32 nm = 0;
    for (u32 i = 0; i < nr; ) {
        const u8* a0 = lo[i]; const u8* a1 = hi[i];
        for (i++; i < nr && lo[i] <= a1 + 64; i++) if (hi[i] > a1) a1 = hi[i];
        m0[nm] = a0; m1[nm] = a1; nm++;
    }
    static int s_sp = -1;
    if (s_sp < 0) { const char* ev = getenv("PS3RECOMP_ENG_VCACHE_SPARSE"); s_sp = (ev && *ev == '0') ? 0 : 1; }
    const int settled = s_sp && e->vbuf && e->seen && e->stable >= 1;
    if (settled && e->hashed_frame == g.frames + 1u) {   /* already checked this frame */
        *content = e->frame_hash;
        return e;
    }
    u64 sp = 0x6A09E667F3BCC908ull;
    for (u32 i = 0; i < nm; i++) {
        const u8* a0 = m0[i]; const u64 n = (u64)(m1[i] - a0);
        if (n < 64) { for (u64 j = 0; j < n; j++) { sp ^= a0[j]; sp *= 1099511628211ull; } continue; }
        for (u64 j = 0; j + 64 <= n; j += 2048) {
            u64 w[8]; memcpy(w, a0 + j, sizeof w);
            for (int k = 0; k < 8; k++) sp = (sp ^ w[k]) * 1099511628211ull;
        }
        { u64 w[8]; memcpy(w, a0 + n - 64, sizeof w);
          for (int k = 0; k < 8; k++) sp = (sp ^ w[k]) * 1099511628211ull; }
        sp ^= n;
    }
    if (settled && e->stable >= 4 && ((g.frames + (u32)key) & 7u) != 0 && sp == e->sparse) {
        e->hashed_frame = g.frames + 1u; e->frame_hash = e->content;
        *content = e->content;
        return e;
    }
    u64 c = 0x51ED270B27A3F5E1ull;
    for (u32 i = 0; i < nm; i++) {
        c = eng_hash_span(m0[i], (u64)(m1[i] - m0[i]), c);
        ds_vc_hashed += (u64)(m1[i] - m0[i]);
    }
    if (e->seen && c == e->content) { if (e->stable < 255) e->stable++; }
    else e->stable = 0;
    e->sparse = sp;
    e->hashed_frame = g.frames + 1u; e->frame_hash = c;
    *content = c;
    return e;
}''',
     "vc sparse probe")

# audio raw8 (diagnostic): AUDIO_RAW8=<file> appends every mixed block of port 0 as the title wrote
# it, before the downmix: f32le, nChannel interleaved (8 for inFAMOUS 1), 48 kHz. For checking which
# channel holds what (the console's stereo image leans right; our BC-250 mix has L/R correlation 0.04
# where the real PS3's is 0.7-0.8). Off by default.
edit("libs/audio/cellAudio.c",
     '''        for (u32 s = 0; s < CELL_AUDIO_BLOCK_SAMPLES; s++) {
            float left, right;''',
     '''        if (p == 0) {   /* audio raw8 */
            static FILE* rf = (FILE*)-1;
            if (rf == (FILE*)-1) { const char* e = getenv("AUDIO_RAW8"); rf = e ? fopen(e, "wb") : NULL; }
            if (rf) { float tmp[CELL_AUDIO_BLOCK_SAMPLES * 8];
                      const u32 nn = CELL_AUDIO_BLOCK_SAMPLES * (nch < 8 ? nch : 8);
                      for (u32 k = 0; k < nn; k++) tmp[k] = ld_be_f32(&src[k]);
                      fwrite(tmp, sizeof(float), nn, rf); }
        }
        for (u32 s = 0; s < CELL_AUDIO_BLOCK_SAMPLES; s++) {
            float left, right;''',
     "audio raw8")

# audio out ch: PS3_AUDIO_OUT_CH=2|6|8 caps the LPCM channel count the audio-output queries report
# (cellAudioOutGetSoundAvailability/2, cellAudioOutGetDeviceInfo's mode list). Unset = as before
# (2/5.1/7.1 listed, 5.1 available). The host is stereo: a title told 5.1/7.1 exists places its
# sounds for surround speakers, and our fixed 7.1 -> stereo fold (rear 0.5, side 0.3) loses most
# of the side and rear placement. inFAMOUS 1's raw port data (AUDIO_RAW8, run raw1) is a 5.1 mix
# (ch 2 dialog, ch 4/5 surround, ch 6/7 silent); the console's stereo image leans right (L-R
# balance p10 -9.2 dB vs -1.8/-4.6 on the real PS3 capture) and the user hears left sounds only
# when far left. The real PS3 capture went over HDMI to a stereo capture card: stereo LPCM.
# Also logs the configuration the title asks cellAudioOutConfigure for.
edit("libs/misc/cellAvconfExt.c",
     '''s32 cellAudioOutGetSoundAvailability(u32 audioOut, u32 type, u32 fs, u32 option)
{
    (void)audioOut;
    (void)option;
''',
     '''/* audio out ch: PS3_AUDIO_OUT_CH caps the LPCM channels reported (0 = unset, as before) */
static int audio_out_ch_cap(void)
{
    static int cap = -1;
    if (cap < 0) { const char* e = getenv("PS3_AUDIO_OUT_CH"); cap = e ? atoi(e) : 0;
                   if (cap != 2 && cap != 6 && cap != 8) cap = 0;
                   if (cap) printf("[cellAvconfExt] PS3_AUDIO_OUT_CH=%d: audio output reported as %d channels\\n", cap, cap); }
    return cap;
}

s32 cellAudioOutGetSoundAvailability(u32 audioOut, u32 type, u32 fs, u32 option)
{
    (void)audioOut;
    (void)option;
    if (audio_out_ch_cap()) {   /* audio out ch */
        printf("[cellAvconfExt] GetSoundAvailability(type=%u fs=0x%X) -> %d\\n", type, fs,
               type == CELL_AUDIO_OUT_CODING_TYPE_LPCM && (fs & CELL_AUDIO_OUT_FS_48KHZ) ? audio_out_ch_cap() : 0);
        return type == CELL_AUDIO_OUT_CODING_TYPE_LPCM && (fs & CELL_AUDIO_OUT_FS_48KHZ) ? audio_out_ch_cap() : 0;
    }
''',
     "audio out ch avail")
edit("libs/misc/cellAvconfExt.c",
     '''    if (type == CELL_AUDIO_OUT_CODING_TYPE_LPCM &&
        (fs & CELL_AUDIO_OUT_FS_48KHZ) &&
        (ch == CELL_AUDIO_OUT_CHNUM_2 || ch == CELL_AUDIO_OUT_CHNUM_6 || ch == CELL_AUDIO_OUT_CHNUM_8))
        return 1; /* available */''',
     '''    if (type == CELL_AUDIO_OUT_CODING_TYPE_LPCM &&
        (fs & CELL_AUDIO_OUT_FS_48KHZ) &&
        (ch == CELL_AUDIO_OUT_CHNUM_2 || ch == CELL_AUDIO_OUT_CHNUM_6 || ch == CELL_AUDIO_OUT_CHNUM_8) &&
        (!audio_out_ch_cap() || (int)ch <= audio_out_ch_cap()))   /* audio out ch */
        return 1; /* available */''',
     "audio out ch avail2")
edit("libs/misc/cellAvconfExt.c",
     '''    info->availableModes[2].fs      = CELL_AUDIO_OUT_FS_48KHZ;

    return CELL_OK;''',
     '''    info->availableModes[2].fs      = CELL_AUDIO_OUT_FS_48KHZ;
    if (audio_out_ch_cap())   /* audio out ch: only the modes up to the cap */
        info->availableModeCount = audio_out_ch_cap() == 2 ? 1 : audio_out_ch_cap() == 6 ? 2 : 3;

    return CELL_OK;''',
     "audio out ch devinfo")
edit("libs/misc/cellAvconfExt.c",
     '''    (void)config; (void)option; (void)waitForEvent;
    printf("[cellAvconfExt] AudioOutConfigure(audioOut=%u) -> ok\\n", audioOut);''',
     '''    (void)option; (void)waitForEvent;
    { const uint32_t ea = (uint32_t)(uintptr_t)config;   /* audio out ch: what the title asks for */
      if (ea) printf("[cellAvconfExt] AudioOutConfigure: channel %u encoder %u downMixer %u\\n",
                     vm_read8(ea), vm_read8(ea + 1), vm_read32(ea + 12)); }
    printf("[cellAvconfExt] AudioOutConfigure(audioOut=%u) -> ok\\n", audioOut);''',
     "audio out ch configure log")

# vk dedup: skip per-draw Vulkan state calls that repeat what this command buffer's open render pass
# already has bound. Every engine draw recorded BindPipeline, SetViewport, SetScissor,
# SetStencilReference, BindDescriptorSets, BindVertexBuffers and BindIndexBuffer before the draw:
# crater (run ds2, PS3RECOMP_ENG_DRAWSTATS) 13.5k draws a frame, "backend draw" 14.3 ms of the RSX
# thread's ~58 ms, ~14% of that thread's samples inside libvulkan_radeon (perf, run cr1); GPU wait
# only 2-5 ms/s ([vk] flush sites), so it is CPU recording cost. ~124 draws per render pass
# ([vk] render passes: ~18k for ~2.25M draws per 10 s). The cache is reset whenever a render pass
# begins (any site: the macro) and when a command buffer starts recording, so another draw path's
# binds can never leave it stale. PS3RECOMP_VK_DEDUP=0 = every call recorded (old).
edit("libs/video/rsx_vulkan_backend.c",
     '''#define pvkCmdBeginRenderPass       (vk_rp_close(), pvkCmdBeginRenderPass)''',
     '''/* vk dedup: what the open render pass of the recording command buffer has bound (valid = 0:
 * nothing known). Reset by every render pass begin and every vk_begin. */
static struct {
    int valid;
    VkPipeline pipe;
    VkViewport vp;
    VkRect2D sc;
    u32 sref;
    VkDescriptorSet dset; uint32_t dyn[2];
    VkBuffer vb; VkDeviceSize voff;
    VkBuffer ib; VkDeviceSize ioff;
} s_dd;
static void vk_dd_reset(void) { s_dd.valid = 0; s_dd.ib = VK_NULL_HANDLE; }
static int vk_dd_on(void)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3RECOMP_VK_DEDUP"); on = !(e && e[0] == '0'); }
    return on;
}
#define pvkCmdBeginRenderPass       (vk_rp_close(), vk_dd_reset(), pvkCmdBeginRenderPass)   /* vk dedup */''',
     "vk dedup state")
edit("libs/video/rsx_vulkan_backend.c",
     '''    VK_CHECK(pvkBeginCommandBuffer(s_vk.cmd, &bi), "vkBeginCommandBuffer");
    s_rec = 1;''',
     '''    VK_CHECK(pvkBeginCommandBuffer(s_vk.cmd, &bi), "vkBeginCommandBuffer");
    s_rec = 1;
    vk_dd_reset();   /* vk dedup: a new recording has nothing bound */''',
     "vk dedup begin")
edit("libs/video/rsx_vulkan_backend.c",
     '''    pvkCmdSetViewport(s_vk.cmd, 0, 1, &vp);
    pvkCmdSetScissor(s_vk.cmd, 0, 1, &sc);
    pvkCmdSetStencilReference(s_vk.cmd, VK_STENCIL_FACE_FRONT_AND_BACK, s_e2.stencil_ref & 0xFFu);
    pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_g.pipe_layout,
                             0, 1, &dset, 2, s_dyn);   /* vk dset reuse: dynamic offsets */
    pvkCmdBindVertexBuffers(s_vk.cmd, 0, 1, &vbuf, &voff);
    static int s_nodraw = -1;
    if (s_nodraw < 0) { const char* e = getenv("PS3RECOMP_VK_NODRAW"); s_nodraw = e && e[0] == '1'; }
    if (s_nodraw) {
    } else if (indices && index_count) {
        pvkCmdBindIndexBuffer(s_vk.cmd, ibuf, ioff, VK_INDEX_TYPE_UINT32);
        pvkCmdDrawIndexed(s_vk.cmd, index_count, 1, 0, 0, 0);''',
     '''    /* vk dedup: record only what differs from the open pass's bound state */
    const int dd = vk_dd_on() && s_dd.valid;
    const u32 sref = s_e2.stencil_ref & 0xFFu;
    if (!dd || s_dd.pipe != pipe) pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, pipe);
    if (!dd || memcmp(&s_dd.vp, &vp, sizeof vp)) pvkCmdSetViewport(s_vk.cmd, 0, 1, &vp);
    if (!dd || memcmp(&s_dd.sc, &sc, sizeof sc)) pvkCmdSetScissor(s_vk.cmd, 0, 1, &sc);
    if (!dd || s_dd.sref != sref) pvkCmdSetStencilReference(s_vk.cmd, VK_STENCIL_FACE_FRONT_AND_BACK, sref);
    if (!dd || s_dd.dset != dset || memcmp(s_dd.dyn, s_dyn, sizeof s_dd.dyn))
        pvkCmdBindDescriptorSets(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, s_g.pipe_layout,
                                 0, 1, &dset, 2, s_dyn);   /* vk dset reuse: dynamic offsets */
    if (!dd || s_dd.vb != vbuf || s_dd.voff != voff) pvkCmdBindVertexBuffers(s_vk.cmd, 0, 1, &vbuf, &voff);
    const int dd_ib = dd && s_dd.ib == ibuf && s_dd.ioff == ioff;
    s_dd.valid = 1; s_dd.pipe = pipe; s_dd.vp = vp; s_dd.sc = sc; s_dd.sref = sref;
    s_dd.dset = dset; memcpy(s_dd.dyn, s_dyn, sizeof s_dd.dyn);
    s_dd.vb = vbuf; s_dd.voff = voff;
    static int s_nodraw = -1;
    if (s_nodraw < 0) { const char* e = getenv("PS3RECOMP_VK_NODRAW"); s_nodraw = e && e[0] == '1'; }
    if (s_nodraw) {
    } else if (indices && index_count) {
        if (!dd_ib) pvkCmdBindIndexBuffer(s_vk.cmd, ibuf, ioff, VK_INDEX_TYPE_UINT32);
        s_dd.ib = ibuf; s_dd.ioff = ioff;
        pvkCmdDrawIndexed(s_vk.cmd, index_count, 1, 0, 0, 0);''',
     "vk dedup draw")
edit("libs/video/rsx_vulkan_backend.c",
     '''    pvkCmdBindPipeline(s_vk.cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, pipe);
    VkViewport vp = { 0.0f, 0.0f, (float)w, (float)h, 0.0f, 1.0f };''',
     '''    VkViewport vp = { 0.0f, 0.0f, (float)w, (float)h, 0.0f, 1.0f };   /* vk dedup: pipeline bound below */''',
     "vk dedup pipeline")

# gcm const fast: a vertex-constant burst (one incrementing packet: SET_TRANSFORM_CONSTANT_LOAD 0x1EFC
# + up to 32 words into the 0x1F00 window) is stored in one call instead of word by word through
# the whole FIFO walker body (debug checks, rsx_draw_engine_method, rsx_dispatch_method's range,
# empty-draw, seen/regs, upload-window tests). Crater, RSX_METHOD_HIST (run mh1): ~408k FIFO words a
# frame, about half of them in that window (0x1EFC and 0x1F00..0x1F0C ~3.1M each per 10 s); the
# walker was ~24% of the RSX thread (perf pf1). The 0x1EFC word still takes the normal path; the
# window words do exactly what rsx_dispatch_method does for them (seen++, regs, constants[slot]).
# Taken only for subchannel 0, a burst inside 0x1EFC..0x1F7C, one contiguous IO mapping, the draw
# engine on and every per-word diagnostic / legacy / live-draw path off. PS3_GCM_CONST_FAST=0 = old.
edit("libs/video/rsx_dispatch.h",
     '''void rsx_dispatch_method(rsx_dispatch* rsx, u32 method, u32 arg);''',
     '''void rsx_dispatch_method(rsx_dispatch* rsx, u32 method, u32 arg);
/* gcm const fast: n words into the transform-constant window from `method` on, as n
 * rsx_dispatch_method calls would store them (method + 4n <= M_VP_UPLOAD_CONST + 128). */
void rsx_dispatch_const_words(rsx_dispatch* rsx, u32 method, const u32* words, u32 n);''',
     "gcm const fast decl")
edit("libs/video/rsx_dispatch.c",
     '''void rsx_dispatch_method(rsx_dispatch* rsx, u32 method, u32 arg)
{''',
     '''void rsx_dispatch_const_words(rsx_dispatch* rsx, u32 method, const u32* words, u32 n)
{   /* gcm const fast: the transform-constant window branch of rsx_dispatch_method, n times */
    const u32 base = rsx->regs[M_VP_UPLOAD_CONST_ID >> 2];
    for (u32 i = 0; i < n; i++) {
        const u32 m = method + i * 4u, idx = m >> 2;
        rsx->seen[idx]++;
        rsx->regs[idx] = words[i];
        const u32 word = (m - M_VP_UPLOAD_CONST) >> 2;
        const u32 slot = base + (word >> 2);
        if (slot < RSX_DSP_NUM_CONSTANTS)
            rsx->constants[slot][word & 3] = words[i];
    }
}

void rsx_dispatch_method(rsx_dispatch* rsx, u32 method, u32 arg)
{''',
     "gcm const fast dispatch")
edit("libs/video/rsx_draw_engine.h",
     '''void rsx_draw_engine_method(u32 method, u32 arg);''',
     '''void rsx_draw_engine_method(u32 method, u32 arg);
/* gcm const fast: a transform-constant window burst (subchannel 0, 0x1F00..0x1F7C) */
void rsx_draw_engine_const_words(u32 method, const u32* words, u32 n);''',
     "gcm const fast engine decl")
edit("libs/video/rsx_draw_engine.c",
     '''void rsx_draw_engine_method(u32 method, u32 arg)
{''',
     '''void rsx_draw_engine_const_words(u32 method, const u32* words, u32 n)
{   /* gcm const fast */
    if (!g.ready) return;
    rsx_dispatch_const_words(&g.rsx, method, words, n);
}

void rsx_draw_engine_method(u32 method, u32 arg)
{''',
     "gcm const fast engine")
edit("libs/video/cellGcmSys.c",
     '''            const int fifo_dbg = gcm_fifo_dbg();
            for (u32 i = 0; i < count; i++) {''',
     '''            const int fifo_dbg = gcm_fifo_dbg();
            /* gcm const fast: a whole vertex-constant burst in one store */
            { static int cf = -1;
              if (cf < 0) {
                  const char* e = getenv("PS3_GCM_CONST_FAST");
                  const char* lg = getenv("GCM_CONST_LEGACY");
                  cf = !(e && *e == '0') && rsx_draw_engine_enabled() && !rsx_live_draw_enabled() &&
                       !(lg && *lg == '1') && !getenv("RSX_METHOD_HIST") && !getenv("TCONST_FIFO") &&
                       !getenv("RSX_CONST_LOG") && !getenv("RSX_EMPTY_DRAW_LOG");
                  if (cf) fprintf(stderr, "[cellGcmSys] vertex-constant bursts: one store per packet (PS3_GCM_CONST_FAST=0 = per word)\\n");
              }
              if (cf && type == 0 && subch == 0 && !fifo_dbg && count >= 2 && count <= 33 &&
                  method >= 0x1EFCu && method + count * 4u <= 0x1F80u) {
                  const u32 ea0 = gcm_io2ea(s_fifo_getoff + 4);
                  const u32 ean = gcm_io2ea(s_fifo_getoff + 4 + (count - 1) * 4);
                  if (ea0 && ean == ea0 + (count - 1) * 4) {
                      u32 i0 = 0;
                      if (method == 0x1EFCu) {   /* SET_TRANSFORM_CONSTANT_LOAD: the normal path */
                          const u32 dw = vm_read32(ea0);
                          rsx_draw_engine_method(method, dw);
                          rsx_process_method(&s_state, method, dw);
                          i0 = 1;
                      }
                      u32 buf[33];
                      for (u32 i = i0; i < count; i++) buf[i - i0] = vm_read32(ea0 + i * 4);
                      rsx_draw_engine_const_words(method + i0 * 4, buf, count - i0);
                      s_fifo_getoff += 4 + count * 4;
                      continue;
                  }
              } }
            for (u32 i = 0; i < count; i++) {''',
     "gcm const fast walker")


# idx memo: an indexed draw whose index bytes, index registers and primitive are those of an
# earlier draw reuses that draw's result: the vertex range (lo, span) and the finished triangle
# indices, skipping the index decode into references, the range remap and the topology index
# write. Crater (DRAWSTATS ds2/dd1c): refs 2.5 ms + remap 3.7-3.9 ms a frame, 4.3M references
# (17 MB of rebuilt indices) for ~13.5k draws, 13.3k of which draw from the vertex cache, i.e.
# the same meshes every frame. Only one-run index draws that took the ranged remap and had no
# restart cut are kept. The index bytes are hashed in full on every draw (64-bit, the vertex
# cache's eng_hash_span), so a changed index buffer is a miss at once. On a hit only refs[0]
# is set; the whole reference list is filled in before anything that reads past it (a wrapping
# element range or a frequency-divided attribute in the fetch plan, a vertex-cache miss, a
# non-indexed fallback). PS3RECOMP_ENG_IDXMEMO=0 = old.
edit("libs/video/rsx_draw_engine.c",
     '''/* The draw accumulator: one BEGIN_END group's batches, references and cuts. */
static struct {''',
     '''/* idx memo: one remembered index result (key fields, index-byte hash, range, indices) */
typedef struct {
    u64 key, content;
    u32 f[8];
    u32 lo, base, span, count, n_draw, idx_cap, last_frame;
    u8 complete;
    u32* idx;
} eng_im_entry;
#define ENG_IM_N 32768u
static eng_im_entry s_im[ENG_IM_N];
static u64 ds_im_hit, ds_im_miss;

/* The draw accumulator: one BEGIN_END group's batches, references and cuts. */
static struct {
    eng_im_entry* im_hit;     /* idx memo: this draw's remembered result */
    eng_im_entry* im_store;   /* idx memo: the entry this draw's result goes into */
    int im_lazy;              /* idx memo: refs[1..] not filled yet */''',
     "idx memo struct")
edit("libs/video/rsx_draw_engine.c",
     '''    dc.inl = NULL;
    dc.inl_bytes = 0;
}''',
     '''    dc.inl = NULL;
    dc.inl_bytes = 0;
    dc.im_hit = dc.im_store = NULL; dc.im_lazy = 0;   /* idx memo */
}''',
     "idx memo reset")
edit("libs/video/rsx_draw_engine.c",
     '''static void dc_fetch(const rsx_vertex_layout_plan* layout, int allow_remap)
{
    const int dso = eng_ds_enabled();
    u64 t0 = dso ? eng_ds_now() : 0, t1;''',
     '''/* idx memo */
static int eng_im_on(void)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3RECOMP_ENG_IDXMEMO"); on = !(e && *e == '0'); }
    return on;
}

/* idx memo: this draw's one index run against the remembered results: dc.im_hit on a match,
 * else dc.im_store = the entry (keyed, not complete) its result goes into. */
static void eng_im_lookup(void)
{
    rsx_dsp_index_array ia;
    rsx_dsp_get_index_array(&g.rsx, &ia);
    const u32 esz = ia.is_u32 ? 4u : 2u;
    const u32 base_index = rsx_dsp_vertex_data_base_index(&g.rsx);
    const int restart_en = rsx_dsp_restart_index_enabled(&g.rsx, ia.is_u32);
    const u32 restart_val = rsx_dsp_restart_index(&g.rsx);
    const u32 ia_loc = ia.location ? RSX_LOCATION_MAIN : RSX_LOCATION_LOCAL;
    const u32 first = dc.idx[0].first, count = dc.idx[0].count;
    const u64 start = (u64)ia.offset + (u64)first * esz, bytes = (u64)count * esz;
    if (start + bytes > 0x100000000ull) return;
    const u8* run = eng_guest_ptr(NULL, ia_loc, (u32)start, (u32)bytes);
    if (!run) return;
    const u32 f[8] = { ia.offset, ia_loc | ((u32)ia.is_u32 << 4) | ((u32)(restart_en != 0) << 5), first, count,
                       base_index, restart_en ? restart_val : 0u, g.rsx.current_primitive, 0x494D454Du };
    const u64 key = eng_fnv1a(f, sizeof f, 1469598103934665603ull);
    const u64 c = eng_hash_span(run, bytes, 0x51ED270B27A3F5E1ull);
    eng_im_entry* e = &s_im[key & (ENG_IM_N - 1u)];
    if (e->complete && e->key == key && !memcmp(e->f, f, sizeof f) && e->content == c) {
        e->last_frame = g.frames;
        dc.im_hit = e;
        ds_im_hit++;
        return;
    }
    e->key = key; memcpy(e->f, f, sizeof f); e->content = c; e->complete = 0;
    dc.im_store = e;
    ds_im_miss++;
}

/* idx memo: the reference list a hit skipped, for a reader past refs[0] */
static int dc_im_fill(void)
{
    if (!dc.im_lazy) return 1;
    const eng_im_entry* e = dc.im_hit;
    if (!dc_reserve_refs(e->span)) return 0;
    for (u32 i = 0; i < e->span; i++) { dc.refs[i].vertex_id = e->lo + i; dc.refs[i].base_index = e->base; }
    dc.im_lazy = 0;
    return 1;
}

static void dc_fetch(const rsx_vertex_layout_plan* layout, int allow_remap)
{
    const int dso = eng_ds_enabled();
    u64 t0 = dso ? eng_ds_now() : 0, t1;
    dc.im_hit = dc.im_store = NULL; dc.im_lazy = 0;   /* idx memo */
    if (allow_remap && eng_im_on() && !dc.n_arr && dc.n_idx == 1 && !dc.inl && dc.idx[0].count > 1 && dc.fetch_ok)
        eng_im_lookup();''',
     "idx memo lookup")
edit("libs/video/rsx_draw_engine.c",
     '''    if (dc.n_idx && dc.fetch_ok) {
        const u32 base_index = rsx_dsp_vertex_data_base_index(&g.rsx);''',
     '''    if (dc.n_idx && dc.fetch_ok && !dc.im_hit) {   /* idx memo: a hit skips the decode */
        const u32 base_index = rsx_dsp_vertex_data_base_index(&g.rsx);''',
     "idx memo skip decode")
edit("libs/video/rsx_draw_engine.c",
     '''    if (!dc.fetch_ok) return;

    dc.n_source_refs = dc.n_refs;''',
     '''    if (!dc.fetch_ok) return;
    if (dc.im_hit) {   /* idx memo: refs[0] now, the rest when something reads them */
        if (!dc_reserve_refs(dc.im_hit->span)) { dc.fetch_ok = 0; return; }
        dc.refs[0].vertex_id = dc.im_hit->lo; dc.refs[0].base_index = dc.im_hit->base;
        dc.n_refs = dc.im_hit->count;
    }

    dc.n_source_refs = dc.n_refs;''',
     "idx memo refs0")
edit("libs/video/rsx_draw_engine.c",
     '''    int consecutive = 0;   /* refs = one run of vertex ids (the ranged remap) */
    if (allow_remap && dc.n_refs > 1) {''',
     '''    int consecutive = 0;   /* refs = one run of vertex ids (the ranged remap) */
    if (dc.im_hit) {   /* idx memo: the ranged remap's result */
        dc.refs_remapped = 1;
        dc.n_refs = dc.im_hit->span;
        consecutive = 1;
        dc.im_lazy = dc.im_hit->span > 1;
    } else if (allow_remap && dc.n_refs > 1) {''',
     "idx memo remap")
edit("libs/video/rsx_draw_engine.c",
     '''    if (dso) { t1 = eng_ds_now(); ds.ns_remap += t1 - t0; t0 = t1; }
    dc.layout = *layout;
    rsx_vertex_fetch_plan_init(&dc.fetch_plan, &g.rsx, layout, eng_guest_ptr, NULL);
    rsx_vertex_fetch_plan_set_inline(&dc.fetch_plan, &g.rsx, dc.inl, dc.inl_bytes);''',
     '''    /* idx memo: keep only a one-run (ranged) result without cuts */
    if (dc.im_store) {
        if (consecutive && !dc.n_cuts) {
            dc.im_store->lo = dc.refs[0].vertex_id; dc.im_store->base = dc.refs[0].base_index;
            dc.im_store->span = dc.n_refs; dc.im_store->count = dc.n_source_refs;
        } else dc.im_store = NULL;
    }
    if (dso) { t1 = eng_ds_now(); ds.ns_remap += t1 - t0; t0 = t1; }
    dc.layout = *layout;
    rsx_vertex_fetch_plan_init(&dc.fetch_plan, &g.rsx, layout, eng_guest_ptr, NULL);
    rsx_vertex_fetch_plan_set_inline(&dc.fetch_plan, &g.rsx, dc.inl, dc.inl_bytes);
    if (dc.im_lazy) {   /* idx memo: prepare_ex walks every reference for these */
        int need = (u64)rsx_vertex_element_index(dc.im_hit->lo, dc.im_hit->base, 0, 0) + dc.n_refs - 1u > 0x000FFFFFu;
        for (u32 slot = 0; slot < layout->count && !need; slot++)
            need = dc.fetch_plan.attr[layout->attrs[slot]].desc.frequency > 1;
        if (need && !dc_im_fill()) { dc.fetch_ok = 0; return; }
    }''',
     "idx memo plan fill")
edit("libs/video/rsx_draw_engine.c",
     '''    if (!dc_reserve_verts((u64)dc.n_refs * layout->stride)) {
        dc.fetch_ok = 0;
        return;
    }''',
     '''    if (!dc_im_fill() || !dc_reserve_verts((u64)dc.n_refs * layout->stride)) {   /* idx memo: fetched from refs */
        dc.fetch_ok = 0;
        return;
    }''',
     "idx memo fetch fill")
edit("libs/video/rsx_draw_engine.c",
     '''    if (dc.vbuf_hit && !indexed) {
        if (!dc_reserve_verts((u64)dc.n_refs * dc.layout.stride) ||''',
     '''    if (dc.vbuf_hit && !indexed) {
        if (!dc_im_fill() ||   /* idx memo */
            !dc_reserve_verts((u64)dc.n_refs * dc.layout.stride) ||''',
     "idx memo nonindexed fill")
edit("libs/video/rsx_draw_engine.c",
     '''    if (indexed) {
        if (!dc_reserve_indices(n_draw)) { eng_drop("reserve_indices", prim); return; }
        rsx_draw_engine_write_topology_indices(
            prim, dc.n_source_refs, dc.cuts, dc.n_cuts,
            dc.refs_remapped ? dc.ref_remap.occurrence_to_unique : NULL,
            g.indices);
    }''',
     '''    const u32* draw_idx = g.indices;   /* idx memo: the remembered indices on a hit */
    if (indexed && dc.im_hit && dc.im_hit->n_draw == n_draw) {
        draw_idx = dc.im_hit->idx;
    } else if (indexed) {
        if (dc.im_hit) { eng_drop("idx_memo", prim); return; }   /* (n_draw is fixed by the key) */
        if (!dc_reserve_indices(n_draw)) { eng_drop("reserve_indices", prim); return; }
        rsx_draw_engine_write_topology_indices(
            prim, dc.n_source_refs, dc.cuts, dc.n_cuts,
            dc.refs_remapped ? dc.ref_remap.occurrence_to_unique : NULL,
            g.indices);
        draw_idx = g.indices;
        if (dc.im_store) {   /* idx memo: keep this result */
            eng_im_entry* e = dc.im_store;
            if (e->idx_cap < n_draw) {
                u32* p = (u32*)realloc(e->idx, (size_t)n_draw * sizeof(u32));
                if (p) { e->idx = p; e->idx_cap = n_draw; }
            }
            if (e->idx_cap >= n_draw) {
                memcpy(e->idx, g.indices, (size_t)n_draw * sizeof(u32));
                e->n_draw = n_draw; e->last_frame = g.frames; e->complete = 1;
            }
        }
    }''',
     "idx memo indices")
edit("libs/video/rsx_draw_engine.c",
     '''        g.be->draw_vbuf(g.be->user, topology, dc.vbuf, uploaded, layout.stride,
                        g.indices, n_draw);
    else
        g.be->draw(g.be->user, topology, dc.verts, uploaded, layout.stride,
                   indexed ? g.indices : NULL, indexed ? n_draw : 0);''',
     '''        g.be->draw_vbuf(g.be->user, topology, dc.vbuf, uploaded, layout.stride,
                        draw_idx, n_draw);   /* idx memo */
    else
        g.be->draw(g.be->user, topology, dc.verts, uploaded, layout.stride,
                   indexed ? draw_idx : NULL, indexed ? n_draw : 0);''',
     "idx memo draw")
edit("libs/video/rsx_draw_engine.c",
     '''                if (ds.span_draws)
            fprintf(stderr, "[drawstats] index ranges:''',
     '''        fprintf(stderr, "[drawstats] idx memo: %llu hits, %llu misses\\n",
                (unsigned long long)ds_im_hit, (unsigned long long)ds_im_miss);
        ds_im_hit = ds_im_miss = 0;
                if (ds.span_draws)
            fprintf(stderr, "[drawstats] index ranges:''',
     "idx memo stats")

# idx memo multi: the index memo for draws of several index batches too. One DRAW_INDEX_ARRAY
# carries at most 256 indices, so every larger mesh arrives as a series of batches; with only
# one-batch draws eligible, run im1 had ~8.9k hits a frame of ~13.5k draws and remap still
# 2.8 ms. Batches that follow each other exactly (each first = previous first + count) decode
# into the same references as one run of their total count, so they are keyed as that run.
edit("libs/video/rsx_draw_engine.c",
     '''    const u32 first = dc.idx[0].first, count = dc.idx[0].count;
    const u64 start = (u64)ia.offset + (u64)first * esz, bytes = (u64)count * esz;''',
     '''    const u32 first = dc.idx[0].first;
    u64 count64 = dc.idx[0].count;   /* idx memo multi: contiguous batches = one run */
    for (u32 b = 1; b < dc.n_idx; b++) {
        if ((u64)dc.idx[b].first != (u64)first + count64) return;
        count64 += dc.idx[b].count;
    }
    if (count64 > 0xFFFFFFFFull) return;
    const u32 count = (u32)count64;
    const u64 start = (u64)ia.offset + (u64)first * esz, bytes = (u64)count * esz;''',
     "idx memo multi lookup")
edit("libs/video/rsx_draw_engine.c",
     '''    if (allow_remap && eng_im_on() && !dc.n_arr && dc.n_idx == 1 && !dc.inl && dc.idx[0].count > 1 && dc.fetch_ok)''',
     '''    if (allow_remap && eng_im_on() && !dc.n_arr && dc.n_idx >= 1 && !dc.inl && dc.fetch_ok &&
        (dc.n_idx > 1 || dc.idx[0].count > 1))   /* idx memo multi */''',
     "idx memo multi gate")

# idx memo sparse: the index memo's content check sampled for settled entries, as the vertex
# cache's (vc sparse). The full 64-bit hash of every hit's index bytes (~8.6 MB a frame in the
# crater) cost more than the decode it replaced (im2: refs stage 2.5 -> 3.3 ms; crater imB/imA
# 19.3 -> 19.5 fps). After 4 full checks in a row that matched, frames other than every 8th
# (staggered by key) compare a sampled hash (64 bytes of every 2 KB + the last 64) against the
# one taken at the last full check; a sampled mismatch takes the full hash. A rewrite of a
# settled index buffer is seen at once if it touches a sampled block, else within 8 frames.
# PS3RECOMP_ENG_IDXMEMO_SPARSE=0 = full hash every draw.
edit("libs/video/rsx_draw_engine.c",
     '''    u8 complete;
    u32* idx;
} eng_im_entry;''',
     '''    u8 complete;
    u8 stable;      /* idx memo sparse: full checks in a row that matched */
    u64 sparse;     /* idx memo sparse: sampled hash at the last full check */
    u32* idx;
} eng_im_entry;''',
     "idx memo sparse struct")
edit("libs/video/rsx_draw_engine.c",
     '''    const u64 key = eng_fnv1a(f, sizeof f, 1469598103934665603ull);
    const u64 c = eng_hash_span(run, bytes, 0x51ED270B27A3F5E1ull);
    eng_im_entry* e = &s_im[key & (ENG_IM_N - 1u)];
    if (e->complete && e->key == key && !memcmp(e->f, f, sizeof f) && e->content == c) {
        e->last_frame = g.frames;
        dc.im_hit = e;
        ds_im_hit++;
        return;
    }
    e->key = key; memcpy(e->f, f, sizeof f); e->content = c; e->complete = 0;''',
     '''    const u64 key = eng_fnv1a(f, sizeof f, 1469598103934665603ull);
    eng_im_entry* e = &s_im[key & (ENG_IM_N - 1u)];
    const int same = e->complete && e->key == key && !memcmp(e->f, f, sizeof f);
    /* idx memo sparse: sampled hash (as eng_vc_probe's) */
    static int s_sp = -1;
    if (s_sp < 0) { const char* ev = getenv("PS3RECOMP_ENG_IDXMEMO_SPARSE"); s_sp = !(ev && *ev == '0'); }
    u64 sp = 0x6A09E667F3BCC908ull;
    if (s_sp) {
        if (bytes < 64) { for (u64 j = 0; j < bytes; j++) { sp ^= run[j]; sp *= 1099511628211ull; } }
        else {
            for (u64 j = 0; j + 64 <= bytes; j += 2048) {
                u64 w[8]; memcpy(w, run + j, sizeof w);
                for (int k = 0; k < 8; k++) sp = (sp ^ w[k]) * 1099511628211ull;
            }
            u64 w[8]; memcpy(w, run + bytes - 64, sizeof w);
            for (int k = 0; k < 8; k++) sp = (sp ^ w[k]) * 1099511628211ull;
        }
        sp ^= bytes;
        if (same && e->stable >= 4 && ((g.frames + (u32)key) & 7u) != 0 && sp == e->sparse) {
            e->last_frame = g.frames;
            dc.im_hit = e;
            ds_im_hit++;
            return;
        }
    }
    const u64 c = eng_hash_span(run, bytes, 0x51ED270B27A3F5E1ull);
    if (same && e->content == c) {
        if (e->stable < 255) e->stable++;
        e->sparse = sp;
        e->last_frame = g.frames;
        dc.im_hit = e;
        ds_im_hit++;
        return;
    }
    e->stable = 0; e->sparse = sp;
    e->key = key; memcpy(e->f, f, sizeof f); e->content = c; e->complete = 0;''',
     "idx memo sparse lookup")

# evq stall dump: PS3_EVQ_STALL=<seconds> -- a blocking sys_event_queue_receive (timeout 0) that has
# waited this long with nothing arriving prints, once per thread and queue (16 reports in all), the
# waiter's registers and a hex dump of every guest object its registers point at (128-byte aligned:
# a CellSpursEventFlag is), then keeps waiting. For the 21:22 console run's streaming stall: fios
# mediathread tid 14 sat in libsre cellSpursEventFlagWait -> receive on queue 5 "_spuEvF" from 593 s
# on (q5 pushes stop at 11363, [evqstat]), holding lwmutex 0x95000039 that tids 15/16 wait for; the
# dump shows whether the flag has the event set with a waiter registered (a lost wakeup) or no event
# at all (the SPU task never set it). For "_spuEvF" waits it also dumps the fios job table the caller
# keeps beside the flag (func_0048B818: flag = obj+0x2980, slot mask obj+0x2C00, slots obj+0x2C04).
# Only guest memory that is surely committed is read (main, stacks, sys_memory below the bump).
# Off (no env) = the plain wait.
edit("runtime/syscalls/sys_event.c",
     '''    if (timeout_us == 0) {
        while (q->count == 0 && q->active && !q->cancelled) {
            pthread_cond_wait(&q->not_empty, &q->lock);
        }
    } else {
        struct timespec ts;''',
     '''    if (timeout_us == 0) {
        /* evq stall dump (tools/patch_evq_stall_dump.py) */
        static int s_stall = -1;
        if (s_stall < 0) { const char* e = getenv("PS3_EVQ_STALL"); s_stall = e ? atoi(e) : 0; }
        int reported = 0;
        while (q->count == 0 && q->active && !q->cancelled) {
            if (s_stall <= 0 || reported) { pthread_cond_wait(&q->not_empty, &q->lock); continue; }
            struct timespec ts;
            clock_gettime(CLOCK_REALTIME, &ts);
            ts.tv_sec += s_stall;
            if (pthread_cond_timedwait(&q->not_empty, &q->lock, &ts) == ETIMEDOUT &&
                q->count == 0 && q->active && !q->cancelled) {
                reported = 1;
                evq_stall_report(ctx, queue_id, q->name, s_stall);
            }
        }
    } else {
        struct timespec ts;''',
     "evq stall wait")
edit("runtime/syscalls/sys_event.c",
     '''int64_t sys_event_queue_receive(ppu_context* ctx)
{''',
     '''/* evq stall dump (tools/patch_evq_stall_dump.py) */
static int evq_stall_readable(uint32_t a, uint32_t n)
{
    extern uint32_t g_sys_mem_bump_ptr;
    if (vm_is_valid_addr(a) && vm_is_valid_addr(a + n - 1)) return 1;
    return a >= 0x40000000u && g_sys_mem_bump_ptr && a + n <= g_sys_mem_bump_ptr;
}
static void evq_stall_hex(const char* tag, uint32_t a, uint32_t n)
{
    /* guest stacks are committed one by one: never read past the page */
    if (a >= VM_STACK_BASE && a < VM_STACK_BASE + VM_STACK_REGION && n > 0x1000u - (a & 0xFFFu))
        n = 0x1000u - (a & 0xFFFu);
    if (!evq_stall_readable(a, n)) return;
    const uint8_t* p = (const uint8_t*)vm_to_host(a);
    for (uint32_t o = 0; o < n; o += 32) {
        char ln[128]; int k = snprintf(ln, sizeof ln, "[evq-stall]   %s %08X:", tag, a + o);
        for (uint32_t i = o; i < o + 32 && i < n; i += 4)
            k += snprintf(ln + k, sizeof ln - k, " %02X%02X%02X%02X", p[i], p[i + 1], p[i + 2], p[i + 3]);
        fprintf(stderr, "%s\\n", ln);
    }
}
static void evq_stall_report(ppu_context* ctx, uint32_t queue_id, const char* qname, int secs)
{
    static _Atomic int s_n;
    char nm[9]; memcpy(nm, qname, 8); nm[8] = 0;
    { const char* want = getenv("PS3_EVQ_STALL_NAME");   /* default: SPURS event flag queues */
      if (strncmp(nm, want ? want : "_spuEvF", 8)) return; }
    if (s_n++ >= 16) return;
    for (int i = 0; i < 8; i++) if (nm[i] && (nm[i] < 32 || nm[i] > 126)) nm[i] = '?';
    fprintf(stderr, "[evq-stall] tid=%llu blocked %d s on queue %u \\"%s\\" (nothing pending) lr=0x%08X\\n",
            (unsigned long long)ctx->thread_id, secs, queue_id, nm, (uint32_t)ctx->lr);
    for (int r = 0; r < 32; r += 8)
        fprintf(stderr, "[evq-stall]   r%-2d %08X %08X %08X %08X %08X %08X %08X %08X\\n", r,
                (uint32_t)ctx->gpr[r], (uint32_t)ctx->gpr[r + 1], (uint32_t)ctx->gpr[r + 2], (uint32_t)ctx->gpr[r + 3],
                (uint32_t)ctx->gpr[r + 4], (uint32_t)ctx->gpr[r + 5], (uint32_t)ctx->gpr[r + 6], (uint32_t)ctx->gpr[r + 7]);
    uint32_t done[32]; int nd = 0;
    for (int r = 3; r < 32; r++) {
        const uint32_t a = (uint32_t)ctx->gpr[r];
        if (a & 127u) continue;
        int seen = 0;
        for (int i = 0; i < nd; i++) if (done[i] == a) seen = 1;
        if (seen || !evq_stall_readable(a, 128)) continue;
        done[nd++] = a;
        char tag[8]; snprintf(tag, sizeof tag, "r%d", r);
        evq_stall_hex(tag, a, 128);
        if (!strcmp(nm, "_spuEvF") && a >= 0x2980u) evq_stall_hex("job", a - 0x2980u + 0x2C00u, 0x2C4u);
    }
    /* the guest stack: libsre's saved registers and its caller's frame */
    evq_stall_hex("sp", (uint32_t)ctx->gpr[1], 0x200);
}

int64_t sys_event_queue_receive(ppu_context* ctx)
{''',
     "evq stall report")

# devpad replay env: PS3_DEVPAD_REPLAY=<file.pad> replays a controller recording ("t d1 d2 lx ly
# rx ry", ms) from the first pad poll + PS3_DEVPAD_REPLAY_AT seconds (default 0), so a console run's
# input (work/live/if1_live_1103_fps/pad/fps1103.pad) can be re-driven on the BC-250 without the
# debug server. Unset = no replay (old).
edit("libs/input/cellPad.c",
     '''    /* devpad: injected presses and a replay, then the recorder (port 0) */
    if (port_no == 0) {''',
     '''    /* devpad: injected presses and a replay, then the recorder (port 0) */
    if (port_no == 0) {
        { static int s_rp = -1; static unsigned long long s_rp_t0;   /* devpad replay env */
          if (s_rp < 0) { s_rp = getenv("PS3_DEVPAD_REPLAY") ? 1 : 0; s_rp_t0 = GetTickCount64(); }
          if (s_rp == 1) {
              const char* at = getenv("PS3_DEVPAD_REPLAY_AT");
              if (GetTickCount64() - s_rp_t0 >= (unsigned long long)(at ? atoi(at) : 0) * 1000ull) {
                  s_rp = 2;
                  const int rc = ps3_devpad_replay(getenv("PS3_DEVPAD_REPLAY"));
                  printf("[devpad] replay of %s started (%d)\\n", getenv("PS3_DEVPAD_REPLAY"), rc);
              } } }''',
     "devpad replay env")


# spu call fast: a lifted brsl/bisl call bracket ends in spu_drain_call(ctx, ret) + spu_img_restore -- two
# out-of-line calls (+ spu_depth_guard inside) after EVERY SPU function call, ~0.35 cores in the if1 crater
# (c1on: drain 0.20, depth guard 0.07, ...). When the callee simply returned (no pending transfer, pc == the
# return pc) the drain loop does nothing but clear drain_ret_pc, so do that inline. The depth limit is still
# honoured (over it -> the slow path, which halts as before); the depth ring just does not record these
# plain returns. spu_img_restore becomes inline (same body). PS3_SPU_CALL_FAST=0 = old (every return
# through spu_drain_call).
edit("runtime/spu/spu_context.h",
     '''/* Drain a translated call up to its explicit architectural return PC. */
void spu_drain_call(spu_context* ctx, uint32_t return_pc);''',
     '''/* Drain a translated call up to its explicit architectural return PC. */
void spu_drain_call_slow(spu_context* ctx, uint32_t return_pc);
/* spu call fast (PS3_SPU_CALL_FAST, default on): 0 until spu_drain_call_slow's first run reads it. */
extern int g_spu_call_fast;
extern uint32_t g_spu_depth_max;
static inline __attribute__((always_inline)) void spu_drain_call(spu_context* ctx, uint32_t return_pc)
{
    /* the callee returned to us: nothing for the drain loop to run */
    if (__builtin_expect(g_spu_call_fast > 0 && !ctx->tramp_fn &&
                         ((ctx->pc ^ return_pc) & SPU_LS_MASK) == 0 &&
                         ctx->host_depth < g_spu_depth_max, 1)) {
        ctx->drain_ret_pc = 0;
        return;
    }
    spu_drain_call_slow(ctx, return_pc);
}''',
     "spu call fast: inline drain")
edit("runtime/spu/spu_context.h",
     '''void spu_img_restore(spu_context* ctx, int32_t saved_img);
/* Wake a host thread''',
     '''static inline __attribute__((always_inline)) void spu_img_restore(spu_context* ctx, int32_t saved_img)
{
    ctx->image_id = ctx->module_img_a00 ? ctx->module_img_a00 : saved_img;   /* spu call fast: inline */
}
/* Wake a host thread''',
     "spu call fast: inline img restore")
edit("runtime/spu/spu_drain.c",
     '''void spu_img_restore(spu_context* ctx, int32_t saved_img)
{
    ctx->image_id = ctx->module_img_a00 ? ctx->module_img_a00 : saved_img;
}''',
     '''/* (spu_img_restore: inline in spu_context.h, spu call fast) */''',
     "spu call fast: img restore moved")
edit("runtime/spu/spu_drain.c",
     '''void spu_drain_call(spu_context* ctx, uint32_t return_pc)
{
    if (__builtin_expect(g_spu_direct < 0, 0)) spu_direct_init();''',
     '''int g_spu_call_fast = 0;            /* spu call fast */
uint32_t g_spu_depth_max = 2000u;
void spu_drain_call_slow(spu_context* ctx, uint32_t return_pc)
{
    if (__builtin_expect(g_spu_direct < 0, 0)) spu_direct_init();
    { static int s_cf = -1;         /* spu call fast: read once, the same limit spu_depth_guard uses */
      if (s_cf < 0) {
          const char* e = getenv("SPU_HOST_DEPTH_MAX");
          g_spu_depth_max = e ? (uint32_t)strtoul(e, 0, 0) : 2000u;
          const char* c = getenv("PS3_SPU_CALL_FAST");
          s_cf = c && c[0] == '1';   /* default off: no measurable gain on route1 (2026-11-04) */
          __atomic_store_n(&g_spu_call_fast, s_cf, __ATOMIC_RELAXED);
      } }''',
     "spu call fast: slow drain")

# devpad record env: PS3_DEVPAD_RECORD=<file.pad> records port 0 from the first pad poll (the time base
# PS3_DEVPAD_REPLAY uses with PS3_DEVPAD_REPLAY_AT=0), flushed per line so a killed run keeps it. For the
# user's BC-250 benchmark route. Unset = no recording (old).
edit("libs/input/cellPad.c",
     '''        { static int s_rp = -1; static unsigned long long s_rp_t0;   /* devpad replay env */''',
     '''        { static int s_rc = -1;                                        /* devpad record env */
          if (s_rc < 0) { const char* r = getenv("PS3_DEVPAD_RECORD"); s_rc = 0;
              if (r && *r) { const int rc = ps3_devpad_record(r); printf("[devpad] recording to %s (%d)\\n", r, rc); } } }
        { static int s_rp = -1; static unsigned long long s_rp_t0;   /* devpad replay env */''',
     "devpad record env: start")
edit("libs/input/cellPad.c",
     '''                fprintf(s_dp_rec, "%llu %u %u %u %u %u %u\\n", GetTickCount64() - s_dp_rec_t0, v[0], v[1], v[2], v[3], v[4], v[5]);''',
     '''                fprintf(s_dp_rec, "%llu %u %u %u %u %u %u\\n", GetTickCount64() - s_dp_rec_t0, v[0], v[1], v[2], v[3], v[4], v[5]);
                fflush(s_dp_rec);   /* devpad record env: a killed run keeps its recording */''',
     "devpad record env: flush")

# spu call fast 2: a callee that returns through a jump (bi on a non-link register, a jump table) leaves
# tramp_fn = spu_indirect_branch with pc already at the return pc; spu_drain_call_slow's first check
# clears it and returns, nothing else. Do that inline too. (route1 r3b: drain_call_slow still 0.11 cores
# with spu call fast on.) Same switch: PS3_SPU_CALL_FAST=0 = old.
edit("runtime/spu/spu_context.h",
     '''    if (__builtin_expect(g_spu_call_fast > 0 && !ctx->tramp_fn &&
                         ((ctx->pc ^ return_pc) & SPU_LS_MASK) == 0 &&
                         ctx->host_depth < g_spu_depth_max, 1)) {
        ctx->drain_ret_pc = 0;
        return;
    }''',
     '''    if (__builtin_expect(g_spu_call_fast > 0 &&
                         (!ctx->tramp_fn || ctx->tramp_fn == spu_indirect_branch) &&
                         ((ctx->pc ^ return_pc) & SPU_LS_MASK) == 0 &&
                         ctx->host_depth < g_spu_depth_max, 1)) {
        ctx->tramp_fn = 0;   /* spu call fast 2: a jump back to the return pc */
        ctx->drain_ret_pc = 0;
        return;
    }''',
     "spu call fast 2: jump return")
