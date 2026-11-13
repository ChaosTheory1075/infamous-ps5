#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
D=${IF_ROOT:-$HOME/inFamous}/work/diag
T=${IF_ROOT:-$HOME/inFamous}/tools/ps5/thread_funcs.py
python3 -I $T $D/fob/infamousfob.log $HOME/if2/ps5/build-fob/Infamous2Recomp rsx
python3 -I $T $D/if2/infamous2.log $HOME/if2/ps5/build-if2/Infamous2Recomp rsx
python3 -I $T $D/if1/infamous.log $HOME/if2/ps5/build-if1/Infamous2Recomp rsx
