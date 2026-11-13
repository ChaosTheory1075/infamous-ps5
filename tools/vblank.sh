#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# vblank.sh <run>: GCM handler registration lines
grep -iE 'vblank|flip ?handler|SetFlipHandler|SetUserHandler|SecondV|graphics handler' $HOME/if2/runs/$1/run.log | sort | uniq -c | head -20
