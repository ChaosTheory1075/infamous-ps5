#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
python3 ${IF_ROOT:-$HOME/inFamous}/tools/fix_nl.py
grep -n -A1 'spv\] miss %016' $HOME/if2/ps3recomp-fork/libs/video/rsx_shader_spirv.cpp | cut -c1-110
python3 ${IF_ROOT:-$HOME/inFamous}/tools/if2_patch_toolkit.py $HOME/if2/ps3recomp-fork | tail -3
echo "build-timing: $(grep -c 'pipeline build took' $HOME/if2/ps3recomp-fork/libs/video/rsx_vulkan_backend.c)"
