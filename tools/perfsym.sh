#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# perfsym.sh <run> [n]: perf top addresses resolved against the binary with nm, grouped by function; plus tids
D=$HOME/if2/perf-$1.data
B=$(ls $HOME/if1/infamous2-lle/build/Infamous2Recomp)
perf script -i $D -F tid,ip,sym 2>/dev/null > /tmp/ps.txt
echo "== by tid"; awk '{print $1}' /tmp/ps.txt | sort | uniq -c | sort -rn | head -12
nm -C --defined-only $B | grep -iE ' [tTwW] ' | sort > /tmp/nm.txt
bias=$((0x${BIAS:-0})); awk '{print $2}' /tmp/ps.txt | python3 -c "
import sys, bisect, collections
syms=[]
for l in open('/tmp/nm.txt'):
    p=l.split(' ',2)
    try: syms.append((int(p[0],16), p[2].strip()))
    except: pass
syms.sort(); keys=[s[0] for s in syms]
c=collections.Counter(); n=0
for l in sys.stdin:
    try: a=int(l.strip(),16)-int(sys.argv[2])
    except: continue
    n+=1
    i=bisect.bisect_right(keys,a)-1
    c[syms[i][1] if i>=0 and 0<=a<0x10000000 else 'kernel/lib']+=1
for s,k in c.most_common(int(sys.argv[1])): print('%5.1f%% %s'%(100*k/n, s[:150]))
" ${2:-40} $bias
