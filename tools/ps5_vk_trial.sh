#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
TRI=$HOME/mp3build/tri
SDK=$TRI/.deps/native/ps5-payload-sdk
TK=$HOME/if2/ps3recomp-fork
PS5_PAYLOAD_SDK=$SDK sh $TRI/tooling/prospero-clang18 -std=gnu11 -O1 -DPS3RECOMP_RSX_VULKAN -dM -E -x c /dev/null | grep -E "PROSPERO|__FreeBSD__|__ORBIS" | head
PS5_PAYLOAD_SDK=$SDK sh $TRI/tooling/prospero-clang18 -std=gnu11 -O1 -DPS3RECOMP_RSX_VULKAN \
  -I$TK/include -I$TK/runtime -I$TK/libs -I$TK/libs/video -I$TK/third_party \
  -I$(ls -d $TRI/.deps/pacbrew/*/sysroot)/user/homebrew/include \
  -I${IF_ROOT:-$HOME/inFamous}/deps/Vulkan-Headers/include \
  -include ${IF_ROOT:-$HOME/inFamous}/tools/compat/ps5/ps5_compat.h \
  -c $TK/libs/video/rsx_vulkan_backend.c -o $HOME/if2/ps5trial/vk.o && echo "rsx_vulkan_backend.c OK for PS5"
nm $HOME/if2/ps5trial/vk.o | grep -E " U (dl|SDL_|vk_icd|sce)" | head -20
