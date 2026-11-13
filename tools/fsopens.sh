#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# fsopens.sh <run>: file opens with the pad-script press lines interleaved, last 40
grep -nE 'open\(|fopen|cellFsOpen|PAD_SCRIPT t=' $HOME/if2/runs/$1/run.log | grep -v 'trace' | tail -${2:-40}
