#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# after_press.sh <run> [pattern]: log line kinds after the first scripted press (pattern default t=120.0s)
L=$HOME/if2/runs/$1/run.log
n=$(grep -n "${2:-t=120.0s press}" "$L" | head -1 | cut -d: -f1)
echo "from line $n of $(wc -l < "$L")"
tail -n +"$n" "$L" | grep -vE 'trace port|WAIT|evt\]' | awk '{print $1, $2}' | sort | uniq -c | sort -rn | head -30
