#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Trial-compile ps3recomp (inFamous 2 toolkit) sources with the PS5 compiler. Prints per-file status
# and the first errors. usage: ps5_trial.sh [file-glob ...]  (default: the runtime + libs C sources)
TRI=$HOME/mp3build/tri
SDK=$TRI/.deps/native/ps5-payload-sdk
PAC=$(ls -d $TRI/.deps/pacbrew/*/sysroot 2>/dev/null | head -1)
TK=$HOME/if2/ps3recomp-fork
OUT=$HOME/if2/ps5trial
mkdir -p $OUT
cc() { PS5_PAYLOAD_SDK=$SDK sh $TRI/tooling/prospero-clang18 "$@"; }
inc="-I$TK/include -I$TK/runtime -I$TK/libs -I$TK/third_party -I$PAC/user/homebrew/include/SDL2 -I$PAC/user/homebrew/include -I${IF_ROOT:-$HOME/inFamous}/deps/Vulkan-Headers/include $(for d in $TK/libs/*/; do printf -- "-I%s " $d; done) -I$TK/runtime/spu -include ${IF_ROOT:-$HOME/inFamous}/tools/compat/ps5/ps5_compat.h -DPS3RECOMP_PS5=1"
files=("$@")
[ ${#files[@]} -eq 0 ] && files=($TK/runtime/*/*.c $TK/runtime/*/*.cpp $TK/libs/*/*.c $TK/libs/*/*.cpp)
ok=0; bad=0
: > $OUT/errors.txt
for f in "${files[@]}"; do
    case $f in *_win32*|*/tests/*|*metal*) continue;; esac
    if [[ $f == *.cpp ]]; then std=-std=gnu++20; else std=-std=gnu11; fi
    if cc $std -O1 -w $inc -c "$f" -o $OUT/$(basename "$f").o 2> $OUT/err.txt; then
        ok=$((ok + 1))
    else
        bad=$((bad + 1))
        echo "== $f" >> $OUT/errors.txt
        grep -m3 'error' $OUT/err.txt >> $OUT/errors.txt
    fi
done
echo "ok $ok, failed $bad (sysroot pacbrew: $PAC)"
grep -h 'error' $OUT/errors.txt | sed -E 's/^[^ ]+ //' | sort | uniq -c | sort -rn | head -25
