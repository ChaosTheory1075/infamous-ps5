#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Wait (up to ~14 h) for the console's FTP to answer, then upload the three update folders and
# check what landed (the console serves eboot.bin decrypted: its size is the plain ELF's).
H=ftp://${PS5_IP:?set PS5_IP (tools/local.env)}:2121/data/homebrew
for i in $(seq 1 420); do
  curl -s --max-time 8 $H/ > /dev/null && break
  sleep 120
done
curl -s --max-time 8 $H/ > /dev/null || { echo "console never came online"; exit 1; }
echo "console online at $(date +%H:%M); waiting 60 s for it to settle"
sleep 60
bash ${IF_ROOT:-$HOME/inFamous}/tools/ps5/ftp_push.sh
for p in "if2 PPSA95460" "fob PPSA95461" "if1 PPSA95462"; do
  set -- $p
  want=$(stat -c %s $HOME/if2/ps5/build-$1/Infamous2Recomp.eboot.elf)
  got=$(curl -s --max-time 30 -I $H/$2/eboot.bin | awk 'tolower($1)=="content-length:"{print $2}' | tr -d '\r')
  echo "$2: console eboot $got bytes, this build's ELF $want bytes -> $([ "$got" = "$want" ] && echo MATCH || echo DIFFERENT)"
done
