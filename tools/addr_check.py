"""Check how many function addresses the EU inFamous port names exist as function starts in another EBOOT.

usage: addr_check.py <functions.json> <port source dir>...
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

funcs = json.load(open(sys.argv[1]))
starts = {int(f["start"], 16) for f in funcs}
toc = funcs[0]["toc"]

names = Counter()
for root in sys.argv[2:]:
    for p in Path(root).rglob("*"):
        if p.suffix not in (".cpp", ".h", ".c", ".patch", ".json", ".toml") or not p.is_file():
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        for m in re.finditer(r"func_([0-9A-Fa-f]{8})\b", text):
            names[int(m.group(1), 16)] += 1

hit = [a for a in names if a in starts]
miss = [a for a in names if a not in starts]
print(f"US TOC {toc}; {len(starts)} function starts")
print(f"port names {len(names)} distinct functions: {len(hit)} are function starts in this EBOOT, {len(miss)} are not")
print("most-referenced misses:", [hex(a) for a, _ in sorted(((a, names[a]) for a in miss), key=lambda x: -x[1])[:15]])
