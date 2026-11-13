#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# vkwaits.sh: each vk_submit_and_wait call site in the Vulkan backend with its enclosing function
F=$HOME/if2/ps3recomp-fork/libs/video/rsx_vulkan_backend.c
sed -n 600,640p $F
grep -n 'vk_submit_and_wait()' $F | while IFS=: read n rest; do
  fn=$(head -n $n $F | grep -nE '^(static |int |void |VkImage|u8|const )[^;]*\(' | tail -1 | cut -c1-110)
  echo "$n <- $fn"
done
