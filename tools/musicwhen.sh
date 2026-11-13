#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# musicwhen.sh <run>...: when each run opened music / ambience files, next to its scripted presses (first 12)
for r in "$@"; do echo "== $r"; grep -anE "music/|streaming_grains/3|PAD_SCRIPT t=" $HOME/if2/runs/$r/run.log | grep -v 'read fd' | cut -c1-120 | head -14; done
