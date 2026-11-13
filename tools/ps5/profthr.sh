#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Name the "[ps5] profile thread N: ..." lines of a console log (busiest threads per 15 s, each with
# its three hottest eboot spans) with nm on the matching PS5 link.
#   profthr.sh <log> <if2|fob|if1>
L=$1; G=${2:-if2}
ELF=$HOME/if2/ps5/build-$G/Infamous2Recomp
base=$(nm "$ELF" | awk '$3=="ps5_app_setup"{print $1}')
nm -n "$ELF" | awk '$2 ~ /[tTwW]/ {print $1, $3}' > /tmp/profthr.syms
grep -a 'profile thread' "$L" | while IFS= read -r line; do
  out=$(echo "$line" | sed -E 's/^.*(profile thread)/\1/; s/ \|.*//')
  for m in $(echo "$line" | grep -oE '[0-9.]+% (anchor[+-][0-9]+|outside)' | tr ' ' '_'); do
    pct=${m%%_*}; what=${m#*_}
    if [ "$what" = outside ]; then out="$out | $pct outside"; continue; fi
    a=$(( 0x$base + ${what#anchor} ))
    name=$(awk -v a=$a 'BEGIN{best="?"} { v=strtonum("0x"$1); if (v<=a) best=$2; else {print best; exit} }' /tmp/profthr.syms)
    out="$out | $pct $(echo $name | cut -c1-60)"
  done
  echo "$out"
done
