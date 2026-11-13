#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Same-scene A/B: each binary 45 s from boot, ftrace 8-33 s (logos, menu); SPU busy per frame.
# Binaries go under the port's build-ab* dirs so if2_run.sh's pkill pattern can stop them.
T=${IF_ROOT:-$HOME/inFamous}/tools
P=$HOME/if2/infamous2-lle
for b in "$@"; do
  v=${b%[0-9]}
  mkdir -p $P/build-ab$v && cp -u /tmp/ab/$v $P/build-ab$v/Infamous2Recomp
  bash $T/if2_run.sh ab_$b 45 INFAMOUS2_EXE=$P/build-ab$v/Infamous2Recomp PS3_FTRACE=8:25:$HOME/if2/runs/ab_$b/ftrace.txt > /dev/null 2>&1
  awk -v r=$b '$1==10 {f++} $1==4 && $2==8197 {a+=($6-$5)/1000; an++} $1==4 && $2<8197 {o+=($6-$5)/1000}
       END{printf "%-6s frames %d ; spu8197 %.0f ms in %d runs (%.3f ms/run) ; others %.0f ms ; per frame: 8197 %.2f others %.2f\n", r, f, a, an, a/an, o, a/f, o/f}' $HOME/if2/runs/ab_$b/ftrace.txt
done
