#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# What the inFamous 2 port's executable-specific numbers would be for inFamous 1 (EU BCES00220).
set -e
pkill -9 -x Infamous2Recomp 2>/dev/null || true
W=${IF_ROOT:-$HOME/inFamous}
E=$W/games/if1-eu/disc/PS3_GAME/USRDIR/EBOOT.elf
TK=$HOME/if2/ps3recomp-fork
O=$HOME/if1map
rm -rf $O && mkdir -p $O/out $O/spu
$HOME/if2/.venv/bin/python $TK/tools/ppu_loader.py $E -o $O/out > $O/loader.log 2>&1
tail -3 $O/loader.log
$HOME/if2/.venv/bin/python $TK/tools/extract_spu_images.py $E -o $O/spu > $O/spu.log 2>&1 || tail -3 $O/spu.log
python3 - "$E" <<'EOF'
import json, sys
fs = json.load(open(__import__("os").path.expanduser("~") + "/if1map/out/EBOOT.functions.json"))
imps = json.load(open(__import__("os").path.expanduser("~") + "/if1map/out/EBOOT.imports.json"))
stubs = sorted(int(i["stub"], 16) for i in imps)
print(len(fs), "functions;", len(imps), "imports; last stub", hex(stubs[-1]), "-> code end", hex(stubs[-1] + 0x20))
d = open(sys.argv[1], "rb").read()
i2 = open(__import__("os").environ.get("IF_ROOT", __import__("os").path.expanduser("~/inFamous")) + "/games/if2-us/update/v104/USRDIR/EBOOT.elf", "rb").read()
pm = i2[0x8D5B00:0x8D5B00 + 11904]
for n in (11904, 1024, 256, 64):
    at = d.find(pm[:n])
    print(f"policy module first {n} bytes:", hex(at) if at >= 0 else "not found")
    if at >= 0: break
EOF
echo "inFamous 1 SPU images:"; (cd $O/spu && ls -l | awk 'NR>1{print $5, $9}')
