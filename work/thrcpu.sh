#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# thrcpu.sh <tag> [VAR=value ...]: one base13 run (G=if2|fob|if1, default if2; MOVE=1) and the CPU time each thread used
# per game frame between 95 s and 165 s of the run (from /proc/<pid>/task/*/stat). For RSX-thread work the BC-250's fps
# says nothing (the BC is not RSX-bound, the console is): compare the RSX thread's ms/frame instead.
T=${1:?tag}; shift; G=${G:-if2}
W=${IF_ROOT:-$HOME/inFamous}/work; O=$HOME/if2/runs/thrcpu_$T; mkdir -p $O
snap() { for d in /proc/$1/task/*; do
    c=$(cat $d/comm 2>/dev/null) || continue
    s=$(cat $d/stat 2>/dev/null) || continue
    s=${s##*) }; set -- $1 $s; echo "${d##*/} ${c// /_} $(( ${13} + ${14} ))"; shift $#; set -- $P; done; }
( cd ~; MOVE=1 ONLY=$G bash $W/base13.sh $T "$@" > $O/base13.out 2>&1 ) &
BP=$!
sleep 95
P=$(pgrep -f "^$HOME/$G/infamous2-lle/build-zen2-pgous[e]/Infamous2Recomp" | head -1)
[ -n "$P" ] || { echo "no game process"; wait $BP; exit 1; }
set -- $P; snap $P > $O/s0.txt; f0=$(grep -ac 'rsx fps\] [0-9]' $HOME/if2/runs/${T}_$G/run.log)
sleep 70
set -- $P; snap $P > $O/s1.txt
wait $BP
python3 - $O $HOME/if2/runs/${T}_$G/run.log $f0 <<'PY'
import sys,re,os
o,log,f0=sys.argv[1],sys.argv[2],int(sys.argv[3])
hz=os.sysconf('SC_CLK_TCK')
def rd(f):
    d={}
    for l in open(f):
        p=l.split()
        if len(p)==3: d[p[0]]=(p[1],int(p[2]))
    return d
a,b=rd(o+'/s0.txt'),rd(o+'/s1.txt')
fps=[float(l.split()[2]) for l in open(log,errors='replace') if re.match(r'\[rsx fps\] [0-9]',l)]
win=fps[f0:f0+14] or fps[-14:]
avg=sum(win)/len(win); frames=avg*70.0
rows=[]
for t,(n,v) in b.items():
    if t in a: rows.append(((v-a[t][1])/hz*1000.0/frames, n, t))
rows.sort(reverse=True)
print('fps in window %.2f (all: avg %.2f min %.2f)'%(avg, sum(fps[-9:])/len(fps[-9:]), min(fps[-9:])))
print('thread CPU ms per frame: '+'  '.join('%s %.2f'%(n,ms) for ms,n,t in rows[:12]))
print('total %.1f ms/frame'%sum(r[0] for r in rows))
PY
