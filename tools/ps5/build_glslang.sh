#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# glslang (HLSL front end + SPIR-V back end) as PS5 static libraries in ~/if2/ps5/prefix.
set -e
mkdir -p $HOME/if2/ps5/compat $HOME/if2/ps5/prefix
cp ${IF_ROOT:-$HOME/inFamous}/tools/ps5/ps5cc $HOME/if2/ps5/ps5cc; chmod +x $HOME/if2/ps5/ps5cc
cp ${IF_ROOT:-$HOME/inFamous}/tools/ps5/ps5.cmake $HOME/if2/ps5/ps5.cmake
cp ${IF_ROOT:-$HOME/inFamous}/tools/compat/ps5/ps5_compat.h $HOME/if2/ps5/compat/
[ -d $HOME/if2/ps5/glslang-src ] || cp -r ${IF_ROOT:-$HOME/inFamous}/deps/glslang $HOME/if2/ps5/glslang-src
cmake -S $HOME/if2/ps5/glslang-src -B $HOME/if2/ps5/glslang-build -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE=$HOME/if2/ps5/ps5.cmake -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=$HOME/if2/ps5/prefix -DBUILD_SHARED_LIBS=OFF \
    -DENABLE_OPT=OFF -DENABLE_GLSLANG_BINARIES=OFF -DGLSLANG_TESTS=OFF -DBUILD_EXTERNAL=OFF \
    -DENABLE_HLSL=ON -DENABLE_SPVREMAPPER=OFF -DGLSLANG_ENABLE_INSTALL=ON > $HOME/if2/ps5/glslang-cfg.log 2>&1 || { tail -30 $HOME/if2/ps5/glslang-cfg.log; exit 1; }
cmake --build $HOME/if2/ps5/glslang-build -j 30 > $HOME/if2/ps5/glslang-build.log 2>&1 || { grep -m10 error $HOME/if2/ps5/glslang-build.log; exit 1; }
cmake --install $HOME/if2/ps5/glslang-build > /dev/null
ls $HOME/if2/ps5/prefix/lib
