# vk tex3d fix: the decompiler pads "Texture3D" to the TextureCube width, so the unit name is 12 characters on
VKF = "libs/video/rsx_vulkan_backend.c"
edit(VKF,
     '''        if (!t || t - c > 8) continue;''',
     '''        if (!t || t - c > 16) continue;   /* "Texture3D   rsx_tex<n>" */''',
     "vk tex3d fix: parse")
