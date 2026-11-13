#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
F=$HOME/if2/ps3recomp-fork/libs/video/rsx_vulkan_backend.c
for l in "$@"; do
  echo "=== line $l in $(awk -v l=$l 'NR<=l && /^[a-z].*\(/ {f=$0} NR==l {print f; exit}' $F | cut -c1-100)"
  sed -n "$((l-6)),$((l+1))p" $F | cut -c1-150
done
