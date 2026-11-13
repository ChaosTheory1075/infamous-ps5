#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
F=$HOME/cdbuild/fw-clean
grep -rlE 'sceKernelReserveVirtualRange|sceKernelMapNamedFlexibleMemory|sceKernelMapDirectMemory|sceKernelAllocateDirectMemory' $F --include=*.cc --include=*.cpp --include=*.c --include=*.h 2>/dev/null | head
f=$(grep -rlE 'sceKernelReserveVirtualRange|sceKernelMapNamedFlexibleMemory' $F --include=*.cc --include=*.cpp 2>/dev/null | head -1)
[ -n "$f" ] && grep -nE 'sceKernel[A-Za-z]+\(|mmap\(|MAP_' "$f" | head -40
