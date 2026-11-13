#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# showlle.sh <game> <module> <hex addr> [lines]: print a lifted firmware function (e.g. liblv2_func_3000C790).
f=$HOME/$1/infamous2-lle/lle/$2
name="${2}_func_$(printf "%08X" $((16#${3#0x})))(ppu_context"
file=$(grep -l "^[a-z ]*$name" $f/*.cpp | head -1)
n=$(grep -n "^[a-z ]*$name" $file | head -1 | cut -d: -f1)
sed -n "${n},$((n + ${4:-120}))p" $file | grep -v '^\s*$' | cut -c1-160
