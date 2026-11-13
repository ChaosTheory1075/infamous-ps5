"""Sum one thread's profile entries over every report of a console log, by function.
  thread_funcs.py <log> <eboot elf (unstripped link)> [thread label substring | 'rsx']
'rsx' picks, in each report, the thread whose entries include rsx_process_method."""
import bisect, collections, re, subprocess, sys

log, elf = sys.argv[1], sys.argv[2]
want = sys.argv[3] if len(sys.argv) > 3 else 'rsx'
syms = subprocess.run(['nm', '-n', elf], capture_output=True, text=True).stdout.split('\n')
addrs, names, base = [], [], None
for l in syms:
    p = l.split()
    if len(p) == 3 and p[1] in 'tTwW':
        addrs.append(int(p[0], 16)); names.append(p[2])
        if p[2] == 'ps5_app_setup': base = int(p[0], 16)
def name(off):
    i = bisect.bisect_right(addrs, base + off) - 1
    return names[i] if i >= 0 else '?'

tot = collections.Counter()
blocks = cores = 0.0
for l in open(log, errors='replace'):
    m = re.match(r'\[ps5\] profile thread \d+ \(([^)]*)\): +([\d.]+)% of samples \(~([\d.]+) cores\)(.*)', l)
    if not m: continue
    label, share, c, rest = m.group(1), m.group(2), float(m.group(3)), m.group(4)
    ents = re.findall(r'([\d.]+)% (anchor([+-]\d+)|outside)', rest)
    named = [(float(p), 'outside' if a == 'outside' else name(int(o))) for p, a, o in ents]
    if want == 'rsx':
        if not any(n.startswith('rsx_') for _, n in named): continue
    elif want not in label: continue
    blocks += 1; cores += c
    for p, n in named: tot[n] += p * c / 100.0
print(f"{want}: {blocks:.0f} reports, average {cores / max(blocks, 1):.2f} cores")
for n, v in tot.most_common(30):
    print(f"  {100 * v / max(cores, 1e-9):5.1f}%  {n}")
