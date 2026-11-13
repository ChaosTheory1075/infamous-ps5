#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# inFamous 2 for the PS5: configure + compile the port (lifted code, toolkit runtime, Vulkan backend)
# with the PS5 toolchain. The executable link is replaced by ps5link.sh (prospero-lld + RADV + SDL2).
set -e
P=$HOME/if2/ps5
# PS5_EXTRA_CFLAGS: added to C and C++ flags at configure time (with RECONFIGURE=1), e.g. -fprofile-use=<profdata>.
# GAME=if2 (default) or fob: which port tree to build (fob: ~/fob, made by tools/fob_build.sh)
GAME=${GAME:-if2}
PORT=$HOME/$GAME/infamous2-lle
B=$P/build-$GAME
[ $GAME = if2 ] && [ -d $P/build ] && [ ! -e $B ] && mv $P/build $B
cp ${IF_ROOT:-$HOME/inFamous}/tools/ps5/ps5cc $P/ps5cc; chmod +x $P/ps5cc
cp ${IF_ROOT:-$HOME/inFamous}/tools/ps5/ps5.cmake $P/ps5.cmake
cp ${IF_ROOT:-$HOME/inFamous}/tools/ps5/ps5link.sh $P/ps5link.sh 2>/dev/null && chmod +x $P/ps5link.sh || true
cp ${IF_ROOT:-$HOME/inFamous}/tools/compat/ps5/ps5_compat.h $P/compat/
cp ${IF_ROOT:-$HOME/inFamous}/tools/ps5/ps5_shims.c ${IF_ROOT:-$HOME/inFamous}/tools/ps5/ps5_app.c $P/
python3 ${IF_ROOT:-$HOME/inFamous}/tools/if2_patch_rebuild.py $HOME/$GAME/src/infamous2-lle/tools/rebuild.py $HOME/$GAME/src/infamous2-lle/main.cpp
cp $HOME/$GAME/src/infamous2-lle/main.cpp $PORT/main.cpp
python3 ${IF_ROOT:-$HOME/inFamous}/tools/if2_patch_toolkit.py $HOME/if2/ps3recomp-fork
export PKG_CONFIG_LIBDIR=/nonexistent   # no host pkg-config packages (spirv-cross) in a PS5 build
if [ ! -f $B/build.ninja ] || [ -n "$RECONFIGURE" ]; then
cmake -S $PORT -B $B -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE=$P/ps5.cmake -DCMAKE_BUILD_TYPE=Release \
    -DPS3RECOMP_DIR=$HOME/if2/ps3recomp-fork -DPython3_EXECUTABLE=/usr/bin/python3 \
    -DPS3RECOMP_RSX_VULKAN=ON -DPS3RECOMP_VULKAN_INCLUDE_DIR=${IF_ROOT:-$HOME/inFamous}/deps/Vulkan-Headers/include \
    -Dglslang_DIR=$P/prefix/lib/cmake/glslang \
    -DSDL2_DIR=$HOME/mp3build/tri/.deps/pacbrew/v0.40.2/sysroot/user/homebrew/lib/cmake/SDL2 \
    "-DCMAKE_CXX_FLAGS=-I$HOME/if2/compat $PS5_EXTRA_CFLAGS" "-DCMAKE_C_FLAGS=$PS5_EXTRA_CFLAGS" \
    "-DCMAKE_CXX_LINK_EXECUTABLE=$P/ps5link.sh <TARGET> <OBJECTS> <LINK_LIBRARIES>" \
    > $P/cfg.log 2>&1 || { tail -40 $P/cfg.log; exit 1; }
fi
grep -E "SDL2|Vulkan|Shaders|glslang|backend" $P/cfg.log | head -10
cmake --build $B -j $(nproc) -- -k 0 > $B.log 2>&1 || true
echo "failed objects: $(grep -c '^FAILED' $B.log)"
grep -h 'error:' $B.log | sed -E 's/^[^ ]+ //' | sort | uniq -c | sort -rn | head -25
grep '^FAILED' $B.log | head -15
