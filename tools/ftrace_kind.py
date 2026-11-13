"""Spans of one kind in a PS3_FTRACE file: count, total, distribution, by 'who'.
  ftrace_kind.py <trace> <kind>"""
import collections, sys
k = sys.argv[2]
by = collections.defaultdict(list)
for line in open(sys.argv[1]):
    p = line.split()
    if len(p) == 6 and p[0] == k:
        by[p[1]].append((float(p[5]) - float(p[4])) / 1000.0)
for who, d in sorted(by.items()):
    d.sort()
    print(f"who={who}: {len(d)} spans, total {sum(d):.0f} ms, median {d[len(d)//2]:.1f} ms, p90 {d[int(len(d)*.9)]:.1f} ms, max {d[-1]:.1f} ms")
