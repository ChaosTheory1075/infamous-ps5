#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Relink everything and check each eboot carries the diagnostics.
bash ${IF_ROOT:-$HOME/inFamous}/tools/ps5/build_recharged.sh | grep -v '^$'
for g in if1 if2 fob; do
  E=$HOME/if2/ps5/build-$g/Infamous2Recomp.eboot.elf
  printf '%s: ' $g
  for s in 'spvmiss' '[wait] site' 'PS3_FTRACE_EVERY' 'flush sites' 'pipeline build took' '[spv] miss' 'polls instead of blocking' 'host main / rsx'; do
    printf '%s=%s ' "$s" "$(strings $E | grep -cF "$s")"
  done
  echo
done
