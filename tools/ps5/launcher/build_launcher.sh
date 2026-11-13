#!/usr/bin/env bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# The inFamous: ReCharged launcher (eboot.bin of PPSA95463): launcher.c + RADV + the payload SDK's
# system modules, linked as the games are (ps5link.sh), then signed.
#   build_launcher.sh   -> ~/if2/ps5/launcher/eboot.bin
set -euo pipefail
tri=$HOME/mp3build/tri
fw=$HOME/cdbuild/fw-clean/ps5/tools
sdk_root=$tri/.deps/native/ps5-payload-sdk
radv_archive=$tri/.deps/native/radv-release/lib/libvulkan_radeon.ps5.a
tool=$tri/build/host/ps5-native-tool
src=${IF_ROOT:-$HOME/inFamous}/tools/ps5/launcher
out=$HOME/if2/ps5/launcher
stage=$out/ps5-link
mkdir -p "$stage/build"
ln -sfn "$tri/tooling" "$stage/tooling"
ln -sfn "$tri/vendor" "$stage/vendor"

stb=$HOME/cdbuild/fw-clean/glue/rexglue-sdk-main/thirdparty/stb   # BC-250: the PC had it under ~/mp3build-app/ws/fw
mp3=$HOME/cdbuild/fw-clean/glue/rexglue-sdk-main/gta4-recomp/src/ps5/hub
tt=$HOME/if2/ps3recomp-fork/libs/font
vkh=${IF_ROOT:-$HOME/inFamous}/deps/Vulkan-Headers/include
PS5_EMUTLS=1 sh $HOME/if2/ps5/ps5cc -O2 -fPIC -fno-visibility-from-dllstorageclass -Wno-unused-function \
    -ffile-prefix-map="$stb"=stb -ffile-prefix-map="$mp3"=hub -ffile-prefix-map="$tt"=font -ffile-prefix-map="$vkh"=vk -ffile-prefix-map="$src"=launcher \
    -I"$stb" -I"$mp3" -I"$tt" -I"$vkh" -c "$src/launcher.c" -o "$stage/build/launcher.o"

export PS5_CLANG=${PS5_CLANG:-/usr/bin/clang-18} LLVM_CONFIG=${LLVM_CONFIG:-/usr/bin/llvm-config-18}
source "$tri/tools/radv-link.sh"
radv_link_recipe "$stage" "$sdk_root" "$radv_archive"
"$sdk_root/bin/prospero-clang" -c -O2 -fno-visibility-from-dllstorageclass \
    -o "$stage/build/ps5_stat.o" "$fw/ps5_stat.c"
"$sdk_root/bin/prospero-clang" -c -O2 -fPIC -fno-visibility-from-dllstorageclass \
    -o "$stage/build/ps5_shims.o" $HOME/if2/ps5/ps5_shims.c

target=$out/launcher
link_pie() {
    "$sdk_root/bin/prospero-lld" "${radv_linker_script[@]}" --eh-frame-hdr "${radv_link_flags[@]}" \
        --version-script "$tri/tooling/native/app-symbols.map" --exclude-libs=ALL \
        --wrap=stat --wrap=lstat --wrap=pthread_attr_setstacksize \
        --wrap=pthread_create --wrap=pthread_join --wrap=pthread_detach \
        --wrap=usleep --wrap=nanosleep --wrap=clock_gettime --wrap=sched_yield \
        --wrap=pthread_cond_wait --wrap=pthread_cond_timedwait --wrap=pthread_mutex_lock --wrap=sem_wait --wrap=sem_timedwait \
        -e _start -o "$target" \
        "$tri/build/obj/app_crt.o" "$tri/build/obj/app_cpp_runtime.o" "$stage/build/ps5_stat.o" \
        "$stage/build/ps5_shims.o" "$stage/build/launcher.o" "$@" \
        "$tri/build/stubs/libSceAgc.so" "$tri/build/stubs/libSceAgcDriver.so" \
        "${radv_link_inputs[@]}" \
        --as-needed "$sdk_root"/target/lib/*.so
}
make_eboot() {
    "$tool" link --in "$target" --out "$target.eboot.elf" \
        --stub-dir "$sdk_root/target/lib" --stub "$tri/build/stubs/libSceAgc.so" \
        --stub "$tri/build/stubs/libSceAgcDriver.so" --module-sdk 0x02000009 \
        --companion-sdk 0x08050001 --file-name eboot.elf
}
link_pie
if ! make_eboot 2> "$stage/build/eboot.err"; then
    cat "$stage/build/eboot.err" >&2
    grep -q "no room for PS5 process parameters" "$stage/build/eboot.err" || exit 1
    "$sdk_root/bin/prospero-clang" -c -O2 -fPIC -fno-visibility-from-dllstorageclass \
        -o "$stage/build/ps5_relro_pad.o" "$fw/ps5_relro_pad.c"
    link_pie "$stage/build/ps5_relro_pad.o"
    make_eboot
fi
"$tool" self --sign --in "$target.eboot.elf" --out "$out/eboot.bin" --magic 0x1D3D154F
echo "==> launcher: $out/eboot.bin ($(stat -c %s "$out/eboot.bin") bytes)"
