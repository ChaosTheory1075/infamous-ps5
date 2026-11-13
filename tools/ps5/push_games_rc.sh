#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Sign the three game builds into ps5\PPSA95463 and upload only if1.bin / if2.bin / fob.bin.
tool=$HOME/mp3build/tri/build/host/ps5-native-tool
A=${IF_ROOT:-$HOME/inFamous}/ps5/PPSA95463
H=ftp://${PS5_IP:?set PS5_IP (tools/local.env)}:2121/data/homebrew/PPSA95463
for g in if1 if2 fob; do
  "$tool" self --sign --in $HOME/if2/ps5/build-$g/Infamous2Recomp.eboot.elf --out $A/$g.bin --magic 0x1D3D154F > /dev/null
  curl -s --max-time 900 -T $A/$g.bin $H/$g.bin || { echo "$g.bin: upload FAILED (game running?)"; continue; }
  echo "$g.bin: console $(curl -s --max-time 30 -I $H/$g.bin | awk 'tolower($1)=="content-length:"{print $2}' | tr -d '\r') bytes, elf $(stat -c %s $HOME/if2/ps5/build-$g/Infamous2Recomp.eboot.elf)"
done
