#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
export LC_ALL=C   # comm and sort must agree on the order
# NID-only import check of the new launcher and game builds against the copies installed in PPSA95463.
mkdir -p /tmp/impdiff
nids() { strings -n 13 "$1" | grep -E '^[A-Za-z0-9+/-]{11}#[A-Z]{1,3}#[A-Z]{1,3}$' | cut -d'#' -f1 | sort -u; }
check() {   # <name> <installed file> <new elf>
  curl -s --max-time 900 -o /tmp/impdiff/$1.old "ftp://${PS5_IP:?set PS5_IP (tools/local.env)}:2121/data/homebrew/PPSA95463/$2"
  nids /tmp/impdiff/$1.old > /tmp/impdiff/o; nids "$3" > /tmp/impdiff/n
  echo "$1: old $(wc -l < /tmp/impdiff/o) new $(wc -l < /tmp/impdiff/n) diff: $(comm -3 /tmp/impdiff/o /tmp/impdiff/n | tr -d '\t' | tr '\n' ' ')"
}
check launcher eboot.bin $HOME/if2/ps5/launcher/launcher.eboot.elf
for g in if1 if2 fob; do check $g $g.bin $HOME/if2/ps5/build-$g/Infamous2Recomp.eboot.elf; done
