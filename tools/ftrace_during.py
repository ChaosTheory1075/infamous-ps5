"""Spans that overlap the longest span of one kind/who in a PS3_FTRACE file, summed by kind/who.
  ftrace_during.py <trace> <kind> <who>"""
import collections, sys
recs = []
for line in open(sys.argv[1]):
    p = line.split()
    if len(p) == 6 and p[0].isdigit():
        recs.append((int(p[0]), p[1], p[2], p[3], float(p[4]), float(p[5])))
k, w = int(sys.argv[2]), sys.argv[3]
cand = [r for r in recs if r[0] == k and r[1] == w]
if not cand: sys.exit("none")
big = max(cand, key=lambda r: r[5] - r[4])
t0, t1 = big[4], big[5]
print(f"longest kind {k} who {w}: {(t1 - t0) / 1000:.1f} ms at {t0 / 1e6:.3f} s (a={big[2]} b={big[3]})")
tot = collections.Counter(); n = collections.Counter()
for r in recs:
    if r is big: continue
    o = min(r[5], t1) - max(r[4], t0)
    if o > 0:
        tot[(r[0], r[1])] += o / 1000.0; n[(r[0], r[1])] += 1
for (kk, ww), ms in tot.most_common(25):
    print(f"  kind {kk:2d} who {ww:>5s}: {ms:8.1f} ms in {n[(kk, ww)]} spans")
