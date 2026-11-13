#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# inFamous 1 title test without the Vulkan draw engine: if1_fastrun.sh <name> <secs> [VAR=value ...]
n=$1; s=$2; shift 2
RUNSH=$HOME/if1/infamous2-lle/run.sh exec ${IF_ROOT:-$HOME/inFamous}/tools/if2_run.sh "$n" "$s" PAD_TRACE=1 PAD_SCRIPT=120:0x0008,150:0x0008,180:0x0008,210:0x0008,240:0x0008,270:0x0008,300:0x0008,330:0x0008,360:0x0008,390:0x0008,420:0x0008,450:0x0008,480:0x0008,510:0x0008,540:0x0008,570:0x0008,600:0x0008,630:0x0008,660:0x0008,690:0x0008,720:0x0008,750:0x0008,780:0x0008,810:0x0008,840:0x0008 "$@"
