#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# logctx.sh <run> <pattern> [lines before] [lines after]: the run log around the first match of
# <pattern>, without the wait/poll noise.
L=$HOME/if2/runs/$1/run.log
n=$(grep -n -m1 -- "$2" $L | cut -d: -f1)
[ -z "$n" ] && { echo "no match"; exit 1; }
b=${3:-40}; a=${4:-5}
echo "== line $n"
sed -n "$((n > b ? n - b : 1)),$((n + a))p" $L | grep -vE 'WAIT|ch-block|ch-wait|^\[sem\] create|^\s' | cut -c1-220
