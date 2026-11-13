#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# The hottest instructions of one function in a perf recording, with the disassembly around them.
#   perfhot.sh <run> <game> <function> [n]
R=$1; G=$2; FN=$3; NN=${4:-12}
D=$HOME/if2/perf-$R.data; B=$HOME/$G/infamous2-lle/build${BUILD_SUFFIX}/Infamous2Recomp
m=$(perf script -G -i $D --show-mmap-events 2>/dev/null | grep -a 'PERF_RECORD_MMAP' | grep -a "r-xp $B" | head -1)
start=$(echo "$m" | grep -ao '\[0x[0-9a-f]*' | head -1 | tr -d '[')
pgoff=$(echo "$m" | grep -ao '@ 0x[0-9a-f]*' | head -1 | awk '{print $2}')
read off vaddr < <(readelf -lW $B | awk '$1=="LOAD" && $7 ~ /E/ {print $2, $3; exit}')
bias=$(( start - (vaddr + pgoff - off) ))
read lo sz < <(nm -S $B | awk -v f="$FN" '$4==f {print $1, $2; exit}')
lo=$((0x$lo)); hi=$((lo + 0x$sz))
printf '%s: 0x%x-0x%x (%d bytes)\n' $FN $lo $hi $((hi - lo))
perf script -G -i $D -F ip,dso 2>/dev/null | awk -v b=$bias -v lo=$lo -v hi=$hi '/Infamous2Recomp/ { a = strtonum("0x"$1) - b; if (a >= lo && a < hi) c[a]++ } END { for (k in c) printf "%d %x\n", c[k], k }' | sort -rn > /tmp/ph.txt
echo "samples in function: $(awk '{s+=$1} END{print s}' /tmp/ph.txt)"
head -$NN /tmp/ph.txt
top=$(head -1 /tmp/ph.txt | awk '{print $2}')
objdump -d --no-show-raw-insn --start-address=$((0x$top - 120)) --stop-address=$((0x$top + 80)) $B | tail -n +7
