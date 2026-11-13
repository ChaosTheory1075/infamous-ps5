#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# fslines.sh <run>: [fs]/sys_fs/memory lines with line numbers, next to the scripted presses
grep -nE '^\[fs\]|^\[sys_fs\]|PAD_SCRIPT t=|sys_memory\] allocate\(|sys_ppu_thread_create' $HOME/if2/runs/$1/run.log | cut -c1-170 | tail -${2:-40}
