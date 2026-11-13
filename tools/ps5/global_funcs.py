"""Whole-run CPU by function from a console log's global "[ps5] profile:" lines (all threads), plus
which eboot code the library ("outside") time is called from.
  global_funcs.py <log> <eboot elf (unstripped link)>"""
import bisect, collections, re, subprocess, sys

log, elf = sys.argv[1], sys.argv[2]
addrs, names, base = [], [], None
for l in subprocess.run(['nm', '-n', elf], capture_output=True, text=True).stdout.split('\n'):
    p = l.split()
    if len(p) == 3 and p[1] in 'tTwW':
        addrs.append(int(p[0], 16)); names.append(p[2])
        if p[2] == 'ps5_app_setup': base = int(p[0], 16)
def name(off):
    i = bisect.bisect_right(addrs, base + off) - 1
    return names[i] if i >= 0 else '?'

fn, out, cal = collections.Counter(), collections.Counter(), collections.Counter()
reports = 0
for l in open(log, errors='replace'):
    m = re.match(r'\[ps5\] profile: +([\d.]+)% anchor([+-]\d+)$', l.strip())
    if m: fn[name(int(m.group(2)))] += float(m.group(1)); continue
    m = re.match(r'\[ps5\] profile: +([\d.]+)% outside eboot', l.strip())
    if m: fn['(outside eboot)'] += float(m.group(1)); continue
    m = re.match(r'\[ps5\] profile: called from +([\d.]+)% anchor([+-]\d+)', l.strip())
    if m: cal[name(int(m.group(2)))] += float(m.group(1)); continue
    if re.match(r'\[ps5\] profile: \d+ samples', l.strip()): reports += 1
print(f"{reports} reports; share of all samples (top-15 lines only, so it sums below 100%):")
for n, v in fn.most_common(30): print(f"  {v / max(reports, 1):5.1f}%  {n}")
print("library time called from:")
for n, v in cal.most_common(15): print(f"  {v / max(reports, 1):5.1f}%  {n}")
