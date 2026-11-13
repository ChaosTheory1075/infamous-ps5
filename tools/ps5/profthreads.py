# profthreads.py <log> <unstripped ELF> [thread label substring] [--from S --to S]: the console's
# "[ps5] profile thread" lines resolved per thread label (anchor = ps5_app_setup, +/- offsets).
import bisect, collections, re, subprocess, sys
log, elf = sys.argv[1], sys.argv[2]
want = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith('--') else None
t_from = float(sys.argv[sys.argv.index("--from") + 1]) if "--from" in sys.argv else 0
t_to = float(sys.argv[sys.argv.index("--to") + 1]) if "--to" in sys.argv else 1e12
syms = []
for line in subprocess.run(["nm", "-n", "-C", "--defined-only", elf], capture_output=True, text=True).stdout.splitlines():
    p = line.split(" ", 2)
    if len(p) == 3 and p[1] in "tTwW": syms.append((int(p[0], 16), p[2]))
addrs = [a for a, _ in syms]
anchor = next(a for a, n in syms if n.startswith("ps5_app_setup"))
def name(off):
    i = bisect.bisect_right(addrs, anchor + off) - 1
    return syms[i][1][:90] if i >= 0 else "?"
LINE = re.compile(r"\[ps5\] profile thread \d+ \(([^)]*)\): ([\d.]+)% of samples \(~([\d.]+) cores\) \|(.*)")
ENT = re.compile(r"([\d.]+)% (anchor([+-]\d+)|outside|\(library\)|[\w?.]+)")
UP = re.compile(r"\[ps5\] status: up (\d+)s")
t = 0; per = collections.defaultdict(collections.Counter); cores = collections.Counter(); nrep = collections.Counter()
for l in open(log, errors="replace"):
    m = UP.search(l)
    if m: t = int(m.group(1)); continue
    m = LINE.search(l)
    if not m or not (t_from <= t <= t_to): continue
    lab, share, cr, rest = m.group(1), float(m.group(2)), float(m.group(3)), m.group(4)
    if want and want not in lab: continue
    cores[lab] += cr; nrep[lab] += 1
    for e in ENT.finditer(rest):
        pct, what, off = float(e.group(1)), e.group(2), e.group(3)
        per[lab][name(int(off)) if off is not None else what] += pct * cr / 100.0
for lab, c in sorted(cores.items(), key=lambda kv: -kv[1]):
    print("== %s: %.2f cores avg over %d reports" % (lab, c / nrep[lab], nrep[lab]))
    tot = sum(per[lab].values())
    for k, v in per[lab].most_common(22): print("  %5.1f%%  %s" % (100 * v / c, k))
