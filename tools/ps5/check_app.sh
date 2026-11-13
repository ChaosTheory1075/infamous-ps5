#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Compile ps5_app.c and ps5_shims.c alone the way ps5link.sh does (syntax/warnings check).
S=$HOME/mp3build/tri/.deps/native/ps5-payload-sdk
T=${IF_ROOT:-$HOME/inFamous}/tools/ps5
sed -i 's/\r$//' $T/ps5_app.c $T/ps5_shims.c
for f in ps5_app ps5_shims; do
  $S/bin/prospero-clang -c -O2 -fPIC -fno-visibility-from-dllstorageclass -Wall -o /tmp/$f.o $T/$f.c && echo "$f OK"
done
