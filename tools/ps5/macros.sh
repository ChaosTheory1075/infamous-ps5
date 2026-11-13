#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# macros.sh: which x86 ISA extensions the PS5 compiler and the Linux build compiler enable by default,
# and what this PC's CPU has
echo "== ps5"; echo | sh ${IF_ROOT:-$HOME/inFamous}/tools/ps5/ps5cc -dM -E -x c - 2>&1 | grep -E '__(SSE4_1|SSE4_2|AVX|AVX2|FMA|BMI2|znver|x86_64)__' | sort
echo | sh ${IF_ROOT:-$HOME/inFamous}/tools/ps5/ps5cc -### -x c -c - -o /dev/null 2>&1 | grep -oE '"-target-cpu" "[^"]+"|"-triple" "[^"]+"'
echo "== linux"; grep -E 'CMAKE_C_COMPILER:|CMAKE_CXX_COMPILER:|CMAKE_C_FLAGS:|CMAKE_CXX_FLAGS:|CMAKE_BUILD_TYPE:' $HOME/if1/infamous2-lle/build/CMakeCache.txt
echo | cc -dM -E -x c - | grep -cE '__SSE4_1__'
echo "== cpu"; grep -m1 'model name' /proc/cpuinfo; grep -m1 -oE '\b(avx2|fma|sse4_1|bmi2|avx512f)\b' /proc/cpuinfo | sort -u | tr '\n' ' '; echo
grep -m1 flags /proc/cpuinfo | grep -oE '\b(avx2|fma|sse4_1|bmi2|avx512f)\b' | sort -u | tr '\n' ' '; echo
