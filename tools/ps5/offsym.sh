#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Name anchor offsets (ps5_app_setup-relative): offsym.sh <if1|if2|fob> <off> [off...]
G=$1; shift
ELF=$HOME/if2/ps5/build-$G/Infamous2Recomp
base=$(nm "$ELF" | awk '$3=="ps5_app_setup"{print $1}')
nm -n "$ELF" | awk '$2 ~ /[tTwW]/ {print $1, $3}' > /tmp/os.syms
for o in "$@"; do printf '%s %x\n' "$o" $(( 0x$base + o )); done > /tmp/os.hits
awk 'NR==FNR { a[NR]=strtonum("0x"$1); s[NR]=$2; n=NR; next }
     { v=strtonum("0x"$2); lo=1; hi=n;
       while (lo < hi) { m=int((lo+hi+1)/2); if (a[m] <= v) lo=m; else hi=m-1 }
       printf "%-12s %s+0x%x\n", $1, s[lo], v-a[lo] }' /tmp/os.syms /tmp/os.hits
