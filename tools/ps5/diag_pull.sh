#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# After a diagnostics run: pull one game's log, trace windows, slow-shader HLSL and the newest shots
# from PPSA95463/<g>/logs into work/diag/<g>, then summarise every trace window.
#   diag_pull.sh <if1|if2|fob>
g=$1
H=ftp://${PS5_IP:?set PS5_IP (tools/local.env)}:2121/data/homebrew/PPSA95463/$g/logs
D=${DIAG_OUT:-$HOME/inFamous/work/diag/$g}
R=$HOME/if2/infamous2-lle/tools/ftrace_report.py
mkdir -p $D/spvmiss $D/shots
log=$(case $g in if1) echo infamous ;; if2) echo infamous2 ;; fob) echo infamousfob ;; esac)
curl -s --max-time 600 -o $D/$log.log $H/$log.log
curl -s --max-time 600 -o $D/$log.prev.log $H/$log.prev.log
for k in $(seq 0 13); do
  curl -s --max-time 900 -f -o $D/ftrace.$k.txt $H/ftrace.$k.txt || rm -f $D/ftrace.$k.txt
done
for f in $(curl -s --max-time 60 $H/spvmiss/ | awk '{print $NF}' | grep hlsl); do
  curl -s --max-time 60 -o $D/spvmiss/$f $H/spvmiss/$f
done
# the newest 24 screenshots, by listing time
curl -s --max-time 60 $H/ | grep 'shot\.' | sort -k6,8 | tail -24 | awk '{print $NF}' | while read f; do
  curl -s --max-time 60 -o $D/shots/$f $H/$f
done
echo "== $g: $(wc -l < $D/$log.log) log lines, $(ls $D/ftrace.*.txt 2>/dev/null | wc -l) trace windows, $(ls $D/spvmiss | wc -l) slow-shader files"
for f in $(ls $D/ftrace.*.txt 2>/dev/null | sort -t. -k2 -n); do
  echo "-- $(basename $f): $(head -1 $f | sed 's/# ps3_ftrace //')"
  python3 -I $R $f --frames 0 2>/dev/null | sed -n '2p'
  python3 -I $R $f --frames 0 2>/dev/null | sed -n '/SPUs (busy)/,/texture upload/p' | grep -v 'wid\|img ' | tr -s ' ' | paste -sd' ' | cut -c1-600
  python3 -I ${IF_ROOT:-$HOME/inFamous}/tools/ftrace_kind.py $f 16
  python3 -I ${IF_ROOT:-$HOME/inFamous}/tools/ftrace_kind.py $f 18 | sed 's/^/fsread /'
done
