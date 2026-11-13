#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
F=$HOME/if2/ps3recomp-fork/libs/video/rsx_vulkan_backend.c
E=$HOME/if2/ps3recomp-fork/libs/video/rsx_draw_engine.c
echo "vk_submit_and_wait calls: $(grep -c 'vk_submit_and_wait()' $F)"
echo "vk_destroy_buffer calls: $(grep -c 'vk_destroy_buffer(' $F)"
grep -n 'submit_and_wait' $E | head
grep -n '^static int vk_submit_and_wait\|^static int vk_begin\|^static void vk_eng_submit_and_wait\|^static void vk_eng_bind_vs_constants\|^static void vk_eng_bind_ps_constants\|^static int vk_ensure_vertex_buffer\|^static int vk_eng_ensure_indices\|^static int vk_create_host_buffer' $F
