#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
F=$HOME/cdbuild/fw-clean
grep -rnE '"/app0|"/data/|freopen|sceKernelReserveVirtualRange|sceKernelMapDirectMemory|sceKernelMapNamedFlexibleMemory|mmap\(' $F/ps5 $F/src 2>/dev/null | grep -v "^.*://" | head -30
ls $F/ps5
