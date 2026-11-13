#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Read a console PS3_FTRACE timeline: the frame report, the gap analysis, and the Vulkan GPU waits
# grouped by the code that forced them (the span's b = low 32 bits of the caller's address, named
# through the log's "anchor" line and nm on the matching PS5 link).
#   ftrace_console.sh <game: if2|fob|if1> [dir with ftrace.txt and <log>.log; default: latest fetch]
G=${1:-if2}
D=${2:-$(cat /tmp/ftrace_last 2>/dev/null)}
case $G in if2) L=infamous2;; fob) L=infamousfob;; if1) L=infamous;; esac
T=$D/ftrace-$G.txt; [ -f $T ] || T=$D/ftrace.txt
echo "== $T"
cd $HOME/if2/infamous2-lle && python3 tools/ftrace_report.py $T --frames 2 --ms-per-col 4 | cut -c1-200 | head -70
python3 ${IF_ROOT:-$HOME/inFamous}/tools/ftrace_gaps.py $T | head -40
ELF=$HOME/if2/ps5/build-$G/Infamous2Recomp
anchor=$(grep -ao 'ps5_app_setup at [0-9a-fx]*' $D/$L.log | head -1 | awk '{print $3}')
base=$(nm $ELF | awk '$3=="ps5_app_setup"{print $1}')
echo "== GPU waits by caller (anchor $anchor, nm ps5_app_setup 0x$base)"
nm -n $ELF | awk '$2 ~ /[tTwW]/ {print $1, $3}' > /tmp/fc.syms
awk '$1==12 {n[$4]++; t[$4]+=$6-$5} END{for (k in n) printf "%s %d %.1f\n", k, n[k], t[k]/1000}' $T | sort -k3 -rn | head -15 |
while read b cnt ms; do
  a=$(( (0x$b - (anchor & 0xFFFFFFFF) + 0x$base) & 0xFFFFFFFF ))
  name=$(awk -v a=$a 'BEGIN{best="?"} { v=strtonum("0x"$1); if (v<=a) best=$2; else {print best; exit} }' /tmp/fc.syms)
  printf '%6d waits %9.1f ms  0x%08x  %s\n' $cnt $ms $a "$name"
done
