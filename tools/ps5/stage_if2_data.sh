#!/usr/bin/env bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Lay out inFamous 2's data in the PS5 app folder (see tools/ps5/ps5_app.c):
#   game/PS3_GAME/                 disc PS3_GAME + updates 1.01-1.04, EBOOT.elf (decrypted 1.04)
#   game/dev_hdd0/game/NPUA80638/  PARAM.SFO + USRDIR/patch (the updates' archives)
#   game/dev_flash/sys/external/   the firmware modules (from RPCS3's dev_flash)
# Disc files are hard links to games/if2-us/disc (no second 15 GB); every file an update replaces is
# written as a new file (--remove-destination), so the extracted disc is never modified.
#   stage_if2_data.sh [title id]
set -euo pipefail
title_id=${1:-PPSA95460}
W=${IF_ROOT:-$HOME/inFamous}
G=$W/ps5/$title_id/game
U=$W/games/if2-us/update
mkdir -p "$G/PS3_GAME" "$G/dev_hdd0/game/NPUA80638" "$G/dev_flash/sys"

echo "==> disc (hard links)"
cp -al "$W/games/if2-us/disc/PS3_GAME/." "$G/PS3_GAME/" 2>/dev/null || cp -a --remove-destination "$W/games/if2-us/disc/PS3_GAME/." "$G/PS3_GAME/"
for v in v101 v102 v103 v104; do
    echo "==> update $v"
    cp -a --remove-destination "$U/$v/." "$G/PS3_GAME/"
    if [[ -d $U/$v/USRDIR/patch ]]; then
        mkdir -p "$G/dev_hdd0/game/NPUA80638/USRDIR"
        cp -a --remove-destination "$U/$v/USRDIR/patch" "$G/dev_hdd0/game/NPUA80638/USRDIR/"
    fi
done
rm -f "$G/PS3_GAME/USRDIR/EBOOT.BIN"
cp --remove-destination "$U/v104/USRDIR/EBOOT.elf" "$G/PS3_GAME/USRDIR/EBOOT.elf"
# PARAM.SFO as the PSN release has it (TITLE_ID NPUA80638, APP_VER 01.03, HG), both places.
python3 - "$U/v104/PARAM.SFO" "$G/PS3_GAME/PARAM.SFO" "$G/dev_hdd0/game/NPUA80638/PARAM.SFO" <<'EOF'
import struct, sys
d = bytearray(open(sys.argv[1], 'rb').read())
_, _, kt, dt, n = struct.unpack_from('<IIIII', d)
want = {'TITLE_ID': b'NPUA80638', 'APP_VER': b'01.03', 'CATEGORY': b'HG'}
for i in range(n):
    ko, fmt, ln, mx, do = struct.unpack_from('<HHIII', d, 20 + i * 16)
    k = d[kt + ko:d.index(0, kt + ko)].decode()
    if k in want:
        v = want[k]
        d[dt + do:dt + do + mx] = v + b'\0' * (mx - len(v))
        struct.pack_into('<I', d, 20 + i * 16 + 4, len(v) + 1)
for out in sys.argv[2:]:
    import os
    if os.path.exists(out): os.remove(out)
    open(out, 'wb').write(d)
print('PARAM.SFO -> NPUA80638 / 01.03 / HG')
EOF
echo "==> firmware modules"
rm -rf "$G/dev_flash/sys/external"
cp -a ${RPCS3_DIR:?set RPCS3_DIR (tools/local.env)}/dev_flash/sys/external "$G/dev_flash/sys/"
sha256sum "$G/PS3_GAME/USRDIR/EBOOT.elf" | cut -c1-16
du -sh "$G" "$G/dev_flash" "$G/dev_hdd0"
