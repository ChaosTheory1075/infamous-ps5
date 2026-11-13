#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
I=$HOME/mp3build/tri/.deps/native/ps5-payload-sdk/target/include
grep -rnE "sceKernelAllocateDirectMemory|sceKernelMapNamedDirectMemory|sceKernelMapDirectMemory|sceKernelGetDirectMemorySize|sceKernelReserveVirtualRange|SCE_KERNEL_WB_ONION|SCE_KERNEL_PROT_CPU_RW|SCE_KERNEL_PROT_CPU_READ|SCE_KERNEL_MAIN_DMEM_SIZE" $I | head -20
