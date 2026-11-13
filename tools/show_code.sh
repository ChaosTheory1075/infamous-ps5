#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# show_code.sh <libsre func> <low16 hex> : context around where that 0x8041xxxx code is built
F=$HOME/fob/infamous2-lle/lle/libsre/libsre_recomp_000.cpp
s=$(grep -n "void libsre_func_$1" $F | cut -d: -f1)
awk -v s=$s 'NR>=s && NR<=s+800' $F > /tmp/f.txt
for n in $(grep -n "| 0x$2;" /tmp/f.txt | cut -d: -f1); do echo "=== at $n"; sed -n "$((n-25)),$((n+3))p" /tmp/f.txt | cut -c1-175; done
