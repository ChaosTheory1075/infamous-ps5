#!/usr/bin/env bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# inFamous: ReCharged (PPSA95463): one app holding the launcher (eboot.bin) and the three games
# (if1.bin, if2.bin, fob.bin), each game's files in its own folder (if1/, if2/, fob/). The game data
# (game/, cache/, radv-shader-cache/) is moved in on the console from the old single-game apps.
#   assemble_recharged.sh   -> Downloads\inFamous\ps5\PPSA95463 (run build_recharged.sh first)
set -euo pipefail
title_id=PPSA95463
tri=$HOME/mp3build/tri
tool=$tri/build/host/ps5-native-tool
W=${IF_ROOT:-$HOME/inFamous}
T=$W/tools/ps5
app=$W/ps5/$title_id

python3 $T/launcher/make_assets.py "$app"
mkdir -p "$app/sce_sys" "$app/sce_module" "$app/logs"
cp $HOME/if2/ps5/launcher/eboot.bin "$app/eboot.bin"
for g in if1 if2 fob; do
    "$tool" self --sign --in $HOME/if2/ps5/build-$g/Infamous2Recomp.eboot.elf --out "$app/$g.bin" --magic 0x1D3D154F
    mkdir -p "$app/$g/logs"
    printf 'PS3_THREAD_DUMP=20\nPS3_EVQSTAT=2000\nPS3_HANG_DUMP=1\nPS3_TOGGLE_FILE=/app0/%s/logs/toggles.txt\n' $g > "$app/$g/env.txt"
    printf '# live knobs (ps3_toggles.h)\n' > "$app/$g/logs/toggles.txt"
done
cp "$tri/runtime/libc.prx" "$app/sce_module/libc.prx"
[ -f "$app/launcher.ini" ] || printf 'game = 1\nskip_intro = 1\nskip_movies = 0\nlanguage = en\ngpu_effects = 1\ndiagnostics = 1\nmenu_music = 70\n' > "$app/launcher.ini"
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
  "contentId": "UP9000-${title_id}_00-INFAMOUSRECHARGE",
  "contentVersion": "01.000.000",
  "downloadDataSize": 256,
  "gameIntent": { "permittedIntents": [ { "intentType": "launchActivity" } ] },
  "localizedParameters": {
    "defaultLanguage": "en-US",
    "en-US": { "titleName": "inFAMOUS: ReCharged" }
  },
  "masterVersion": "01.00",
  "pubtools": { "creationDate": "$(date -u +%Y-%m-%d) 00:00:00", "loudnessSnd0": "-28.00", "toolVersion": "2.00" },
  "requiredSystemSoftwareVersion": "0x0000000000000000",
  "sdkVersion": "0x0000000000000000",
  "titleId": "${title_id}",
  "versionFileUri": ""
}
EOF
python3 ${MP3_PS5_DIR:?set MP3_PS5_DIR (tools/local.env)}/ci/make_sce_art.py "$app/sce_sys" \
    --icon /tmp/rc_icon.png --background /tmp/rc_bg.png
for f in eboot.bin if1.bin if2.bin fob.bin; do echo "$f $(stat -c %s "$app/$f")"; done
find "$app" -type f | sed "s|$app/||" | sort
