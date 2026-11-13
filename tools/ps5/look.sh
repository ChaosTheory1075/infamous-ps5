#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
ls $HOME/cdbuild/fw-clean/ps5/tools/ 2>/dev/null | head; ls $HOME/mp3build/tri/build/obj/ $HOME/mp3build/tri/build/stubs/ $HOME/mp3build/tri/build/host/ 2>/dev/null | head -20
S=$HOME/mp3build/tri/.deps/native/ps5-payload-sdk/target/lib
ls $S | grep -iE "SceSystemService|SceUserService|ScePad|SceAudioOut|SceVideoOut|SceKeyboard|SceImeDialog|libkernel|libc\b|platform" | head -20
ls $HOME/mp3build/tri/.deps/pacbrew/v0.40.2/sysroot/user/homebrew/lib | grep -iE "iconv|samplerate|SDL2" | head
