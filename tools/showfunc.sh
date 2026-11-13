#!/bin/bash
# showfunc.sh <lift dir> <hex addr> [lines]: print a lifted PPU function (func_XXXXXXXX) from the lift.
d=$1; a=$(printf "%08X" $((16#${2#0x}))); n=${3:-120}
f=$(grep -l "^void func_$a(ppu_context\* ctx)" $d/ppu_recomp_*.cpp 2>/dev/null | head -1)
[ -z "$f" ] && f=$(grep -l "func_$a(ppu_context\* ctx)$" $d/ppu_recomp_*.cpp 2>/dev/null | head -1)
[ -z "$f" ] && { echo "func_$a not found"; exit 1; }
l=$(grep -n "func_$a(ppu_context\* ctx)" "$f" | grep -v ';' | head -1 | cut -d: -f1)
sed -n "${l},$((l + n))p" "$f"
