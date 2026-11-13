#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Build and package all three PS5 apps (RECONFIGURE=1 to re-run CMake, e.g. after a glslang change).
T=${IF_ROOT:-$HOME/inFamous}/tools/ps5
G=${IF_ROOT:-$HOME/inFamous}/games
for g in if2 fob if1; do
    GAME=$g bash $T/build_if2.sh > $HOME/if2/ps5/build-$g.out 2>&1
    echo "ps5 $g: $(grep 'failed objects' $HOME/if2/ps5/build-$g.out) $(grep -m1 -E 'error:|undefined symbol' $HOME/if2/ps5/build-$g.log)"
done
bash $T/package_if2.sh 2>&1 | tail -1
GAME=fob TITLE_NAME='inFAMOUS: Festival of Blood' CONTENT_TAG=INFAMOUSFOBPS500 ART_SRC=$G/fob-us/NPUA80657 \
    bash $T/package_if2.sh PPSA95461 2>&1 | tail -1
GAME=if1 TITLE_NAME='inFAMOUS' CONTENT_TAG=INFAMOUS1PS50000 ART_SRC=$G/if1-eu/disc/PS3_GAME \
    bash $T/package_if2.sh PPSA95462 2>&1 | tail -1
