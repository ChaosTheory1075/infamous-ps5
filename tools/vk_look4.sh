#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
F=$HOME/if2/ps3recomp-fork/libs/video/rsx_vulkan_backend.c
sed -n 505,575p $F
for fn in vk_eng_submit_and_wait vk_eng_bind_vs_constants vk_eng_bind_ps_constants vk_eng_present vk_eng_readback vk_eng_ensure_indices vk_destroy_buffer; do
  n=$(grep -nE "^static [a-zA-Z0-9_ ]+\b$fn\(" $F | head -1 | cut -d: -f1)
  echo "=== $fn @ $n"; [ -n "$n" ] && sed -n "${n},$((n+30))p" $F | awk 'NR==1 || !/^static / {print} /^}/ {exit}'
done
