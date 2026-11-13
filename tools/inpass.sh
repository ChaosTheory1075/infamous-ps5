#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# inpass.sh: calls made between each vkCmdBeginRenderPass and its vkCmdEndRenderPass in the Vulkan backend
F=$HOME/if2/ps3recomp-fork/libs/video/rsx_vulkan_backend.c
awk '/pvkCmdBeginRenderPass/{inp=1; print "--- pass at " NR} inp && /[a-z_]+\(/{ while (match($0, /(vk_|eng_|rsx_)[a-z0-9_]+\(/)) { print NR ": " substr($0, RSTART, RLENGTH); $0 = substr($0, RSTART + RLENGTH) } } /pvkCmdEndRenderPass/{inp=0}' $F
