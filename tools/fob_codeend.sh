#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# PPU loader on FoB, then compare the highest function end with inFamous 2's --code-end 0x742e18.
set -e
mkdir -p $HOME/fob/out
TK=$HOME/if2/ps3recomp-fork
$HOME/if2/.venv/bin/python $TK/tools/ppu_loader.py ${IF_ROOT:-$HOME/inFamous}/games/fob-us/NPUA80657/USRDIR/EBOOT.elf -o $HOME/fob/out > $HOME/fob/loader.log 2>&1
tail -4 $HOME/fob/loader.log
python3 - <<'EOF'
import json
for name, p in (("inFamous 2", __import__("os").path.expanduser("~") + "/if2/infamous2-lle/out/EBOOT.functions.json"), ("FoB", __import__("os").path.expanduser("~") + "/fob/out/EBOOT.functions.json")):
    f = json.load(open(p))
    ends = sorted(int(x["end"], 16) for x in f)
    print(name, len(f), "functions, highest end", hex(ends[-1]), "2nd", hex(ends[-2]))
EOF
