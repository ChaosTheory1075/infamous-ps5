#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
S=$HOME/mp3build/tri/.deps/native/ps5-payload-sdk/target/lib
for l in $S/libc.so $S/libkernel.so $S/libSceLibcInternal.so; do [ -f $l ] && echo "== $l" && llvm-nm-18 -D --defined-only $l 2>/dev/null | grep -wE "setjmp|longjmp|_setjmp|_longjmp|sigsetjmp|siglongjmp|__setjmp|tmpfile|timegm|mkstemp|sbrk" ; done
ls $S | head -50
grep -rn "_setjmp\|_longjmp\|tmpfile\|timegm\|sbrk" $HOME/if2/ps3recomp-fork/runtime $HOME/if2/ps3recomp-fork/libs --include=*.c --include=*.cpp --include=*.h | grep -v "^.*//" | head -12
