#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# play_box.sh <fob|if2>: ONE clean live run for the user at the BC-250 (fullscreen, real pad, their save, console env).
# While the black box is on screen: hold SELECT + R3 (both stick clicks on a DualSense: L3 + R3) for ~1 s ->
# screenshots in ~/if2/runs/box_<g>/snaps/ AND the draw list of those frames in run.log ("[cap]" lines).
# Quit with the window's close button or `pkill -x Infamous2Recomp`.
g=${1:-fob}; W=~/inFamous/work
case $g in fob) gd=$HOME/fob/gamedata_user;; if2) gd=$HOME/if2/gamedata_save;; *) echo "fob or if2"; exit 1;; esac
S=$HOME/if2/runs/box_${g}_snaps; mkdir -p $S; rm -f $S/*.ppm
cd ~
BC_CORES=all RUNSH=$HOME/$g/infamous2-lle/run.sh bash ~/inFamous/tools/if2_run.sh box_$g 7200 \
  INFAMOUS2_EXE=$HOME/$g/infamous2-lle/build-zen2-pgouse/Infamous2Recomp PS3_GAMEDATA_ROOT=$gd \
  $($W/console_env.sh $g) PS3RECOMP_VK_WINDOW=1 PS3RECOMP_VK_FULLSCREEN=1 PS3_PAD_SDL=1 PS3_SNAP_DIR=$S PS3RECOMP_VK_DUMP_EVERY=0
