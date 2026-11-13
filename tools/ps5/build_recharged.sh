#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# inFamous: ReCharged (PPSA95463): the launcher + the three games built for the combined layout.
T=${IF_ROOT:-$HOME/inFamous}/tools/ps5
bash $T/launcher/build_launcher.sh > $HOME/if2/ps5/launcher.out 2>&1; tail -1 $HOME/if2/ps5/launcher.out
for g in if2 fob if1; do
    GAME=$g bash $T/build_if2.sh > $HOME/if2/ps5/build-$g.out 2>&1
    echo "ps5 $g: $(grep 'failed objects' $HOME/if2/ps5/build-$g.out) $(grep -m1 -E 'error:|undefined symbol' $HOME/if2/ps5/build-$g.log) $(ls -la --time-style=+%H:%M $HOME/if2/ps5/build-$g/Infamous2Recomp.eboot.elf | awk '{print $6}')"
done
echo BUILD-DONE
