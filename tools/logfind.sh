#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# logfind.sh <run> <regex> [context]: first matches of a regex in a run log, with line numbers.
grep -naE -m ${4:-10} -C ${3:-0} "$2" $HOME/if2/runs/$1/run.log | cut -c1-220
