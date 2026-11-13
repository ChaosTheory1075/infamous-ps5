#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# waitrun.sh <game> [max s]: wait until that game's binary is gone
for i in $(seq ${2:-900}); do pgrep -f "^$HOME/$1/infamous2-lle/build/Infamous2Recomp" >/dev/null || exit 0; sleep 1; done
