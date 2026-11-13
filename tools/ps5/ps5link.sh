#!/usr/bin/env bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# CMake's executable link for the PS5 (CMAKE_CXX_LINK_EXECUTABLE): ps5link.sh <target> <objects> <libs>
# Links the objects and static libraries CMake collected with RADV (libvulkan_radeon.ps5.a), the PS5
# SDL2 and the payload SDK's system modules into a PS5 PIE ELF, then converts it to eboot.elf
# (ps5-native-tool), the way Max Payne 3 RePrescribed's ci/ps5_package_mp3.sh does.
# Writes <target> (the PIE ELF) and <target>.eboot.elf next to it.
set -euo pipefail

target=$1; shift
tri=$HOME/mp3build/tri
fw=$HOME/cdbuild/fw-clean/ps5/tools           # gta4-ps5's ps5/tools (read-only copy)
sdk_root=$tri/.deps/native/ps5-payload-sdk
pac=$tri/.deps/pacbrew/v0.40.2/sysroot/user/homebrew/lib
radv_archive=$tri/.deps/native/radv-release/lib/libvulkan_radeon.ps5.a
tool=$tri/build/host/ps5-native-tool
build=$(pwd)
stage=$build/ps5-link

inputs=()
for w in "$@"; do
    case $w in
        -lsamplerate) [[ -f $pac/libsamplerate.a ]] && inputs+=("$pac/libsamplerate.a") ;;
        -liconv)      [[ -f $pac/libiconv.a ]] && inputs+=("$pac/libiconv.a") ;;
        -l*|-L*|-Wl,*|-pthread|-rdynamic) ;;        # system modules come from target/lib/*.so below
        *spirv-cross*) ;;                           # Metal-only translator, not on the PS5
        *.o|*.a|*.obj) [[ $w = /* ]] && inputs+=("$w") || inputs+=("$build/$w") ;;
    esac
done
echo "==> [ps5 link] ${#inputs[@]} objects and libraries"

mkdir -p "$stage/build"
ln -sfn "$tri/tooling" "$stage/tooling"
ln -sfn "$tri/vendor" "$stage/vendor"
export PS5_CLANG=${PS5_CLANG:-/usr/bin/clang-18}
export LLVM_CONFIG=${LLVM_CONFIG:-/usr/bin/llvm-config-18}
source "$tri/tools/radv-link.sh"
radv_link_recipe "$stage" "$sdk_root" "$radv_archive"
# Native TLS (ps5cc): the same layout plus a PT_TLS for .tdata/.tbss (tools/ps5/ps5-pie-tls.ld).
[ "${PS5_EMUTLS:-0}" = 1 ] || radv_linker_script=(-T ${IF_ROOT:-$HOME/inFamous}/tools/ps5/ps5-pie-unwind-tls.ld
                                          -L ${IF_ROOT:-$HOME/inFamous}/tools/ps5 -L "$stage/tooling/native")
"$PS5_CLANG" --target=x86_64-sie-ps5 -fPIC -fno-plt -fno-stack-protector \
    -isysroot "$sdk_root" -isystem "$sdk_root/target/include" \
    -O2 -c "$fw/ps5_emutls.c" -o "$stage/build/ps5-emutls-cxa.o"
"$sdk_root/bin/prospero-clang" -c -O2 -fno-visibility-from-dllstorageclass \
    -o "$stage/build/ps5_stat.o" "$fw/ps5_stat.c"

"$sdk_root/bin/prospero-clang" -c -O2 -fPIC -fno-visibility-from-dllstorageclass \
    -o "$stage/build/ps5_shims.o" $HOME/if2/ps5/ps5_shims.c
# Which game this build is (its folder in the inFamous: ReCharged app: /app0/if1, if2 or fob).
case $build in
    *build-fob*) gdir=fob ;;
    *build-if1*) gdir=if1 ;;
    *)           gdir=if2 ;;
esac
"$sdk_root/bin/prospero-clang" -c -O2 -fPIC -fno-visibility-from-dllstorageclass -DPS5_GAME_DIR="\"$gdir\"" \
    -o "$stage/build/ps5_app.o" $HOME/if2/ps5/ps5_app.c
# The game's decrypted EBOOT.elf is NOT built in any more (2026-11-09): the launcher's installer decrypts it from the
# user's own dump (installer.c inst_unself). PS5_EMBED_EBOOT=1 builds it in as before (ps5_app.c ps5_put_eboot).
eboot_obj=()
if [ "${PS5_EMBED_EBOOT:-0}" = 1 ]; then
eboot_src=$HOME/$gdir/infamous2/vfs/PS3_GAME/USRDIR/EBOOT.elf
[[ -f $eboot_src ]] || { echo "ps5link: no $eboot_src" >&2; exit 1; }
cat > "$stage/build/ps5_eboot.S" <<EOF
    .section .rodata
    .balign 64
    .globl ps5_eboot_start
    .hidden ps5_eboot_start
ps5_eboot_start:
    .incbin "$eboot_src"
    .globl ps5_eboot_end
    .hidden ps5_eboot_end
ps5_eboot_end:
EOF
"$sdk_root/bin/prospero-clang" -c -fPIC -o "$stage/build/ps5_eboot.o" "$stage/build/ps5_eboot.S"
eboot_obj=("$stage/build/ps5_eboot.o")
else   # the two symbols as an empty block (a weak undefined one could end up as a dynamic import)
printf '    .section .rodata\n    .globl ps5_eboot_start\n    .hidden ps5_eboot_start\nps5_eboot_start:\n    .globl ps5_eboot_end\n    .hidden ps5_eboot_end\nps5_eboot_end:\n' > "$stage/build/ps5_eboot.S"
"$sdk_root/bin/prospero-clang" -c -fPIC -o "$stage/build/ps5_eboot.o" "$stage/build/ps5_eboot.S"
eboot_obj=("$stage/build/ps5_eboot.o")
fi

link_pie() {
    "$sdk_root/bin/prospero-lld" "${radv_linker_script[@]}" --eh-frame-hdr "${radv_link_flags[@]}" \
        --version-script "$tri/tooling/native/app-symbols.map" --exclude-libs=ALL \
        --wrap=stat --wrap=lstat --wrap=pthread_attr_setstacksize \
        --wrap=pthread_create --wrap=pthread_join --wrap=pthread_detach \
        --wrap=usleep --wrap=nanosleep --wrap=clock_gettime --wrap=sched_yield \
        --wrap=pthread_cond_wait --wrap=pthread_cond_timedwait --wrap=pthread_mutex_lock --wrap=sem_wait --wrap=sem_timedwait \
        -e _start -o "$target" \
        "$tri/build/obj/app_crt.o" "$tri/build/obj/app_cpp_runtime.o" "$stage/build/ps5_stat.o" "$stage/build/ps5_shims.o" "$stage/build/ps5_app.o" "${eboot_obj[@]}" "$@" \
        --start-group "${inputs[@]}" --end-group \
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
    echo "==> [ps5 link] again with RELRO padding (room for the process parameters)"
    "$sdk_root/bin/prospero-clang" -c -O2 -fPIC -fno-visibility-from-dllstorageclass \
        -o "$stage/build/ps5_relro_pad.o" "$fw/ps5_relro_pad.c"
    link_pie "$stage/build/ps5_relro_pad.o"
    make_eboot
fi
echo "==> [ps5 link] $target.eboot.elf ($(stat -c %s "$target.eboot.elf") bytes)"
