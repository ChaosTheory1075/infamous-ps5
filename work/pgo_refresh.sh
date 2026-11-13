#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# pgo_refresh.sh <g>: instrumented build (build-zen2-pgogen, -j4) of the CURRENT tree, one 240 s console-env 13-thread
# run in the city save collecting a profile, merge to ~/<g>/pgo/<g>.profdata (old kept .pre-<date>), clean pgouse rebuild.
g=$1; D=$(date +%Y%m%d-%H%M); R=$HOME/$g/infamous2-lle
cd $R/build-zen2-pgogen && ninja -j4 Infamous2Recomp > $HOME/$g/pgo/gen-$D.log 2>&1 || { echo "$g: pgogen build failed"; tail -5 $HOME/$g/pgo/gen-$D.log; exit 1; }
mkdir -p $HOME/$g/pgo/raw-$D
case $g in fob) gd=$HOME/fob/gamedata_user; P=$( (seq 12 4 72 | awk '{print $1":0x4000"}') | paste -sd,);;
           if2) gd=$HOME/if2/gamedata_save; P=20:0x4000,25:0x4000,30:0x4000,35:0x4000;;
           if1) gd=$HOME/if1/gamedata_pgo; P=$(seq 20 5 60 | awk '{print $1":0x4000"}' | paste -sd,);; esac
cd ~; RUNSH=$R/run.sh bash ~/inFamous/tools/if2_run.sh pgo_$g 240 INFAMOUS2_EXE=$R/build-zen2-pgogen/Infamous2Recomp PS3_GAMEDATA_ROOT=$gd \
  PS3RECOMP_VK_WINDOW=1 PS3RECOMP_VK_DUMP_EVERY=15 PS3_PAD_SDL=0 PAD_SCRIPT=$P $(~/inFamous/work/console_env.sh $g) \
  PS3_PGO_DUMP_S=30 LLVM_PROFILE_FILE=$HOME/$g/pgo/raw-$D/r_%p.profraw > /dev/null 2>&1
ls $HOME/$g/pgo/raw-$D/*.profraw >/dev/null 2>&1 || { echo "$g: no profraw"; exit 1; }
cp $HOME/$g/pgo/$g.profdata $HOME/$g/pgo/$g.profdata.pre-$D
llvm-profdata-18 merge -o $HOME/$g/pgo/$g.profdata $HOME/$g/pgo/raw-$D/*.profraw || { cp $HOME/$g/pgo/$g.profdata.pre-$D $HOME/$g/pgo/$g.profdata; echo "$g: merge failed"; exit 1; }
cd $R/build-zen2-pgouse && ninja -t clean > /dev/null && ninja Infamous2Recomp > $HOME/$g/pgo/use-$D.log 2>&1 && echo "$g: pgo refreshed ($D), mismatches $(grep -c 'hash mismatch' $HOME/$g/pgo/use-$D.log)" || echo "$g: pgouse build failed"
