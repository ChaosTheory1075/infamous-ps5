#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Rebuild + package + upload only FoB (PPSA95461), after checking its imports against the console's.
T=${IF_ROOT:-$HOME/inFamous}/tools
G=${IF_ROOT:-$HOME/inFamous}/games
bash $T/apply_patches.sh 2>&1 | grep -E 'appended|patched' | tail -5
GAME=fob bash $T/ps5/build_if2.sh > $HOME/if2/ps5/build-fob.out 2>&1
echo "ps5 fob: $(grep 'failed objects' $HOME/if2/ps5/build-fob.out) $(grep -m1 -E 'error:|undefined symbol' $HOME/if2/ps5/build-fob.log)"
GAME=fob TITLE_NAME='inFAMOUS: Festival of Blood' CONTENT_TAG=INFAMOUSFOBPS500 ART_SRC=$G/fob-us/NPUA80657 \
    bash $T/ps5/package_if2.sh PPSA95461 2>&1 | tail -1
bash $T/ps5/import_diff.sh PPSA95461 fob
grep -c 'spuregs' $HOME/if2/ps5/build-fob/Infamous2Recomp
