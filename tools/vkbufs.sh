#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# vkbufs.sh: the vk_buffer type and every place the Vulkan backend creates a buffer (with its function)
F=$HOME/if2/ps3recomp-fork/libs/video/rsx_vulkan_backend.c
grep -n -A6 'typedef struct' $F | grep -A6 -B1 'VkBuffer' | head -12
grep -n 'vk_create_host_buffer(\|vk_create_buffer(' $F | while IFS=: read n rest; do
  fn=$(head -n $n $F | grep -nE '^(static |int |void |VkImage|u8|const )[^;]*\(' | tail -1 | cut -c1-100)
  echo "$n <- $fn"
done
