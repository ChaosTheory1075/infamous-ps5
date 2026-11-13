#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Print a C function from the toolkit by name: showfn.sh <name> [lines] [file]
N=$1; L=${2:-120}
F=${3:-$(grep -rln "^[a-zA-Z].*[ *]$N(" --include=*.c --include=*.cpp --include=*.h $HOME/if2/ps3recomp-fork/runtime $HOME/if2/ps3recomp-fork/libs | grep -v '/build\|tests/' | head -1)}
n=$(grep -n "^[a-zA-Z].*[ *]$N(" $F | grep -v ';' | head -1 | cut -d: -f1)
echo "== $F:$n"
sed -n "$n,$((n + L))p" $F
