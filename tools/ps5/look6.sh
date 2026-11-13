#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
F=$HOME/cdbuild/fw-clean
grep -rlE 'sceUserServiceInitialize|scePadInit|scePadOpen|sceAudioOutInit|SDL_Init\(|sceKernelSetProcessName|sceSysmoduleLoadModule' $F --include=*.cpp --include=*.cc --include=*.c --include=*.h 2>/dev/null | grep -v thirdparty | head -20
