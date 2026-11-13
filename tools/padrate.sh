#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# padrate.sh <run>...: pad reads per second over the run (runs of equal values collapsed)
for r in "$@"; do echo "== $r"; grep 'trace port 0' $HOME/if2/runs/$r/run.log | awk '{print $5, $NF}' | uniq -c | tail -15; done
