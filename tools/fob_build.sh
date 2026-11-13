#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# inFAMOUS: Festival of Blood (US PSN NPUA80657, v1.00) on the inFamous 2 port. FoB is the inFamous 2
# engine: same 302 firmware imports, byte-identical SPU images and Wws_Job policy module, only the
# addresses moved. This copies the (locally patched) inFamous 2 port and swaps its numbers:
#   code end            0x742e18  -> 0x781aa0   (last import stub + 0x20)
#   policy module       file 0x8D5B00 / guest 0x8E5B00 -> 0x91D900 / 0x92D900
#   SPU image 0         spu_0000_at_007FA100 -> spu_0000_at_00842080 (same bytes)
#   title id            NPUA80638 -> NPUA80657
# then lays out the PSN copy (PKG contents, decrypted EBOOT + firmware) and runs rebuild.py from
# the "port" step with the shared toolkit ~/if2/ps3recomp-fork.
#   fob_build.sh [rebuild.py args]      (default: --only port,firmware,ppu,spu,jobs,compile,finish)
set -e
W=${IF_ROOT:-$HOME/inFamous}
OUT=$HOME/fob
SRC=$OUT/src
G=$OUT/infamous2
T=$G/vfs/dev_hdd0/game/NPUA80657

if [ ! -d "$SRC/.git" ]; then
    git clone -q https://github.com/erikomis/infamous2-recomp.git "$SRC"
fi
python3 $W/tools/if2_patch_rebuild.py "$SRC/infamous2-lle/tools/rebuild.py" "$SRC/infamous2-lle/main.cpp"
R=$SRC/infamous2-lle/tools/rebuild.py
sed -i "s/TITLE_ID = 'NPUA80638'/TITLE_ID = 'NPUA80657'/; s/'--code-end', '0x742e18'/'--code-end', '0x781aa0'/; \
        s/f.seek(0x8D5B00)/f.seek(0x91D900)/; s/wwsjob_pm_at_008E5B00/wwsjob_pm_at_0092D900/g; \
        s/spu_0000_at_007FA100/spu_0000_at_00842080/g" "$R"
# The two job modules the port re-lifts with extra resume points (the interpreter's fallback covers a
# missing one): FoB's counterparts by code similarity (tools/fob_jobmods.py, 97% / 93%); the first's
# points matched exactly at -0x10 (fob_jobextra.py), the second's take its entry point's +8.
sed -i "s/('jobmod_ab654d30fd90_efe70', ('0x15280', '0x155EC'))/('jobmod_db1f4c51136a_efe60', ('0x15270', '0x155DC'))/; \
        s/('jobmod_cbb4b5c85d75_e59f8', ('0x6C44', '0x6C64'))/('jobmod_524cae397099_e5a00', ('0x6C4C', '0x6C6C'))/" "$R"
grep -n -A1 "^JOBMOD_EXTRA" "$R"
# gpu_light.c / gpu_ssao.c hook inFamous 2's light and SSAO jobs by lifted name and image id; FoB's
# are the same code at other ids (light: another module, 8 bytes shorter): fob_gpu_hooks.sh.
bash $W/tools/fob_gpu_hooks.sh $HOME/if2/infamous2-lle "$SRC/infamous2-lle"
sed -i "s/#define WWSJOB_PM_EA    0x008E5B00u/#define WWSJOB_PM_EA    0x0092D900u/; s/wwsjob_pm_at_008E5B00/wwsjob_pm_at_0092D900/g" \
    "$SRC/infamous2-lle/stubs.cpp"
grep -nE "TITLE_ID = |code-end|f.seek|wwsjob_pm_at|spu_0000_at" "$R" | cut -c1-120
grep -n "WWSJOB_PM_EA " "$SRC/infamous2-lle/stubs.cpp"

# The PSN copy as rebuild.py's game + decrypt steps would leave it.
if [ ! -f "$T/USRDIR/EBOOT.elf" ]; then
    mkdir -p "$G/game" "$G/fw" "$T" "$G/vfs/dev_hdd0/home/00000001/savedata" "$G/vfs/dev_hdd1"
    cp -a "$W/games/fob-us/NPUA80657/." "$T/"
    rm -f "$T/USRDIR/EBOOT.BIN"
    cp "$W/games/fob-us/NPUA80657/USRDIR/EBOOT.BIN" "$W/games/fob-us/NPUA80657/USRDIR/EBOOT.elf" "$G/game/"
    for m in liblv2 libsysmodule libsre; do cp "$W/games/fw493/$m.sprx" "$W/games/fw493/$m.prx" "$G/fw/"; done
    ln -sfn dev_hdd0/game/NPUA80657 "$G/vfs/PS3_GAME"
fi
[ -x "$OUT/.venv/bin/python" ] || ln -sfn $HOME/if2/.venv "$OUT/.venv"

export INFAMOUS2_ANY_HOST=1 INFAMOUS2_PREPARED=1
export INFAMOUS2_CMAKE_ARGS=${INFAMOUS2_CMAKE_ARGS:-"-DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_CXX_FLAGS=-I$HOME/if2/compat -DPS3RECOMP_RSX_VULKAN=ON -DPS3RECOMP_VULKAN_INCLUDE_DIR=/usr/include"}
args=("$@")
[ ${#args[@]} -eq 0 ] && args=(--only port,firmware,ppu,spu,jobs,compile,finish)
$HOME/if2/.venv/bin/python "$R" --out "$OUT" --toolkit $HOME/if2/ps3recomp-fork --venv $HOME/if2/.venv \
    --firmware "$G/fw" -j 30 "${args[@]}"
