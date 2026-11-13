#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
cd $HOME/if2/ps3recomp-fork
grep -c 'SPIRV_MISS_DIR' libs/video/rsx_shader_spirv.cpp
n=$(grep -n 'engine: vkCreateGraphicsPipelines failed' libs/video/rsx_vulkan_backend.c | cut -d: -f1)
sed -n "$((n-2)),$((n+3))p" libs/video/rsx_vulkan_backend.c | cat -A | cut -c1-120
