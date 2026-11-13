"""How many of the EU port's PPU patch hunks find their old text in the US lift, addresses ignored.

Every hex constant and func_/label name is normalised to a placeholder, then each hunk's old side
(context + removed lines) is looked up as a run of consecutive lines in the normalised US lift.
Counts hunks that match exactly once (rebasable by content), more than once (ambiguous) or never.

usage: hunk_match.py <EU patch dir> <US recompiled dir>
"""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HEX = re.compile(r"0x[0-9A-Fa-f]+|\b(?:func|loc|L|label)_[0-9A-Fa-f]+\b|\b[0-9]+\b")


def norm(line):
    return HEX.sub("#", line.rstrip("\r\n")).strip()


us_lines = []
for p in sorted(Path(sys.argv[2]).glob("ppu_recomp_*.cpp")):
    with open(p, errors="ignore") as f:
        us_lines += [norm(l) for l in f]
index = defaultdict(list)
for i, l in enumerate(us_lines):
    if len(l) > 12:
        index[l].append(i)

def find(old):
    old = [l for l in old if l]
    if not old:
        return "empty"
    anchor = max(range(len(old)), key=lambda k: len(old[k]))
    hits = 0
    for i in index.get(old[anchor], ()):
        s = i - anchor
        if s >= 0 and [l for l in us_lines[s:s + len(old) + 8] if l][:len(old)] == old:
            hits += 1
            if hits > 1:
                break
    return {0: "none", 1: "unique"}.get(hits, "ambiguous")


stats = Counter()
for p in sorted(Path(sys.argv[1]).glob("ppu_recomp_*.cpp.patch")):
    old = None
    for line in open(p, errors="ignore"):
        if line.startswith("@@"):
            if old is not None:
                stats[find(old)] += 1
            old = []
        elif old is not None and line[:1] in (" ", "-") and not line.startswith("---"):
            old.append(norm(line[1:]))
    if old is not None:
        stats[find(old)] += 1
total = sum(stats.values())
print(f"{total} PPU hunks: " + ", ".join(f"{k} {v} ({100 * v / total:.1f}%)" for k, v in stats.most_common()))
