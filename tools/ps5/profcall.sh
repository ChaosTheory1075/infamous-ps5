#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Name the "[ps5] profile: called from X% anchor+N" lines (eboot callers of the hottest
# library/kernel code) with nm on the matching PS5 link, summed by function.
#   profcall.sh <log> <if2|fob|if1> [n]
L=$1; G=${2:-if2}; N=${3:-25}
ELF=$HOME/if2/ps5/build-$G/Infamous2Recomp
base=$(nm "$ELF" | awk '$3=="ps5_app_setup"{print $1}')
nm -n "$ELF" | awk '$2 ~ /[tTwW]/ {print $1, $3}' > /tmp/profcall.syms
grep -aoE 'called from +[0-9.]+% anchor[+-][0-9]+' "$L" | sed -E 's/called from +([0-9.]+)% anchor([+-][0-9]+)/\1 \2/' |
while read pct off; do printf '%s %x\n' "$pct" $(( 0x$base + off )); done > /tmp/profcall.hits
echo "called-from lines: $(wc -l < /tmp/profcall.hits)"
awk 'NR==FNR { a[NR]=strtonum("0x"$1); s[NR]=$2; n=NR; next }
     { v=strtonum("0x"$2); lo=1; hi=n;
       while (lo < hi) { m=int((lo+hi+1)/2); if (a[m] <= v) lo=m; else hi=m-1 }
       tot[s[lo]] += $1 }
     END { for (k in tot) printf "%8.1f  %s\n", tot[k], k }' /tmp/profcall.syms /tmp/profcall.hits | sort -rn | head -$N
