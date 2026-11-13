#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Fetch the three apps' logs (and frame timelines) from the console (FTP, no auth) into
# Downloads\inFamous\work\console-logs\<stamp>.   ftp_logs.sh   -> prints the folder
H=ftp://${PS5_IP:?set PS5_IP (tools/local.env)}:2121/data/homebrew
D=${IF_ROOT:-$HOME/inFamous}/work/console-logs/$(date +%Y%m%d-%H%M)
mkdir -p $D
for p in "PPSA95460 infamous2 if2" "PPSA95461 infamousfob fob" "PPSA95462 infamous if1"; do
  set -- $p
  for f in $2.log $2.prev.log; do
    curl -s --max-time 60 -o $D/$f "$H/$1/logs/$f" || echo "no $1/logs/$f"
  done
  curl -s --max-time 120 -o $D/ftrace-$3.txt "$H/$1/logs/ftrace.txt" || rm -f $D/ftrace-$3.txt
  [ -s $D/ftrace-$3.txt ] || rm -f $D/ftrace-$3.txt
  # screenshots (PS3RECOMP_VK_DUMP_EVERY): logs/shot.NNN.ppm -> shots-<game>/, newest run's only
  mkdir -p $D/shots-$3
  for s in $(curl -s --max-time 60 "$H/$1/logs/" | grep -oE 'shot\.[0-9]{3}\.ppm' | sort -u); do
    curl -s --max-time 60 -o $D/shots-$3/$s "$H/$1/logs/$s"
  done
  rmdir $D/shots-$3 2>/dev/null
done
ls -la $D
echo $D > /tmp/ftp_logs_last
echo $D > /tmp/ftrace_last
