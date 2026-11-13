#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# inFamous 2 on Linux: port checkout + patched toolkit + venv, then rebuild.py from the "port" step
# (the game and decrypt steps were done by if2_prepare.sh). Usage: if2_build.sh [rebuild.py args]
set -e
OUT=${OUT:-$HOME/if2}
SRC=$OUT/src
cd "$OUT"
if [ ! -d "$SRC/.git" ]; then
    git clone -q https://github.com/erikomis/infamous2-recomp.git "$SRC"
fi
if [ ! -d "$OUT/ps3recomp-fork/.git" ]; then
    sh "$SRC/tools/setup_toolkit.sh" "$OUT/ps3recomp-fork" --managed
fi
if [ ! -x "$OUT/.venv/bin/python" ]; then
    python3 -m venv "$OUT/.venv"
    "$OUT/.venv/bin/pip" -q install -r "$OUT/ps3recomp-fork/requirements.txt"
fi
export INFAMOUS2_ANY_HOST=1 INFAMOUS2_PREPARED=1
python3 ${IF_ROOT:-$HOME/inFamous}/tools/if2_patch_rebuild.py "$SRC/infamous2-lle/tools/rebuild.py" "$SRC/infamous2-lle/main.cpp"
python3 ${IF_ROOT:-$HOME/inFamous}/tools/if2_patch_toolkit.py "$OUT/ps3recomp-fork"
"$OUT/.venv/bin/python" "$SRC/infamous2-lle/tools/rebuild.py" --out "$OUT" \
    --toolkit "$OUT/ps3recomp-fork" --venv "$OUT/.venv" -j 30 "$@"
