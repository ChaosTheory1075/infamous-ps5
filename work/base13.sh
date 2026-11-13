#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# base13.sh <tag> [VAR=value ...]: one 170 s run per game on 13 threads (PS5 6.5 cores), with the console's own
# per-game env (work/console_env.sh). ONLY=fob|if2|if1 limits it; FOB_EXE/IF2_EXE/IF1_EXE pick builds.
[ "$(nproc)" -ge 16 ] || { echo "nproc $(nproc) < 16: 8-core unlock missing (warm reboot)"; exit 1; }
[ "$(df --output=avail -BG / | tail -1 | tr -dc 0-9)" -ge 6 ] || { echo "less than 6 GB free on / -- runs hang at boot"; exit 1; }
T=${1:-b13}; shift
W=~/inFamous/work
P=$( (seq 12 4 72 | awk '{print $1":0x4000"}') | paste -sd,)
P1=$(seq 20 5 60 | awk '{print $1":0x4000"}' | paste -sd,)
# MOVE=1: walk + camera sweeps from 80 s (left stick forward with right stick right/left/up/down, 6 s each,
# repeated to 164 s), so streaming/culling/new geometry are exercised instead of a still scene (user 2026-11-10).
MV=""
if [ -n "$MOVE" ]; then for t in $(seq 80 24 158); do
  MV="$MV,$t:0x810000:6,$((t+6)):0x10000:6,$((t+12)):0x410000:6,$((t+18)):0x50000:6"; done; fi   # horizontal only: up/down looked at sky/ground (cheap)
cd ~
run() { local g=$1 exe=$2 gd=$3 pad=$4; shift 4
  RUNSH=$HOME/$g/infamous2-lle/run.sh bash ~/inFamous/tools/if2_run.sh ${T}_$g 170 INFAMOUS2_EXE=$exe PS3_GAMEDATA_ROOT=$gd \
    PS3RECOMP_VK_DUMP_EVERY=15 PS3RECOMP_VK_WINDOW=1 PS3_PAD_SDL=0 PAD_SCRIPT=$pad$MV $($W/console_env.sh $g) "$@" > /dev/null 2>&1; }
[ -z "$ONLY" -o "$ONLY" = fob ] && run fob ${FOB_EXE:-$HOME/fob/infamous2-lle/build-zen2-pgouse/Infamous2Recomp} $HOME/fob/gamedata_user $P "$@"
[ -z "$ONLY" -o "$ONLY" = if2 ] && run if2 ${IF2_EXE:-$HOME/if2/infamous2-lle/build-zen2-pgouse/Infamous2Recomp} $HOME/if2/gamedata_save 20:0x4000,25:0x4000,30:0x4000,35:0x4000 "$@"
[ -z "$ONLY" -o "$ONLY" = if1 ] && run if1 ${IF1_EXE:-$HOME/if1/infamous2-lle/build-zen2-pgouse/Infamous2Recomp} $HOME/if1/gamedata_pgo $P1 "$@"
for g in fob if2 if1; do L=$HOME/if2/runs/${T}_$g/run.log; [ -f $L ] || continue
  v=$(grep -a 'rsx fps\] [0-9]' $L | awk '{print $3}' | tail -9)
  echo "${T}_$g: $(echo $v) | avg $(echo "$v" | awk '{s+=$1} END{printf "%.2f", s/NR}') min $(echo "$v" | sort -n | head -1)"; done
