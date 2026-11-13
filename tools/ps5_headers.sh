#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
S=$HOME/mp3build/tri/.deps/native/ps5-payload-sdk
ls $S; ls $S/target | head
I=$S/target/include
grep -n "SIGRTMIN" $I/sys/signal.h | head -3
grep -n "MAP_NORESERVE\|MAP_NOSYNC" $I/sys/mman.h | head
grep -n "TIME_UTC\|timespec_get" $I/time.h | head
ls $I/netinet | head -5
