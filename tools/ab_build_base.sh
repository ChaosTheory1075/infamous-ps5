#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Keep the current zen2 binary as /tmp/ab/new, rebuild from the .orig lifted sources as /tmp/ab/base,
# then put the transformed sources back (rebuilding new again).
S=$HOME/if2/infamous2-lle/spu
T=${IF_ROOT:-$HOME/inFamous}/tools
mkdir -p /tmp/ab
cp $HOME/if2/infamous2-lle/build-zen2/Infamous2Recomp /tmp/ab/new
for f in $S/*/spu_recomp.c; do [ -f $f.orig ] && { mv $f $f.rc; cp $f.orig $f; }; done
bash $T/build_zen2.sh if2 | tail -1
cp $HOME/if2/infamous2-lle/build-zen2/Infamous2Recomp /tmp/ab/base
for f in $S/*/spu_recomp.c; do [ -f $f.rc ] && mv $f.rc $f; done
echo "base and new ready"; ls -la /tmp/ab
