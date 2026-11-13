#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Run a zen2 build of inFamous 2 with rendering off and, from 100 s in, take <n> all-thread stack
# snapshots one second apart; print each thread's top frames per snapshot.   stacksample.sh [n]
N=${1:-6}
S=$HOME/if2/infamous2-lle
(RUNSH=$S/run-zen2.sh bash ${IF_ROOT:-$HOME/inFamous}/tools/if2_run.sh ss1 150 PS3RECOMP_RSX_ENGINE=off PS3_VERBOSE=0 > /tmp/ss1.out 2>&1 &)
sleep 100
pid=$(pgrep -f "^$S/build-zen2/Infamous2Recomp" | head -1)
echo "pid $pid"
for i in $(seq 1 $N); do
  gdb -q -batch -p $pid -ex "thread apply all bt 14" 2>/dev/null > /tmp/ss-$i.txt
  sleep 1
done
pkill -9 -f "$S/build-zen2/Infamous2Recomp"
for i in $(seq 1 $N); do
  echo "=================== snapshot $i"
  awk '
  /^Thread /{ if (hdr != "") print hdr " | " fr; hdr=$0; sub(/ \(Thread 0x[0-9a-f]+ /," ",hdr); sub(/\):$/,"",hdr); fr=""; n=0; next }
  /^#[0-9]/{ f=$0; sub(/^#[0-9]+ +(0x[0-9a-f]+ in )?/,"",f); sub(/ \(.*$/,"",f); if (n < 6) fr = fr (n ? " < " : "") f; n++ }
  END{ print hdr " | " fr }' /tmp/ss-$i.txt | grep -v 'syscall_cp\|^$' | cut -c1-300
done
