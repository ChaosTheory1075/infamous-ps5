#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# wait until the if1t run shows an fps line, a crash, or 3 minutes pass
L=$HOME/if2/runs/if1t/run.log
for i in $(seq 36); do
  sleep 5
  grep -qE '\[rsx fps\]|Segmentation|SIGSEGV|aborted' "$L" 2>/dev/null && break
done
wc -l < "$L"; grep -E '\[rsx fps\]|engine|Segmentation|aborted' "$L" | head -8
