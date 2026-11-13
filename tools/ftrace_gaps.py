#!/usr/bin/env python3
"""What fills the gaps of a PS3_FTRACE trace: per SPU, its channel waits (channel, LS pc,
duration histogram); RSX drain spans (count, durations, how many end on an ACQUIRE); semaphore
ACQUIRE waits (label offset); the main thread's usleep sites.
  ftrace_gaps.py <trace.txt> [spu id]
"""
import collections
import statistics
import sys

path = sys.argv[1]
want_spu = int(sys.argv[2]) if len(sys.argv) > 2 else None
spans = collections.defaultdict(list)
for line in open(path):
    if line.startswith('#') or line.startswith('T '):
        continue
    p = line.split()
    if len(p) != 6:
        continue
    kind, who, a, b, t0, t1 = int(p[0]), int(p[1]), int(p[2], 16), int(p[3], 16), float(p[4]), float(p[5])
    spans[kind].append((who, a, b, t0, t1))


def hist(ds):
    if not ds:
        return "none"
    ds = sorted(ds)
    q = lambda f: ds[min(len(ds) - 1, int(f * len(ds)))]
    return (f"n={len(ds)} total={sum(ds)/1000:.0f} ms  p10={q(.1)/1000:.2f} p50={q(.5)/1000:.2f} "
            f"p90={q(.9)/1000:.2f} max={ds[-1]/1000:.1f} ms")


print("== SPU channel waits (kind 3), by SPU / channel / LS pc")
byk = collections.defaultdict(list)
for who, a, b, t0, t1 in spans[3]:
    if want_spu is None or who == want_spu:
        byk[(who, a, b)].append(t1 - t0)
for k, ds in sorted(byk.items(), key=lambda kv: -sum(kv[1]))[:12]:
    print(f"  spu {k[0]} ch {k[1]} pc 0x{k[2]:05X}: {hist(ds)}")
print("== SPU busy (kind 4), by SPU / image / wid")
byb = collections.defaultdict(list)
for who, a, b, t0, t1 in spans[4]:
    byb[(who, a, b)].append(t1 - t0)
for k, ds in sorted(byb.items(), key=lambda kv: -sum(kv[1]))[:8]:
    print(f"  spu {k[0]} img {k[1]} wid 0x{k[2]:X}: {hist(ds)}")
print("== RSX drains (kind 7)")
print("  ended on ACQUIRE:", hist([t1 - t0 for _, a, _, t0, t1 in spans[7] if a]))
print("  other:           ", hist([t1 - t0 for _, a, _, t0, t1 in spans[7] if not a]))
print("== RSX semaphore ACQUIRE waits (kind 5) / gave up (6), by label offset")
bys = collections.defaultdict(list)
for kind in (5, 6):
    for who, a, b, t0, t1 in spans[kind]:
        bys[(kind, a)].append(t1 - t0)
for k, ds in sorted(bys.items(), key=lambda kv: -sum(kv[1]))[:8]:
    print(f"  kind {k[0]} label 0x{k[1]:X}: {hist(ds)}")
print("== PPU usleep runs (kind 2) and blocking syscalls (kind 1) by thread / site")
byu = collections.defaultdict(list)
for kind in (1, 2):
    for who, a, b, t0, t1 in spans[kind]:
        byu[(kind, who, a if kind == 1 else 0, b)].append(t1 - t0)
for k, ds in sorted(byu.items(), key=lambda kv: -sum(kv[1]))[:12]:
    what = f"syscall {k[2]}" if k[0] == 1 else "usleep"
    print(f"  tid {k[1]} {what} @0x{k[3]:08X}: {hist(ds)}")
# Gap structure of the busiest SPU: busy and idle run lengths in time order.
if spans[4]:
    tot = collections.Counter()
    for who, a, b, t0, t1 in spans[4]:
        tot[who] += t1 - t0
    s = want_spu if want_spu is not None else tot.most_common(1)[0][0]
    bs = sorted((t0, t1) for who, a, b, t0, t1 in spans[4] if who == s)
    gaps = [bs[i + 1][0] - bs[i][1] for i in range(len(bs) - 1)]
    print(f"== spu {s}: busy runs {hist([t1 - t0 for t0, t1 in bs])}")
    print(f"   gaps between busy runs {hist(gaps)}")
