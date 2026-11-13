#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
export PATH="$HOME/inFamous/lle/bin:$PATH"   # clang 18 (BC-250: system clang is 21)
# A Linux build of one port with the PS5's CPU target (-march=znver2: SSE4.1 shufb, the AVX2 SPU
# float path), in build-zen2 beside the normal build, for timing what the console will run.
#   build_zen2.sh [if2|fob|if1]
G=${1:-if2}
S=$HOME/$G/infamous2-lle
B=$S/build-zen2
[ -n "$NOPATCH" ] || python3 ${IF_ROOT:-$HOME/inFamous}/tools/if2_patch_toolkit.py $HOME/if2/ps3recomp-fork | tail -2
if [ ! -f $B/build.ninja ]; then
  CC=clang CXX=clang++ cmake -S $S -B $B -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DPS3RECOMP_DIR=$HOME/if2/ps3recomp-fork -DPS3RECOMP_RSX_VULKAN=ON -DPS3RECOMP_VULKAN_INCLUDE_DIR=/usr/include \
    -DPython3_EXECUTABLE=$HOME/if2/.venv/bin/python -DSDL2_DIR=/usr/lib/x86_64-linux-gnu/cmake/SDL2 \
    -Dglslang_DIR=/usr/lib/x86_64-linux-gnu/cmake/glslang \
    "-DCMAKE_C_FLAGS=-march=znver2" "-DCMAKE_CXX_FLAGS=-I$HOME/if2/compat -march=znver2" > /tmp/zen2-cfg-$G.log 2>&1 \
    || { tail -30 /tmp/zen2-cfg-$G.log; exit 1; }
fi
cmake --build $B -j $(nproc) -- -k 0 > /tmp/zen2-build-$G.log 2>&1
echo "$G zen2: rc=$? failed=$(grep -c '^FAILED' /tmp/zen2-build-$G.log) $(tail -1 /tmp/zen2-build-$G.log)"
