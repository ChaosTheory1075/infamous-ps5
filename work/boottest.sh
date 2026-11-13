#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# boottest.sh <game> <n> <tag> [VAR=val..]: n boots of 100 s at 13 threads with the console env; counts load stalls
# (any "[evq kick] #" line or no world frames after 100 s) and "changed with no LR raised" lines.
g=$1; n=$2; T=$3; shift 3
case $g in fob) gd=$HOME/fob/gamedata_user; P=$( (seq 12 4 72 | awk '{print $1":0x4000"}') | paste -sd,);;
           if2) gd=$HOME/if2/gamedata_save; P=20:0x4000,25:0x4000,30:0x4000,35:0x4000;;
           if1) gd=$HOME/if1/gamedata_pgo; P=$(seq 20 5 60 | awk '{print $1":0x4000"}' | paste -sd,);; esac
st=0
for i in $(seq 1 $n); do
  RUNSH=$HOME/$g/infamous2-lle/run.sh bash ~/inFamous/tools/if2_run.sh ${T}_${g}_$i 100 INFAMOUS2_EXE=$HOME/$g/infamous2-lle/build-zen2-pgouse/Infamous2Recomp \
    PS3_GAMEDATA_ROOT=$gd PS3RECOMP_VK_WINDOW=1 PS3RECOMP_VK_DUMP_EVERY=15 PS3_PAD_SDL=0 PAD_SCRIPT=$P $(~/inFamous/work/console_env.sh $g) "$@" > /dev/null 2>&1
  L=$HOME/if2/runs/${T}_${g}_$i/run.log
  k=$(grep -a -c '\[evq kick\] #' $L); w=$(grep -a 'rsx fps\] [0-9]' $L | awk '$3<40' | wc -l); nl=$(grep -a -c 'changed with no LR raised' $L)
  s=0; [ $k -gt 0 ] && s=1; st=$((st+s))
  echo "$T $g #$i: stall=$s kicks=$k worldwins=$w noLR=$nl fps=$(grep -a 'rsx fps\] [0-9]' $L | awk '{print $3}' | tail -2 | tr '\n' ' ')"
done
echo "$T $g: $st stalls in $n boots"
