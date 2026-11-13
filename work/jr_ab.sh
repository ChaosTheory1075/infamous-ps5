#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# jr_ab.sh <name> <aud|all> [reps]: replay the captured jobs on the current BC-250 build and compare with
# the saved baseline digests. Prints total time / Mcycles / Minstructions and the number of digest diffs.
cd ~/inFamous/work
n=$1; set=$2; reps=${3:-50}
X=""; [ "$set" = aud ] && X="PS3_SPU_JR_SPU=2005,2006"
timeout 300 bash bc_if1_spawn.sh $n PS3_IF1_SPURS2_SPUS=2 PS3_SPU_CALL_FAST=1 PS3_SPU_JR=1 $X PS3_SPU_JR_REPLAY=$HOME/if1/jr/$set:$reps $JR_EXTRA > /dev/null 2>&1
L=$HOME/if2/runs/$n/run.log
B=$HOME/if1/jr/base_dig.txt; [ "$set" = aud ] && B=$HOME/if1/jr/aud_base_dig.txt
grep -a '^\[jr-replay\]' $L | grep -v MISMATCH | sed "s|$HOME/if1/jr/$set/||" | grep -o -E '^\[jr-replay\] [^:]+:.*final [0-9A-F]+' | sed -E 's/\[jr-replay\] ([^:]+):.*event digest ([0-9A-F]+).*final ([0-9A-F]+)/\1 \2 \3/' > /tmp/$n.dig
echo "$n ($set): $(grep -a 'files, total' $L | sed 's/\[jr-replay\] //'); digest diffs vs baseline: $(diff $B /tmp/$n.dig | grep -c '^[<>]')"
