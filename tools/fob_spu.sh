#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Extract FoB's embedded SPU images and compare them with inFamous 2's by content.
set -e
TK=$HOME/if2/ps3recomp-fork
rm -rf $HOME/fob/spu-images && mkdir -p $HOME/fob/spu-images
$HOME/if2/.venv/bin/python $TK/tools/extract_spu_images.py ${IF_ROOT:-$HOME/inFamous}/games/fob-us/NPUA80657/USRDIR/EBOOT.elf -o $HOME/fob/spu-images > $HOME/fob/spu-extract.log 2>&1 || tail -5 $HOME/fob/spu-extract.log
echo "FoB:"; (cd $HOME/fob/spu-images && sha1sum * | sort)
echo "inFamous 2:"; (cd $HOME/if2/infamous2-lle/spu/images && sha1sum *.elf | sort)
grep -n "SPU_IMAGE_EXTRA" -A3 $HOME/if2/src/infamous2-lle/tools/rebuild.py | head -8
