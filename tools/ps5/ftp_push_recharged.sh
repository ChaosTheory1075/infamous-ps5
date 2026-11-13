#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Upload the inFamous: ReCharged app folder (ps5\PPSA95463) to the console as a NEW app folder, then
# check every uploaded size against the local one. Touches nothing outside /data/homebrew/PPSA95463.
H=ftp://${PS5_IP:?set PS5_IP (tools/local.env)}:2121/data/homebrew/PPSA95463
A=${IF_ROOT:-$HOME/inFamous}/ps5/PPSA95463
cd "$A"
bad=0
while read -r f; do
  f=${f#./}
  curl -s --max-time 900 --ftp-create-dirs -T "$f" "$H/$f" || { echo "$f: upload FAILED"; bad=1; continue; }
  remote=$(curl -s --max-time 30 -I "$H/$f" | awk 'tolower($1)=="content-length:"{print $2}' | tr -d '\r')
  [ "$remote" = "$(stat -c %s "$f")" ] || { echo "$f: local $(stat -c %s "$f"), console ${remote:-?}"; bad=1; }
done < <(find . -type f | sort)
curl -s --max-time 30 --ftp-create-dirs -Q "MKD /data/homebrew/PPSA95463/logs" "$H/" > /dev/null 2>&1
[ $bad = 0 ] && echo "UPLOAD OK: $(find . -type f | wc -l) files" || echo "UPLOAD HAD PROBLEMS"
