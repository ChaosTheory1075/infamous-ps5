#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Relink one PS5 app after a ps5_app.c / ps5_shims.c change (compiled at link time, not by ninja), then repackage.
#   relink_if2.sh [if2|fob|if1]
G=${1:-if2}
T=${IF_ROOT:-$HOME/inFamous}/tools/ps5
rm -f $HOME/if2/ps5/build-$G/Infamous2Recomp $HOME/if2/ps5/build-$G/Infamous2Recomp.eboot.elf
GAME=$G bash $T/build_if2.sh > $HOME/if2/ps5/build-$G.out 2>&1
echo "ps5 $G relink: $(grep 'failed objects' $HOME/if2/ps5/build-$G.out)"
case $G in
  if2) bash $T/package_if2.sh 2>&1 | tail -1 ;;
  fob) GAME=fob TITLE_NAME='inFAMOUS: Festival of Blood' CONTENT_TAG=INFAMOUSFOBPS500 ART_SRC=${IF_ROOT:-$HOME/inFamous}/games/fob-us/NPUA80657 bash $T/package_if2.sh PPSA95461 2>&1 | tail -1 ;;
  if1) GAME=if1 TITLE_NAME='inFAMOUS' CONTENT_TAG=INFAMOUS1PS50000 ART_SRC=${IF_ROOT:-$HOME/inFamous}/games/if1-eu/disc/PS3_GAME bash $T/package_if2.sh PPSA95462 2>&1 | tail -1 ;;
esac
