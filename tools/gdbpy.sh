#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# gdbpy.sh <game> <script.py> [times] [gap s]: run a gdb python probe against a running port a few times.
pid=$(pgrep -f "^$HOME/$1/infamous2-lle/build/Infamous2Recomp")
for i in $(seq 1 ${3:-1}); do
    gdb -q -batch -p $pid -x "$2" 2>&1 | grep -vE '^\[|^(0x|Using|Reading|warning|Download)' | grep -v '^$'
    sleep ${4:-3}
done
