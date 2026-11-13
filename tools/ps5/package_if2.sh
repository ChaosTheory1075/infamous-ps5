#!/usr/bin/env bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# inFamous 2 for the PS5: the app folder (eboot.bin, sce_module/libc.prx, sce_sys) from the PS5 build,
# in Downloads\inFamous\ps5\<title id>. The game data is staged separately (stage_if2_data.sh).
#   package_if2.sh [title id]
set -euo pipefail
title_id=${1:-PPSA95460}
GAME=${GAME:-if2}
name=${TITLE_NAME:-inFAMOUS 2}
cid=${CONTENT_TAG:-INFAMOUS2PS50000}
tri=$HOME/mp3build/tri
tool=$tri/build/host/ps5-native-tool
W=${IF_ROOT:-$HOME/inFamous}
elf=$HOME/if2/ps5/build-$GAME/Infamous2Recomp.eboot.elf
app=$W/ps5/$title_id
[[ -f $elf ]] || { echo "no $elf: run build_if2.sh first" >&2; exit 2; }

mkdir -p "$app/sce_sys" "$app/sce_module" "$app/logs" "$app/cache"
"$tool" self --sign --in "$elf" --out "$app/eboot.bin" --magic 0x1D3D154F
cp "$tri/runtime/libc.prx" "$app/sce_module/libc.prx"
cat > "$app/sce_sys/param.json" <<EOF
{
  "ageLevel": { "default": 0 },
  "applicationCategoryType": 0,
  "applicationDrmType": "free",
  "attribute": 0,
  "attribute2": 0,
  "attribute3": 262208,
  "conceptId": "${title_id:4}",
  "contentBadgeType": 1,
  "contentId": "UP9000-${title_id}_00-${cid}",
  "contentVersion": "01.000.000",
  "downloadDataSize": 256,
  "gameIntent": { "permittedIntents": [ { "intentType": "launchActivity" } ] },
  "localizedParameters": {
    "defaultLanguage": "en-US",
    "en-US": { "titleName": "${name}" }
  },
  "masterVersion": "01.00",
  "pubtools": { "creationDate": "$(date -u +%Y-%m-%d) 00:00:00", "loudnessSnd0": "-28.00", "toolVersion": "2.00" },
  "requiredSystemSoftwareVersion": "0x0000000000000000",
  "sdkVersion": "0x0000000000000000",
  "titleId": "${title_id}",
  "versionFileUri": ""
}
EOF
# Dashboard art from the game's own ICON0/PIC1 (Max Payne's art script, no title text).
src=${ART_SRC:-$W/games/if2-us/disc/PS3_GAME}
python3 ${MP3_PS5_DIR:?set MP3_PS5_DIR (tools/local.env)}/ci/make_sce_art.py "$app/sce_sys" \
    --icon "$src/ICON0.PNG" --background "$src/PIC1.PNG"
python3 - "$app/README.txt" "$name" "$title_id" "$GAME" <<'PYEOF'
import sys
out, name, tid, game = sys.argv[1:5]
src = {
    "if2": "US disc BCUS98125 with updates 1.01-1.04 (the 1.04 executable is the PSN 1.03 one the port targets)",
    "fob": "US PSN release NPUA80657 v1.00",
    "if1": "EU disc BCES00220 (English selected at start; the disc's other languages via PS3_LANG)",
}[game]
first = {
    "if2": "  - inFAMOUS 2 copies some data to its install folder (game/dev_hdd0/game/BCUS98125_INSTALL,\n    about 2.4 GB) on the first start: give it a few minutes.",
    "fob": "  - Festival of Blood copies some data to game/dev_hdd0/game/NPUA80657_INSTALL on the first\n    start: give it a few minutes.",
    "if1": "  - inFAMOUS installs about 1.3 GB to game/dev_hdd0/game/BCES00220 on the first start (the\n    title screen takes a while that time).",
}[game]
gaps = {
    "if2": "",
    "fob": "",
    "if1": "  - inFAMOUS (1) is the newest of the three on this toolkit. On the PC test build it reaches\n    \"Press the Start Button\", and START is taken there once the game runs a few frames a\n    second (the main-menu music starts). What the menu after it does is the open question.",
}[game]
t = open(__import__("os").environ.get("IF_ROOT", __import__("os").path.expanduser("~/inFamous")) + "/tools/ps5/README-app.txt").read()
t = t.replace("@TITLE@", name).replace("@TITLEID@", tid).replace("@SOURCE@", src)
log = {"if2": "infamous2", "fob": "infamousfob", "if1": "infamous"}[game]
t = t.replace("@LOGPAD@", " " * (26 - len(log))).replace("@LOG@", log)
t = t.replace("@FIRSTRUN@", first).replace("@GAPS@\n", gaps + ("\n" if gaps else ""))
open(out, "w", newline="\r\n").write(t)
PYEOF
"$tool" self --inspect --file "$app/eboot.bin" | tail -3
echo "==> $app ($(stat -c %s "$app/eboot.bin") bytes)"
# What changes from one build to the next, for copying over an app already on the console (the
# game data, shaders, icons and libc.prx stay as they are): ps5\update\<title id>.
upd=$W/ps5/update/$title_id
mkdir -p "$upd"
cp "$app/eboot.bin" "$app/README.txt" "$upd/"
echo "==> $upd (update: eboot.bin + README.txt)"
