#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
F=$HOME/if2/ps3recomp-fork/libs/video/rsx_vulkan_backend.c
for fn in vk_present_window vk_destroy_image; do
  n=$(grep -nE "^static [a-zA-Z0-9_ ]+\b$fn\(" $F | head -1 | cut -d: -f1)
  echo "=== $fn @ $n"; [ -n "$n" ] && sed -n "${n},$((n+60))p" $F | awk 'NR==1 || !/^static / {print} /^}/ {exit}'
done
n=$(grep -n '^static void vk_cb_present' $F | cut -d: -f1); echo "=== vk_cb_present @ $n"; sed -n "${n},$((n+12))p" $F
grep -n 'static struct {' $F | head; n=$(grep -n '} s_g;' $F | cut -d: -f1); sed -n "$((n-30)),${n}p" $F
grep -n 'eng_active = 1\|s_vk.eng_active =' $F | head
