#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Rebuild everything after a toolkit change: inFamous 2 + FoB on Linux (Vulkan), then both PS5 apps.
T=${IF_ROOT:-$HOME/inFamous}/tools
export INFAMOUS2_CMAKE_ARGS='-DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_CXX_FLAGS=-I'"$HOME"'/if2/compat -DPS3RECOMP_RSX_VULKAN=ON -DPS3RECOMP_VULKAN_INCLUDE_DIR=/usr/include'
bash $T/if2_build.sh --only compile,finish --firmware $HOME/if2/infamous2/fw > $HOME/if2/build-linux.log 2>&1
echo "linux if2: $(grep -E '^(ERROR|DONE)' $HOME/if2/build-linux.log | tail -1)"
bash $T/fob_build.sh --only compile,finish > $HOME/fob/build-linux.log 2>&1
echo "linux fob: $(grep -E '^(ERROR|DONE)' $HOME/fob/build-linux.log | tail -1)"
for g in if2 fob; do
    [ -n "$CLEAN" ] && rm -rf $HOME/if2/ps5/build-$g
    GAME=$g bash $T/ps5/build_if2.sh > $HOME/if2/ps5/build-$g.out 2>&1
    echo "ps5 $g: $(grep 'failed objects' $HOME/if2/ps5/build-$g.out) $(grep -m1 -E 'error:' $HOME/if2/ps5/build-$g.log)"
done
bash $T/ps5/package_if2.sh 2>&1 | tail -1
GAME=fob TITLE_NAME='inFAMOUS: Festival of Blood' CONTENT_TAG=INFAMOUSFOBPS500 \
    ART_SRC=${IF_ROOT:-$HOME/inFamous}/games/fob-us/NPUA80657 \
    bash $T/ps5/package_if2.sh PPSA95461 2>&1 | tail -1
