#!/bin/bash
# vkdev.sh: Vulkan ICDs present in WSL, /dev/dxg, and the devices vulkaninfo sees
ls /usr/share/vulkan/icd.d/ /dev/dxg 2>&1; ls /usr/lib/wsl/lib 2>&1 | head
which vulkaninfo && vulkaninfo --summary 2>&1 | grep -E 'deviceName|driverName|apiVersion|ERROR' | head
