#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# glslang 15.4 for the PS5 WITH the SPIRV-Tools optimizer (ENABLE_OPT=ON): rsx_shader_spirv.cpp asks
# for the HLSL legalization passes (disableOptimizer = false), which glslang only runs when it is built
# against SPIRV-Tools; without them some HLSL becomes SPIR-V a driver may refuse.
set -e
P=$HOME/if2/ps5
S=$P/glslang-src
cd $S
if [ ! -d External/spirv-tools ]; then
    python3 update_glslang_sources.py > $P/glslang-sources.log 2>&1 || { tail -20 $P/glslang-sources.log; exit 1; }
fi
ls External
rm -rf $P/glslang-build-opt
cmake -S $S -B $P/glslang-build-opt -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE=$P/ps5.cmake -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=$P/prefix -DBUILD_SHARED_LIBS=OFF \
    -DENABLE_OPT=ON -DENABLE_GLSLANG_BINARIES=OFF -DGLSLANG_TESTS=OFF -DBUILD_EXTERNAL=ON \
    -DSPIRV_SKIP_TESTS=ON -DSPIRV_SKIP_EXECUTABLES=ON -DSPIRV_WERROR=OFF \
    -DENABLE_HLSL=ON -DENABLE_SPVREMAPPER=OFF -DGLSLANG_ENABLE_INSTALL=ON \
    -DSKIP_SPIRV_TOOLS_INSTALL=OFF \
    "-DCMAKE_CXX_CREATE_SHARED_LIBRARY=touch <TARGET>" "-DCMAKE_C_CREATE_SHARED_LIBRARY=touch <TARGET>" > $P/glslang-opt-cfg.log 2>&1 || { tail -30 $P/glslang-opt-cfg.log; exit 1; }
cmake --build $P/glslang-build-opt -j 30 > $P/glslang-opt-build.log 2>&1 || { grep -m10 error $P/glslang-opt-build.log; exit 1; }
cmake --install $P/glslang-build-opt > /dev/null
ls $P/prefix/lib
