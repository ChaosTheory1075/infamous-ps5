#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
cd $HOME/if2/ps3recomp-fork/libs/video
for fn in vk_eng_make_view vk_eng_upload_rows vk_barrier_image vk_eng_bind_pipeline vk_eng_pipeline_create; do
  n=$(grep -nE "^static [a-zA-Z0-9_ ]+\b$fn\(" rsx_vulkan_backend.c | head -1 | cut -d: -f1)
  echo "=== $fn @ $n"; [ -n "$n" ] && sed -n "${n},$((n+40))p" rsx_vulkan_backend.c | awk 'NR==1 || !/^static / {print} /^}/ {exit}'
done
grep -n "s_e2\.\(pipe\|pipeline\)\b\|cur_pipe\|s_e2 = \|} s_e2;" rsx_vulkan_backend.c | head
grep -n "typedef struct vk_eng_pipe\|vk_eng_pipe {" -A12 rsx_vulkan_backend.c | head -20
grep -n "dummy" rsx_vulkan_backend.c | head
