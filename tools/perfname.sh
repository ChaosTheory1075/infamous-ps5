#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Name a perf recording's samples by function (nm on the binary, the load bias taken from perf's own
# mmap record), overall and for the busiest threads.   perfname.sh <run> <game> [n]
D=$HOME/if2/perf-$1.data; B=$HOME/$2/infamous2-lle/build${BUILD_SUFFIX}/Infamous2Recomp; N=${3:-35}
m=$(perf script -G -i $D --show-mmap-events 2>/dev/null | grep -a 'PERF_RECORD_MMAP' | grep -a "r-xp $B" | head -1)
start=$(echo "$m" | grep -ao '\[0x[0-9a-f]*' | head -1 | tr -d '[')
pgoff=$(echo "$m" | grep -ao '@ 0x[0-9a-f]*' | head -1 | awk '{print $2}')
read off vaddr < <(readelf -lW $B | awk '$1=="LOAD" && $7 ~ /E/ {print $2, $3; exit}')
bias=$(( start - (vaddr + pgoff - off) ))
printf 'map %s pgoff %s seg off %s vaddr %s -> bias 0x%x\n' "$start" "$pgoff" "$off" "$vaddr" $bias
perf script -G -i $D -F tid,ip,dso 2>/dev/null > /tmp/pn.txt
nm -C --defined-only $B | grep -iE ' [tTwW] ' | sort > /tmp/pn.nm
python3 - $N $bias <<'PY'
import sys, bisect, collections
syms = []
for l in open('/tmp/pn.nm'):
    p = l.split(' ', 2)
    try: syms.append((int(p[0], 16), p[2].strip()))
    except: pass
syms.sort(); keys = [s[0] for s in syms]
N = int(sys.argv[1]); bias = int(sys.argv[2])
tot = collections.Counter(); bytid = collections.defaultdict(collections.Counter); tids = collections.Counter()
for l in open('/tmp/pn.txt'):
    p = l.split()
    if len(p) < 2: continue
    tid = p[0]
    try: ip = int(p[1], 16)
    except ValueError: continue
    dso = ' '.join(p[2:])
    tids[tid] += 1
    if 'Infamous2Recomp' in dso:
        a = ip - bias
        i = bisect.bisect_right(keys, a) - 1
        name = syms[i][1] if i >= 0 else '?'
    elif 'kernel' in dso: name = '[kernel]'
    else: name = '[' + dso.split('/')[-1].strip('()') + ']'
    tot[name] += 1; bytid[tid][name] += 1
n = sum(tot.values())
print(f"== all threads ({n} samples)")
for s, k in tot.most_common(N): print(f"{100*k/n:5.1f}% {s[:140]}")
for tid, c in tids.most_common(4):
    m = sum(bytid[tid].values())
    print(f"== thread {tid} ({100*c/n:.0f}% of samples)")
    for s, k in bytid[tid].most_common(22): print(f"   {100*k/m:5.1f}% {s[:130]}")
PY
