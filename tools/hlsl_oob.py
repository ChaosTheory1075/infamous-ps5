"""Find dumped HLSL shaders that index an array past its declared size with a constant
(glslang: "array index out of range"). usage: hlsl_oob.py <dump dir>"""
import re
import sys
from pathlib import Path

decl = re.compile(r"\b([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]\s*(?:[:;=,)]|$)", re.M)
use = re.compile(r"\b([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]")
for p in sorted(Path(sys.argv[1]).glob("*.hlsl")):
    s = p.read_text(errors="ignore")
    sizes = {}
    for line in s.splitlines():
        t = line.strip()
        if re.match(r"(static\s+)?(const\s+)?(float|int|uint|bool|half|min16float)\d?(x\d)?\s+\w+\s*\[\s*\d+\s*\]", t) or "register(" in t:
            for m in decl.finditer(t):
                sizes.setdefault(m.group(1), int(m.group(2)))
    for i, line in enumerate(s.splitlines(), 1):
        for m in use.finditer(line):
            n, k = m.group(1), int(m.group(2))
            if n in sizes and k >= sizes[n] and not re.match(r"\s*(static\s+)?(const\s+)?\w+\s+" + n + r"\s*\[", line):
                print(f"{p.name}:{i}: {n}[{k}] but declared [{sizes[n]}]: {line.strip()[:140]}")
