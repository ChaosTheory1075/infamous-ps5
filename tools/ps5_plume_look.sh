#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
P=$(ls -d $HOME/mp3build/tri/thirdparty/plume* | head -1)
echo "plume: $P"
grep -nE "vk_icdGetInstanceProcAddr|volkInitializeCustom|VK_KHR_display|vkCreateDisplayPlaneSurfaceKHR|__PROSPERO__|SDL_Vulkan_CreateSurface|ps5" $P/plume_vulkan.cpp | head -40
