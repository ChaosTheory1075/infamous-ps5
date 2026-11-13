#!/usr/bin/env python3
"""Symbolize and add up the "[ps5] profile thread" lines of a console log (SIGPROF samples every 4 ms
of CPU time, addresses as anchor+offset, anchor = ps5_app_setup) against the PS5 build that ran.

usage: profsym.py <log> <Infamous2Recomp ELF> [--from S] [--to S]
  --from/--to: only the reports whose "[ps5] status: up N s" time is in that range (seconds)
Prints per thread label the share of samples, then the functions by share of all samples, then by
group (SPU job module / runtime function)."""
import bisect, collections, re, subprocess, sys

log, elf = sys.argv[1], sys.argv[2]
t_from = float(sys.argv[sys.argv.index("--from") + 1]) if "--from" in sys.argv else 0
t_to = float(sys.argv[sys.argv.index("--to") + 1]) if "--to" in sys.argv else 1e12

syms = []
for line in subprocess.run(["nm", "-C", "--defined-only", elf], capture_output=True, text=True).stdout.splitlines():
    p = line.split(" ", 2)
    if len(p) == 3 and p[1] in "tTwW":
        syms.append((int(p[0], 16), p[2]))
syms.sort()
addrs = [a for a, _ in syms]
anchor = next(a for a, n in syms if n == "ps5_app_setup")

def name(off):
    i = bisect.bisect_right(addrs, anchor + off) - 1
    return syms[i][1] if i >= 0 else "?"

LINE = re.compile(r"\[ps5\] profile thread \d+ \(([^)]*)\): ([\d.]+)% of samples \(~([\d.]+) cores\) \|(.*)")
ENT = re.compile(r"([\d.]+)% (anchor\+(\d+)|outside|[\w?]+)")
UP = re.compile(r"\[ps5\] status: up (\d+)s")
thr = collections.Counter()
fn = collections.Counter()
fn_thr = collections.defaultdict(collections.Counter)
up = 0
reports = 0
with open(log, "rb") as f:
    for raw in f:
        if b"[ps5] " not in raw:
            continue
        s = raw.decode("utf-8", "replace")
        m = UP.search(s)
        if m:
            up = int(m.group(1))
            continue
        m = LINE.search(s)
        if not m or not (t_from <= up <= t_to):
            continue
        label, share = m.group(1), float(m.group(2))
        label = re.sub(r"\d+$", "", label).rstrip(".") if label.startswith("spu") else label
        thr[label] += share
        reports += 1
        for e in ENT.finditer(m.group(4)):
            pct = float(e.group(1)) * share / 100.0
            n = name(int(e.group(3))) if e.group(3) else e.group(2)
            fn[n] += pct
            fn_thr[label][n] += pct
tot = sum(thr.values()) or 1
print(f"# {reports} thread reports, status time {t_from:g}-{t_to:g} s")
print("## threads (share of all samples)")
for k, v in thr.most_common(25):
    print(f"{100 * v / tot:6.2f}%  {k}")
print("## functions (share of all samples; each thread's report lists only its top entries)")
for k, v in fn.most_common(60):
    print(f"{100 * v / tot:6.2f}%  {k}")
grp = collections.Counter()
for k, v in fn.items():
    g = re.sub(r"_spu_func_[0-9A-F]+$", "", k) if "_spu_func_" in k else k.split("(")[0]
    grp[g] += v
print("## groups")
for k, v in grp.most_common(40):
    print(f"{100 * v / tot:6.2f}%  {k}")
