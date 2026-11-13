import json
import re

for name, p in (("inFamous 2", __import__("os").path.expanduser("~") + "/if2/infamous2-lle/out/EBOOT.imports.json"), ("FoB", __import__("os").path.expanduser("~") + "/fob/out/EBOOT.imports.json")):
    j = json.load(open(p))
    text = json.dumps(j)
    addrs = sorted({int(a, 16) for a in re.findall(r'"(?:stub|stub_addr|addr|address|thunk)"\s*:\s*"(0x[0-9a-fA-F]+)"', text)})
    print(name, "top-level keys:", list(j)[:5] if isinstance(j, dict) else type(j).__name__,
          "| stub-like addresses:", len(addrs), hex(addrs[0]) if addrs else "-", hex(addrs[-1]) if addrs else "-")
    sample = j if isinstance(j, list) else next(iter(j.values()))
    print("  sample:", json.dumps(sample)[:300])
