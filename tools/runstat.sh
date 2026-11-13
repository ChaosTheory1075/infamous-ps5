#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# runstat.sh <run name>...: progress of headless runs (log size, frames, last fps, crashes)
for r in "$@"; do
    d=$HOME/if2/runs/$r
    echo "== $r: $(wc -l < $d/run.log) log lines, $(ls $d/frame_*s.ppm 2>/dev/null | wc -l) frames"
    grep 'rsx fps\] [0-9]' $d/run.log | tail -2
    grep -m3 -iE 'segmentation|fatal|abort|\[RSX vulkan\].*(fail|not supported)' $d/run.log
done
