#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Name the anchor offsets of a console log's LAST profile block and LAST wait block with nm.
#   diagsym.sh <log> <if2|fob|if1> [block index from the end, default 1]
L=$1; G=$2; B=${3:-1}
ELF=$HOME/if2/ps5/build-$G/Infamous2Recomp
base=$(nm "$ELF" | awk '$3=="ps5_app_setup"{print $1}')
nm -n "$ELF" | awk '$2 ~ /[tTwW]/ {print $1, $3}' > /tmp/ds.syms
start=$(grep -an 'profile thread 0 (' "$L" | tail -$B | head -1 | cut -d: -f1)
end=$(awk -v s=$start 'NR>s && /\[ps5\] status: up/ {print NR; exit}' "$L"); [ -z "$end" ] && end=$(wc -l < "$L")
sed -n "${start},${end}p" "$L" > /tmp/ds.block
# every "anchor+N" -> name, appended to the line
python3 - "$base" /tmp/ds.syms /tmp/ds.block <<'PY'
import bisect, re, sys
base = int(sys.argv[1], 16)
addrs, names = [], []
for l in open(sys.argv[2]):
    p = l.split(None, 1)
    if len(p) < 2: continue
    addrs.append(int(p[0], 16)); names.append(p[1].strip())
def name(off):
    i = bisect.bisect_right(addrs, base + off) - 1
    return names[i] if i >= 0 else '?'
for l in open(sys.argv[3], errors='replace'):
    l = l.rstrip('\n')
    if 'profile thread' in l:
        head, *parts = l.split(' | ')
        print(head)
        for p in parts:
            m = re.search(r'anchor([+-]\d+)', p)
            print('      ' + p.strip() + ('  ' + name(int(m.group(1))) if m else ''))
    elif l.startswith('[wait]'):
        m = re.search(r'anchor([+-]\d+)', l)
        print(l + ('  ' + name(int(m.group(1))) if m else ''))
PY
