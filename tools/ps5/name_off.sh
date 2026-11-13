#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# name_off.sh <game> <offset>... : the function containing ps5_app_setup+offset
ELF=$HOME/if2/ps5/build-$1/Infamous2Recomp; shift
base=$(nm "$ELF" | awk '$3=="ps5_app_setup"{print $1}')
for o in "$@"; do
  a=$(printf '%x' $(( 0x$base + o )))
  nm -n "$ELF" | awk -v a=$a 'BEGIN{t=strtonum("0x"a)} $2 ~ /[tTwW]/ {v=strtonum("0x"$1); if (v<=t) {n=$3; s=v} else {print n, sprintf("+0x%x", t-s); exit}}' | sed "s/^/$o -> /"
done
