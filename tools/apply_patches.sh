#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Append any not-yet-appended patch fragment (tools/patch_*.py) to if2_patch_toolkit.py, then apply
# the toolkit edits.   apply_patches.sh
T=${IF_ROOT:-$HOME/inFamous}/tools
for f in $T/patch_*.py; do
  sed -i 's/\r$//' $f
  tag=$(grep -o '"[a-z0-9 ]*: [a-z_0-9 ]*")' $f | head -1)
  first=$(grep -m1 -o 'edit("[^"]*", *[r]*'"'"'*' $f >/dev/null; grep -m1 -oE '"[^"]+"\)$' $f | head -1)
  key=$(grep -m1 -oE '^# .{20,60}' $f | head -1)
  grep -qF "$key" $T/if2_patch_toolkit.py || { cat $f >> $T/if2_patch_toolkit.py; echo "appended $(basename $f)"; }
done
python3 $T/if2_patch_toolkit.py $HOME/if2/ps3recomp-fork | tail -6
