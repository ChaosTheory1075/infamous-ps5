#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Rebuild the Linux test binaries. usage: rebuild_linux.sh if2 fob if1
for d in "$@"; do
  pkill -9 -f "^$HOME/$d/infamous2-lle/build/Infamous2Recomp"
  cd $HOME/$d/infamous2-lle/build || continue
  ninja > /tmp/ninja-$d.log 2>&1
  echo "$d: rc=$? $(tail -1 /tmp/ninja-$d.log)"
done
