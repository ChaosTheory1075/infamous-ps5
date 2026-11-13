#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# jr_ab_if2.sh <name> <capdir> [reps] [GAME=if2|fob]: replay captured SPU jobs on the current BC-250 build of
# GAME (default if2), print totals and digest diffs vs <capdir>/base_dig.txt (written if missing).
n=$1; cap=$2; reps=${3:-50}; g=${GAME:-if2}
export PATH="$HOME/inFamous/lle/bin:$PATH"
RUNSH=$HOME/$g/infamous2-lle/run.sh timeout 300 bash ~/inFamous/tools/if2_run.sh $n 280 INFAMOUS2_EXE=$HOME/$g/infamous2-lle/build-zen2/Infamous2Recomp \
  PS3_SPU_JR=1 PS3_SPU_JR_REPLAY=$cap:$reps $JR_EXTRA > /dev/null 2>&1
L=$HOME/if2/runs/$n/run.log
grep -a '^\[jr-replay\]' $L | grep -v MISMATCH | grep -o -E '^\[jr-replay\] [^:]+:.*final [0-9A-F]+' | sed -E 's/\[jr-replay\] ([^:]+):.*event digest ([0-9A-F]+).*final ([0-9A-F]+)/\1 \2 \3/' | sed "s|$cap/||" > /tmp/$n.dig
[ -f $cap/base_dig.txt ] || cp /tmp/$n.dig $cap/base_dig.txt
echo "$n: $(grep -a 'files, total' $L | sed 's/\[jr-replay\] //'); mismatches: $(grep -a -c MISMATCH $L); digest diffs vs base: $(diff $cap/base_dig.txt /tmp/$n.dig | grep -c '^[<>]')"
