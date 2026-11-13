#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# For each run: does it hit the libspurs handler assertion, and which SPU faulted first.
for r in "$@"; do
    L=$HOME/if2/runs/$r/run.log
    [ -f $L ] || continue
    a=$(grep -ac 'SPURS is aborted' $L)
    f=$(grep -am1 'stopped (status=.*FAULT' $L | cut -c1-90)
    u=$(grep -am1 'interpreting unlifted LS 0x18BB0' $L | cut -c1-60)
    echo "$r: aborted=$a fault=[$f] 18BB0=[$u]"
done
