#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Build and run the SPU float differential test for the AVX2 path (the NEON test, retargeted).
T=$HOME/if2/ps3recomp-fork/runtime/spu/tests
sed -e 's/#if !defined(__ARM_NEON)/#if !defined(SPU_FLOAT_AVX2)/' \
    -e 's/test_spu_float_neon/test_spu_float_avx2/g' \
    -e 's/no NEON, nothing/no AVX2 path, nothing/' \
    -e 's/neon %.1f ns/avx2 %.1f ns/' $T/test_spu_float_neon.c > $T/test_spu_float_avx2.c
cp $T/test_spu_float_avx2.c ${IF_ROOT:-$HOME/inFamous}/tools/test_spu_float_avx2.c
cd $T
clang -O2 -march=${MARCH:-znver2} -I.. -I../.. -I../../.. -I../../../include test_spu_float_avx2.c -o /tmp/tfa -lm 2>&1 | grep -E 'error' | head -20
/tmp/tfa
