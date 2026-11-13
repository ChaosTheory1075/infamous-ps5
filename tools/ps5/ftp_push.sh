#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Upload the update files (eboot.bin + README.txt from ps5\update\<title id>) to the console's app
# folders over FTP (no auth), then check each uploaded size against the local one.
#   ftp_push.sh [title id ...]   (default all three)
H=ftp://${PS5_IP:?set PS5_IP (tools/local.env)}:2121/data/homebrew
U=${IF_ROOT:-$HOME/inFamous}/ps5/update
for t in "${@:-PPSA95460 PPSA95461 PPSA95462}"; do
  for one in $t; do
    for f in eboot.bin README.txt; do
      curl -s --max-time 900 -T $U/$one/$f "$H/$one/$f" || { echo "$one/$f: upload FAILED"; continue; }
      remote=$(curl -s --max-time 30 -I "$H/$one/$f" | awk 'tolower($1)=="content-length:"{print $2}' | tr -d '\r')
      echo "$one/$f: local $(stat -c %s $U/$one/$f), console ${remote:-?}"
    done
  done
done
