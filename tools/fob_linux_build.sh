#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Regenerate FoB's GPU hooks, apply the toolkit fragments, then rebuild FoB's normal Linux build.
T=${IF_ROOT:-$HOME/inFamous}/tools
sed -i 's/\r$//' $T/fob_gpu_hooks.sh
bash $T/fob_gpu_hooks.sh $HOME/if2/infamous2-lle $HOME/fob/infamous2-lle || exit 1
cp $HOME/fob/infamous2-lle/gpu_light.c $HOME/fob/infamous2-lle/gpu_ssao.c $HOME/fob/infamous2-lle/ssao_gpu.h $HOME/fob/src/infamous2-lle/
bash $T/apply_patches.sh
cmake --build $HOME/fob/infamous2-lle/build -j 30 -- -k 0 > /tmp/fob-linux-build.log 2>&1
echo "fob linux: rc=$? failed=$(grep -c '^FAILED' /tmp/fob-linux-build.log) $(tail -1 /tmp/fob-linux-build.log)"
grep -m5 -A3 'error:' /tmp/fob-linux-build.log
exit 0
