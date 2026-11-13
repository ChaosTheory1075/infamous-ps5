#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Name the addresses of the LAST "[ps5] profile thread N" block of a console log.
#   profthr_sym.sh <log> <if2|fob|if1>
L=$1; G=$2
ELF=$HOME/if2/ps5/build-$G/Infamous2Recomp
base=$(nm "$ELF" | awk '$3=="ps5_app_setup"{print $1}')
nm -n "$ELF" | awk '$2 ~ /[tTwW]/ {print $1, $3}' > /tmp/pts.syms
last=$(grep -an 'profile thread 0:' "$L" | tail -1 | cut -d: -f1)
sed -n "${last},$((last+7))p" "$L" | while read -r line; do
  t=$(echo "$line" | sed -E 's/.*profile thread ([0-9]+):.*\(~([0-9.]+) cores\).*/T\1 \2c/')
  echo "$line" | grep -oE '[0-9.]+% anchor[+-][0-9]+' | while read pct off; do
     off=${off#anchor}; printf '%s %s %x\n' "$t" "$pct" $(( 0x$base + off ))
  done
done > /tmp/pts.hits
awk 'NR==FNR { a[NR]=strtonum("0x"$1); s[NR]=$2; n=NR; next }
     { v=strtonum("0x"$4); lo=1; hi=n;
       while (lo < hi) { m=int((lo+hi+1)/2); if (a[m] <= v) lo=m; else hi=m-1 }
       printf "%-4s %-6s %6s  %s\n", $1, $2, $3, s[lo] }' /tmp/pts.syms /tmp/pts.hits
