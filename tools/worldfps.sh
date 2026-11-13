#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# World-frame rates (lines with at least one world frame) of each run: worldfps.sh <run> ...
for r in "$@"; do
    echo "$r: $(grep -a 'rsx fps\] [0-9]' $HOME/if2/runs/$r/run.log | grep -v ' 0 world' | awk '{print $3}' | tail -14 | tr '\n' ' ')"
done
