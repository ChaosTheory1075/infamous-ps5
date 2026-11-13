#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Headless inFamous 2 run on Linux: if2_run.sh <name> <seconds> [VAR=value ...]
# Log in ~/if2/runs/<name>/run.log, last Vulkan frame in frame.ppm (+ frame.png on Windows side).
name=$1; secs=$2; shift 2
R=$HOME/if2/runs/$name
rm -rf "$R"; mkdir -p "$R"; cd "$R"
export HEADLESS=1 PS3_LANG=en PS3_DEV_FLASH=${RPCS3_DIR:?set RPCS3_DIR (tools/local.env)}/dev_flash
export PS3RECOMP_RSX_ENGINE=dispatch PS3RECOMP_VK_GUEST_PROGRAMS=1 PS3RECOMP_VK_DUMP=$R/frame.ppm
export PS3RECOMP_ENG_FPSLOG=1 PS3_GAMEDATA_ROOT=$HOME/if2/gamedata
for kv in "$@"; do export "$kv"; done
# PS5-like CPU budget (user 2026-11-10): PS5 games get 6.5 cores / 13 threads; the BC-250 (6 cores / 12 threads after a cold boot) runs on all 12 threads by default. (The old 0-4 = 5 SMT threads = 2.5 cores, wrong.)
C=${BC_CORES:-$( [ "$(nproc)" -ge 13 ] && echo 0-12 || echo 0-$(( $(nproc) - 1 )) )}; if [ "$C" = all ]; then sh "${RUNSH:-$HOME/if2/infamous2-lle/run.sh}" > run.log 2>&1 &
else taskset -c "$C" sh "${RUNSH:-$HOME/if2/infamous2-lle/run.sh}" > run.log 2>&1 &
fi
pid=$!
for ((i = 0; i < secs; i += 5)); do
    sleep 5
    kill -0 $pid 2>/dev/null || break
    # keep a copy of the frame every minute
    if (( i % 60 == 55 )) && [ -f frame.ppm ]; then cp frame.ppm "frame_$((i + 5))s.ppm"; fi
done
if kill -0 $pid 2>/dev/null; then pkill -9 -f "^$(dirname "${RUNSH:-$HOME/if2/infamous2-lle/run.sh}")/build[-a-z0-9]*/Infamous2Recomp"; echo "stopped after ${secs}s"; else echo "exited by itself"; fi
wait $pid 2>/dev/null; rc=$?; echo "[if2_run] game exit code $rc" >> run.log; echo "exit code $rc"
echo "log lines: $(wc -l < run.log)"
D=${IF_ROOT:-$HOME/inFamous}/work/if2-frames/$name
mkdir -p "$D"
for f in frame*.ppm; do [ -f "$f" ] && python3 -c "
import sys
d=open(sys.argv[1],'rb').read()
" "$f" && cp "$f" "$D/"; done
ls "$D"
