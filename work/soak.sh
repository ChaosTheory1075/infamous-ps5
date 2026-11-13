#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# soak.sh <g> <secs> <tag>: console-env 13-thread run with walk + camera sweeps from 80 s to the end; reports fps
# per window (min/avg), evq kicks, crashes. Stability check for the PS5 builds' BC twins.
g=$1; S=$2; T=$3
case $g in fob) gd=$HOME/fob/gamedata_user; P=$( (seq 12 4 72 | awk '{print $1":0x4000"}') | paste -sd,);;
           if2) gd=$HOME/if2/gamedata_save; P=20:0x4000,25:0x4000,30:0x4000,35:0x4000;;
           if1) gd=$HOME/if1/gamedata_pgo; P=$(seq 20 5 60 | awk '{print $1":0x4000"}' | paste -sd,);; esac
MV=""; for t in $(seq 80 24 $((S-24))); do MV="$MV,$t:0x810000:6,$((t+6)):0x10000:6,$((t+12)):0x410000:6,$((t+18)):0x50000:6"; done
cd ~; RUNSH=$HOME/$g/infamous2-lle/run.sh bash ~/inFamous/tools/if2_run.sh ${T}_$g $S INFAMOUS2_EXE=$HOME/$g/infamous2-lle/build-zen2-pgouse/Infamous2Recomp \
  PS3_GAMEDATA_ROOT=$gd PS3RECOMP_VK_WINDOW=1 PS3RECOMP_VK_DUMP_EVERY=30 PS3_PAD_SDL=0 PAD_SCRIPT=$P$MV $(~/inFamous/work/console_env.sh $g) $SOAK_EXTRA > /dev/null 2>&1
L=$HOME/if2/runs/${T}_$g/run.log; v=$(grep -a 'rsx fps\] [0-9]' $L | awk '{print $3}' | tail -n +9)
echo "${T}_$g: windows $(echo "$v" | wc -l) avg $(echo "$v" | awk '{s+=$1} END{printf "%.2f", s/NR}') min $(echo "$v" | sort -n | head -1) kicks $(grep -a -c 'evq kick\] #' $L) crash $(grep -a -c -i 'segmentation\|SIGSEGV\|fatal\|abort' $L) lines $(wc -l < $L)"
