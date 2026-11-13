#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Apply the toolkit edits and run the x86 SPU helper tests (floats AVX2, quadword bytes SSSE3)
# with the PS5's CPU target.
T=${IF_ROOT:-$HOME/inFamous}/tools
K=$HOME/if2/ps3recomp-fork
sed -i 's/\r$//' $T/patch_spu_bytes_sse.py $T/test_spu_bytes_sse.c
grep -q 'spu bytes ssse3: base' $T/if2_patch_toolkit.py || cat $T/patch_spu_bytes_sse.py >> $T/if2_patch_toolkit.py
python3 $T/if2_patch_toolkit.py $K | tail -12
I="-I$K/runtime/spu -I$K/runtime -I$K -I$K/include"
clang -O2 -march=${MARCH:-znver2} $I $T/test_spu_bytes_sse.c -o /tmp/tsb -lm 2>&1 | grep error | head
/tmp/tsb
bash $T/test_avx2.sh
