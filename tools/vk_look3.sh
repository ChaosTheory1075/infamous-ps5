#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
cd $HOME/if2/ps3recomp-fork/libs/video
n=$(grep -n 'typedef struct vk_eng_obj' rsx_vulkan_backend.c | cut -d: -f1)
sed -n "${n},$((n+16))p" rsx_vulkan_backend.c
