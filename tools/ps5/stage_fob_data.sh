#!/usr/bin/env bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Lay out Festival of Blood's data (US PSN NPUA80657 v1.00) in its PS5 app folder (tools/ps5/ps5_app.c):
#   game/PS3_GAME/                 the PKG's contents, EBOOT.elf (decrypted) in USRDIR
#   game/dev_hdd0/game/NPUA80657/  PARAM.SFO + USRDIR/dlc (the game opens its unlock file there)
#   game/dev_flash/sys/external/   the firmware modules (from RPCS3's dev_flash)
# Files are hard links to games/fob-us/NPUA80657 where possible.
#   stage_fob_data.sh [title id]
set -euo pipefail
title_id=${1:-PPSA95461}
W=${IF_ROOT:-$HOME/inFamous}
S=$W/games/fob-us/NPUA80657
G=$W/ps5/$title_id/game
mkdir -p "$G/PS3_GAME" "$G/dev_hdd0/game/NPUA80657/USRDIR" "$G/dev_flash/sys"
echo "==> PSN data (hard links)"
cp -al "$S/." "$G/PS3_GAME/" 2>/dev/null || cp -a --remove-destination "$S/." "$G/PS3_GAME/"
rm -f "$G/PS3_GAME/USRDIR/EBOOT.BIN"
cp -al "$S/PARAM.SFO" "$G/dev_hdd0/game/NPUA80657/" 2>/dev/null || cp -a "$S/PARAM.SFO" "$G/dev_hdd0/game/NPUA80657/"
cp -al "$S/USRDIR/dlc" "$G/dev_hdd0/game/NPUA80657/USRDIR/" 2>/dev/null || cp -a "$S/USRDIR/dlc" "$G/dev_hdd0/game/NPUA80657/USRDIR/"
echo "==> firmware modules"
rm -rf "$G/dev_flash/sys/external"
cp -a ${RPCS3_DIR:?set RPCS3_DIR (tools/local.env)}/dev_flash/sys/external "$G/dev_flash/sys/"
sha256sum "$G/PS3_GAME/USRDIR/EBOOT.elf" | cut -c1-16
du -sh "$G"
