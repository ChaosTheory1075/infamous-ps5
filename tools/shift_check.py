"""Is the US EBOOT the EU one shifted? Pairs the two sorted function lists and histograms the deltas.

usage: shift_check.py <US functions.json> <port source dir>...
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

us = sorted(int(f["start"], 16) for f in json.load(open(sys.argv[1])))
eu = set()
for root in sys.argv[2:]:
    for p in Path(root).rglob("*.patch"):
        for m in re.finditer(r"func_([0-9A-Fa-f]{8})\b", p.read_text(errors="ignore")):
            eu.add(int(m.group(1), 16))
eu = sorted(eu)
print(f"EU functions defined in the patches: {len(eu)}, US: {len(us)}")
if not eu:
    sys.exit()

# For every EU function take the delta to the nearest US start at the same rank (+-20).
deltas = Counter()
j = 0
for i, a in enumerate(eu):
    k = min(len(us) - 1, int(i * len(us) / len(eu)))
    best = min(us[max(0, k - 20):k + 21], key=lambda b: abs(b - a))
    deltas[best - a] += 1
print("most common deltas (US - EU):")
for d, n in deltas.most_common(12):
    print(f"  {d:+#x}: {n}")
