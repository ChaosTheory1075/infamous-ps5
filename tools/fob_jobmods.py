"""Pair FoB's SPU job modules with inFamous 2's by size and code similarity."""
import difflib
import os

A = __import__("os").path.expanduser("~") + "/if2/infamous2-lle/spu/jobmods"
B = __import__("os").path.expanduser("~") + "/fob/infamous2-lle/spu/jobmods"
a = {f[:-4]: open(os.path.join(A, f), "rb").read() for f in os.listdir(A) if f.endswith(".bin")}
b = {f[:-4]: open(os.path.join(B, f), "rb").read() for f in os.listdir(B) if f.endswith(".bin")}
for name in ("jobmod_ab654d30fd90_efe70", "jobmod_cbb4b5c85d75_e59f8"):
    d = a[name]
    words = [d[i:i + 4] for i in range(0, len(d), 4)]
    best = []
    for n, e in b.items():
        if abs(len(e) - len(d)) > len(d) // 4:
            continue
        ew = [e[i:i + 4] for i in range(0, len(e), 4)]
        r = difflib.SequenceMatcher(None, words, ew, autojunk=False).ratio()
        best.append((r, n, len(e)))
    best.sort(reverse=True)
    print(name, len(d), "->", [(round(r, 3), n, s) for r, n, s in best[:3]])
