#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Compare the PS5 import NIDs (dynstr entries "<11-char nid>#<lib>#<mod>") of a new eboot against the
# one installed on the console (the FTP serves it as the decrypted ELF).   import_diff.sh <title> <game>
t=${1:-PPSA95460}; g=${2:-if2}
mkdir -p /tmp/impdiff
curl -s --max-time 900 -o /tmp/impdiff/old.elf "ftp://${PS5_IP:?set PS5_IP (tools/local.env)}:2121/data/homebrew/$t/eboot.bin"
nids() { strings -n 13 "$1" | grep -E '^[A-Za-z0-9+/-]{11}#[A-Z]{1,3}#[A-Z]{1,3}$' | sort -u; }
nids /tmp/impdiff/old.elf > /tmp/impdiff/old.n
nids $HOME/if2/ps5/build-$g/Infamous2Recomp.eboot.elf > /tmp/impdiff/new.n
echo "$t: imports old $(wc -l < /tmp/impdiff/old.n), new $(wc -l < /tmp/impdiff/new.n)"
echo "only in new:"; comm -13 /tmp/impdiff/old.n /tmp/impdiff/new.n
echo "only in old:"; comm -23 /tmp/impdiff/old.n /tmp/impdiff/new.n | head
