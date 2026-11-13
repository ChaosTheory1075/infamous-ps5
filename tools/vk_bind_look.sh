#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
cd $HOME/if2/ps3recomp-fork/libs/video
grep -n "RSX_SPIRV_TEXTURE_BINDING\|RSX_SPIRV_SAMPLER_BINDING\|RSX_SPIRV_.*BINDING" rsx_shader_spirv.h
grep -nE "register\(t(1[6-9]|[2-9][0-9])|register\(s(1[6-9])|: register\(t\" ?|t%u|\"t\" *#" rsx_fp_decompiler.c | head -20
grep -nE "VK_ENG_TEX_SLOTS|binding *= *|descriptorCount|bindingCount" rsx_vulkan_backend.c | head -30
