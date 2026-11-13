#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Lay out inFamous 2 (US disc BCUS98125 + update 1.04) the way rebuild.py's game and decrypt steps
# leave a PSN NPUA80638 install, inside WSL's own disk. The 1.04 disc executable is byte-identical to
# the PSN 1.03 one the port is built from; RPCS3 on Windows already decrypted it and the firmware.
set -e
W=${IF_ROOT:-$HOME/inFamous}
OUT=${OUT:-$HOME/if2}
G=$OUT/infamous2
T=$G/vfs/dev_hdd0/game/NPUA80638

mkdir -p "$G/game" "$G/fw" "$T" "$G/vfs/dev_hdd0/home/00000001/savedata" "$G/vfs/dev_hdd1"
if [ -z "$UPDATES_ONLY" ]; then
    echo "copying the disc's PS3_GAME"
    cp -a "$W/games/if2-us/disc/PS3_GAME/." "$T/"
fi
# The updates are not cumulative (1.01 brings patch1 + the *_text archives, 1.03 patch3,
# 1.04 patch4), so lay all of them over the disc in order.
for v in v101 v102 v103 v104; do
    echo "laying update $v over it"
    cp -a "$W/games/if2-us/update/$v/." "$T/"
done
rm -f "$T/USRDIR/EBOOT.BIN" "$T/USRDIR/EBOOT.elf"
cp "$W/games/if2-us/update/v104/USRDIR/EBOOT.elf" "$T/USRDIR/EBOOT.elf"
cp "$W/games/if2-us/update/v104/USRDIR/EBOOT.BIN" "$W/games/if2-us/update/v104/USRDIR/EBOOT.elf" "$G/game/"
for m in liblv2 libsysmodule libsre; do
    cp "$W/games/fw493/$m.sprx" "$W/games/fw493/$m.prx" "$G/fw/"
done
# PARAM.SFO as the PSN release has it (same-length values, rewritten in place).
python3 - "$T/PARAM.SFO" <<'EOF'
import struct, sys
p = sys.argv[1]
d = bytearray(open(p, 'rb').read())
_, _, kt, dt, n = struct.unpack_from('<IIIII', d)
want = {'TITLE_ID': b'NPUA80638', 'APP_VER': b'01.03', 'CATEGORY': b'HG'}
for i in range(n):
    ko, fmt, ln, mx, do = struct.unpack_from('<HHIII', d, 20 + i * 16)
    k = d[kt + ko:d.index(0, kt + ko)].decode()
    if k in want:
        v = want[k]
        assert len(v) < mx, k
        d[dt + do:dt + do + mx] = v + b'\0' * (mx - len(v))
        struct.pack_into('<I', d, 20 + i * 16 + 4, len(v) + 1)
        print('  PARAM.SFO', k, '->', v.decode())
open(p, 'wb').write(d)
EOF
ln -sfn dev_hdd0/game/NPUA80638 "$G/vfs/PS3_GAME"
du -sh "$T"
