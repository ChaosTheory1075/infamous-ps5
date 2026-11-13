#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# rsxcpu.sh <g> <tag> [VAR=v ...]: static base13 run; over 30 s of gameplay: fps, CPU ms per frame of the RSX thread (host
# main thread, tid == pid), of the be-async worker and of the whole process. A low-noise metric for RSX-side changes.
g=$1; T=$2; shift 2
ONLY=$g bash ~/inFamous/work/base13.sh $T "$@" > /dev/null 2>&1 &
bpid=$!
until pid=$(pgrep -f "^$HOME/$g/infamous2-lle/build-zen2-pgous[e]/Infamous2Recomp" | head -1); [ -n "$pid" ]; do sleep 2; done
L=$HOME/if2/runs/${T}_$g/run.log
until [ $(grep -a -c 'rsx fps\] [0-9]' $L 2>/dev/null) -ge 9 ]; do sleep 3; kill -0 $pid 2>/dev/null || exit 1; done
snap() { for t in /proc/$pid/task/*; do echo "$(basename $t) $(awk '{print $14+$15}' $t/stat) $(tr ' ' _ < $t/comm)"; done; }
f0=$(grep -a -o "[0-9]* frames in" $L | awk '{s+=$1} END{print s}'); snap > $HOME/if2/runs/${T}_$g.c0; t0=$(date +%s.%N)
sleep 30
f1=$(grep -a -o "[0-9]* frames in" $L | awk '{s+=$1} END{print s}'); snap > $HOME/if2/runs/${T}_$g.c1; t1=$(date +%s.%N)
wait $bpid
python3 - $pid $HOME/if2/runs/${T}_$g.c0 $HOME/if2/runs/${T}_$g.c1 $f0 $f1 $t0 $t1 "$g $T" <<'PY'
import sys
pid,c0,c1,f0,f1,t0,t1,lab=sys.argv[1:9]
a={l.split()[0]:(int(l.split()[1]),l.split()[2]) for l in open(c0)}; b={l.split()[0]:(int(l.split()[1]),l.split()[2]) for l in open(c1)}
dt=float(t1)-float(t0); fr=max(1,int(f1)-int(f0))
tot=sum(b[k][0]-a[k][0] for k in b if k in a)*10.0
rsx=(b[pid][0]-a[pid][0])*10.0 if pid in a and pid in b else 0
ba=sum((b[k][0]-a[k][0])*10.0 for k in b if k in a and b[k][1].startswith('be_async'))
print("%s: frames/s %.1f | per frame: RSX thread %.2f ms, be_async %.2f ms, whole process %.1f ms" % (lab, fr/dt, rsx/fr, ba/fr, tot/fr))
PY
