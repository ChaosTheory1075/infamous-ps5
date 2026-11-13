#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# release_gate.sh <tag>: BC-250 regression gate for the staged console build's BC twins (same source, console env):
# 10-minute moving soak per game; PASS needs: no crash/abort, 0 evq kicks, no black scene frame, 0 wrong-kind textures,
# no audio dropout lines, fps windows reported. Prints one PASS/FAIL line per game.
T=${1:-gate}; cd ${IF_ROOT:-$HOME/inFamous}
for g in ${GATE_GAMES:-if1 if2 fob}; do
  bash work/soak.sh $g 600 $T > $HOME/if2/runs/${T}_$g.soak 2>&1
  L=$HOME/if2/runs/${T}_$g/run.log
  v=$(grep -a 'rsx fps\] [0-9]' $L | awk '{print $3}' | tail -n +9)
  avg=$(echo "$v" | awk '{s+=$1} END{printf "%.1f", s/NR}'); min=$(echo "$v" | sort -n | head -1); n=$(echo "$v" | wc -l)
  kicks=$(grep -a -c 'evq kick\] #' $L); wk=$(grep -a -c 'wrong-kind texture' $L); crash=$(grep -a -c -i 'SIGSEGV\|SIGABRT\|Segmentation\|abort()\|\[crash\]' $L)
  ex=$(grep -a 'game exit code' $L | awk '{print $NF}'); dirty=$(grep -a -c 'ENG_DIRTY_CHECK FAILED' $L)
  black=$(python3 - "$T" "$g" <<'PY'
import sys,glob
from PIL import Image, ImageStat
fs=sorted(glob.glob(__import__("os").path.expanduser("~") + '/if2/runs/%s_%s/frame.ppm.*.ppm'%(sys.argv[1],sys.argv[2])))
b=0
for f in fs[2:]:   # the first dumps are boot/loading frames
    im=Image.open(f).convert('L'); w,h=im.size
    if ImageStat.Stat(im.crop((0,h//3,w,h*5//6))).mean[0] < 4: b+=1
print("%d/%d"%(b,max(0,len(fs)-2)))
PY
)
  ok=PASS; [ "$n" -ge 40 ] && [ "$kicks" = 0 ] && [ "$wk" = 0 ] && [ "$crash" = 0 ] && [ "${black%%/*}" = 0 ] || ok=FAIL
  echo "$g: $ok | windows $n avg $avg min $min | kicks $kicks wrong-kind $wk crash-lines $crash black-frames $black exit $ex"
done
