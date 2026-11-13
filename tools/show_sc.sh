#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# show_sc.sh <libsre func hex> : lines around its sys_event_queue_receive (syscall 130)
F=$HOME/fob/infamous2-lle/lle/libsre/libsre_recomp_000.cpp
s=$(grep -n "void libsre_func_$1" $F | cut -d: -f1)
awk -v s=$s 'NR>=s && NR<=s+800' $F > /tmp/f.txt
grep -n '(0x82)\|(130)' /tmp/f.txt | head
n=$(grep -n '(0x82);\|(130);' /tmp/f.txt | head -1 | cut -d: -f1)
[ -n "$n" ] && sed -n "$((n-40)),$((n+25))p" /tmp/f.txt | cut -c1-170
