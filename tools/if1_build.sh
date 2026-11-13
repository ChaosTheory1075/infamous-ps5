#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# inFamous 1 (EU disc BCES00220) on the inFamous 2 LLE port (Noah's toolkit + erikomis's patch, the
# shared ~/if2/ps3recomp-fork). See tools/if1_patch_port.py for the numbers.
#   if1_build.sh [rebuild.py args]   (default: --only port,firmware,ppu,spu,jobs,compile,finish)
set -e
W=${IF_ROOT:-$HOME/inFamous}
OUT=$HOME/if1
SRC=$OUT/src
G=$OUT/infamous2
mkdir -p $OUT
[ -d "$SRC/.git" ] || git clone -q https://github.com/erikomis/infamous2-recomp.git "$SRC"
python3 $W/tools/if2_patch_rebuild.py "$SRC/infamous2-lle/tools/rebuild.py" "$SRC/infamous2-lle/main.cpp"
python3 $W/tools/if1_patch_port.py "$SRC/infamous2-lle"
# The disc as the VFS root's PS3_GAME (copied onto WSL's disk: reads through /mnt/c are slow).
if [ ! -f "$G/vfs/PS3_GAME/USRDIR/EBOOT.elf" ]; then
    mkdir -p "$G/game" "$G/fw" "$G/vfs/dev_hdd0/game" "$G/vfs/dev_hdd0/home/00000001/savedata" "$G/vfs/dev_hdd1"
    cp -a "$W/games/if1-eu/disc/PS3_GAME" "$G/vfs/"
    rm -f "$G/vfs/PS3_GAME/USRDIR/EBOOT.BIN"
    cp "$W/games/if1-eu/disc/PS3_GAME/USRDIR/EBOOT.BIN" "$W/games/if1-eu/disc/PS3_GAME/USRDIR/EBOOT.elf" "$G/game/"
    for m in liblv2 libsysmodule libsre; do cp "$W/games/fw493/$m.sprx" "$W/games/fw493/$m.prx" "$G/fw/"; done
    # No dev_hdd0/game/BCES00220 here: that is the game's own HDD install target. A symlink to the
    # disc there made the first-boot install walk/copy the disc onto itself (a malloc per entry
    # until the heap ran out); the game creates the folder and fills it (~1.3 GB).
fi
rm -f "$G/vfs/dev_hdd0/game/BCES00220" 2>/dev/null || true   # (a symlink left by an older version)
[ -e "$OUT/.venv" ] || ln -sfn $HOME/if2/.venv "$OUT/.venv"
export INFAMOUS2_ANY_HOST=1 INFAMOUS2_PREPARED=1
export INFAMOUS2_CMAKE_ARGS=${INFAMOUS2_CMAKE_ARGS:-"-DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_CXX_FLAGS=-I$HOME/if2/compat -DPS3RECOMP_RSX_VULKAN=ON -DPS3RECOMP_VULKAN_INCLUDE_DIR=/usr/include"}
args=("$@")
[ ${#args[@]} -eq 0 ] && args=(--only port,firmware,ppu,spu,jobs,compile,finish)
$HOME/if2/.venv/bin/python "$SRC/infamous2-lle/tools/rebuild.py" --out "$OUT" --toolkit $HOME/if2/ps3recomp-fork \
    --venv $HOME/if2/.venv --firmware "$G/fw" -j 30 "${args[@]}"
