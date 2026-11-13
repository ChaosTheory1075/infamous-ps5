#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# The update folders (ps5\update\<title id>: eboot.bin + README.txt) from the current app folders,
# without repackaging. package_if2.sh refreshes them on every build.
W=${IF_ROOT:-$HOME/inFamous}/ps5
for t in PPSA95460 PPSA95461 PPSA95462; do
  mkdir -p $W/update/$t
  cp $W/$t/eboot.bin $W/$t/README.txt $W/update/$t/
  cmp -s $W/$t/eboot.bin $W/update/$t/eboot.bin && echo "$t: $(du -sh $W/update/$t | cut -f1)"
done
