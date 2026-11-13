#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
cat /tmp/rc_build.out
bash ${IF_ROOT:-$HOME/inFamous}/tools/ps5/build_recharged.sh
for g in if1 if2 fob; do echo "$g lfq=$(strings $HOME/if2/ps5/build-$g/Infamous2Recomp.eboot.elf | grep -c 'cellSre_Library') skip=$(strings $HOME/if2/ps5/build-$g/Infamous2Recomp.eboot.elf | grep -c 'skipped movie')"; done
