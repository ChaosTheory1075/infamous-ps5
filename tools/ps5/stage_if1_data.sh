#!/usr/bin/env bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Lay out inFamous 1's data (EU disc BCES00220) in its PS5 app folder (tools/ps5/ps5_app.c):
#   game/PS3_GAME/                 the disc's PS3_GAME, EBOOT.elf (decrypted) in USRDIR
#   game/dev_hdd0/                 empty: the game writes its HDD install (~1.3 GB) on first boot
#   game/dev_flash/sys/external/   the firmware modules (from RPCS3's dev_flash)
# Disc files are hard links to games/if1-eu/disc.
#   stage_if1_data.sh [title id]
set -euo pipefail
title_id=${1:-PPSA95462}
W=${IF_ROOT:-$HOME/inFamous}
S=$W/games/if1-eu/disc/PS3_GAME
G=$W/ps5/$title_id/game
mkdir -p "$G/PS3_GAME" "$G/dev_hdd0/game" "$G/dev_flash/sys"
echo "==> disc (hard links)"
cp -al "$S/." "$G/PS3_GAME/" 2>/dev/null || cp -a --remove-destination "$S/." "$G/PS3_GAME/"
rm -f "$G/PS3_GAME/USRDIR/EBOOT.BIN"
echo "==> firmware modules"
rm -rf "$G/dev_flash/sys/external"
cp -a ${RPCS3_DIR:?set RPCS3_DIR (tools/local.env)}/dev_flash/sys/external "$G/dev_flash/sys/"
sha256sum "$G/PS3_GAME/USRDIR/EBOOT.elf" | cut -c1-16
du -sh "$G"
