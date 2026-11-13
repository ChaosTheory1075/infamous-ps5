#!/usr/bin/env python3
"""Hitches in a PS3_FTRACE window: every frame much longer than the median, with what grew in it.

  tools/ftrace_hitch.py <trace.txt> [--min-ms 100] [--top 6]

A hitch is a frame over --min-ms and over twice the median. For each one, the accounts of
ftrace_report.py (PPU blocking per thread and call site, SPU busy, RSX drain / present / GPU wait /
first-use compile / texture upload) are compared with their mean over the ordinary frames (under
1.5x the median), and the largest increases are listed. A PPU thread whose blocking grew is waiting
on someone; an RSX account that grew is the render thread's own time.
"""
import argparse
import collections
import os
import statistics
import sys

sys.path.insert(0, __import__("os").path.expanduser("~") + "/if2/infamous2-lle/tools")
import ftrace_report as fr   # noqa: E402


def frame_accounts(spans, frames, names):
    out = []
    j0 = 0
    for f0, f1 in frames:
        acc = collections.defaultdict(float)
        while j0 < len(spans) and spans[j0][5] < f0 - 5000:
            j0 += 1
        for k, who, a, b, t0, t1 in spans[j0:]:
            if t0 > f1:
                break
            o = fr.overlap(t0, t1, f0, f1)
            if o <= 0:
                continue
            tn = names.get(who, str(who))
            if k == fr.USLEEP:
                acc[f"ppu {tn} usleep@{b:08X}"] += o
            elif k == fr.SYSCALL:
                acc[f"ppu {tn} {fr.SYSCALL_NAMES.get(a, 'sc%d' % a)}@{b:08X}"] += o
            elif k == fr.SPU_BUSY:
                acc["spu busy (all)"] += o
                acc[f"spu busy img {a}"] += o
            elif k == fr.SPU_WAIT:
                acc["spu wait (all)"] += o
            elif k in (fr.SEMA, fr.SEMA_GAVEUP):
                acc["rsx acquire wait"] += o
            elif k == fr.DRAIN:
                acc["rsx drain"] += o
            elif k == fr.PRESENT:
                acc["rsx present"] += o
            elif k == fr.GPU_WAIT:
                acc["rsx " + fr.GPU_WAIT_KIND.get(a, "gpu wait")] += o
            elif k == fr.READBACK:
                acc["rsx readback"] += o
            elif k == fr.COMPILE and who == 0:
                acc["rsx first-use compile"] += o
            elif k == fr.TEXUP:
                acc["rsx texture upload"] += o
            elif k == 18:
                acc[f"fs read ({tn})"] += o
        out.append(acc)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace", nargs="+")
    ap.add_argument("--min-ms", type=float, default=100.0)
    ap.add_argument("--top", type=int, default=6)
    args = ap.parse_args()
    for path in args.trace:
        header, names, spans = fr.load(path)
        flips = [s[4] for s in spans if s[0] == fr.FLIP_REQ]
        if len(flips) < 3:
            print(f"{os.path.basename(path)}: fewer than 3 flips")
            continue
        frames = list(zip(flips, flips[1:]))
        durs = [b - a for a, b in frames]
        med = statistics.median(durs)
        accs = frame_accounts(spans, frames, names)
        normal = [i for i, d in enumerate(durs) if d < 1.5 * med]
        base = collections.defaultdict(float)
        for i in normal:
            for key, v in accs[i].items():
                base[key] += v / len(normal)
        hitches = [i for i, d in enumerate(durs) if d > args.min_ms and d > 2 * med]
        print(f"== {os.path.basename(path)}: {len(frames)} frames, median {med:.1f} ms, "
              f"{len(hitches)} hitches over {max(args.min_ms, 2 * med):.0f} ms")
        # A PPU thread blocked most of an ordinary frame is idle; its waits only grow with the frame.
        blocked = collections.defaultdict(float)
        for key, v in base.items():
            if key.startswith("ppu "):
                blocked[key.rsplit(" ", 1)[0]] += v
        idle = {t for t, v in blocked.items() if v > 0.8 * med}
        for i in hitches:
            run = {t: durs[i] - sum(v for key, v in accs[i].items() if key.rsplit(" ", 1)[0] == t)
                   for t in blocked if t not in idle}
            grew = sorted(((v - base.get(key, 0.0), key, v) for key, v in accs[i].items()
                           if key.rsplit(" ", 1)[0] not in idle), reverse=True)
            grew += [(r - (med - blocked[t]), t + " running", r) for t, r in run.items()]
            grew.sort(reverse=True)
            parts = [f"{key} {v:.0f} (+{d:.0f})" for d, key, v in grew[:args.top] if d > 5]
            print(f"  t={frames[i][0] / 1000:.2f}s {durs[i]:.0f} ms: " + "; ".join(parts))


if __name__ == "__main__":
    main()
