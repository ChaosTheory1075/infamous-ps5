#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Relift inFAMOUS 1's WWS job policy module (LS 0xA00) with the return points 0x3258 / 0x3260 as
# extra entries: the job call (bisl $5) and the call to 0x2660 return there, and when the host call
# chain was unwound (stop/irq path) the return came in through spu_indirect_branch with no lifted
# function -> interpreter ([ibstat] nofn pcs 03258 / 03260 on spu 2005, console 2026-11-01).
cd $HOME/if1/infamous2-lle || exit 1
T=$(mktemp -d)
$HOME/if2/.venv/bin/python $HOME/if2/ps3recomp-fork/tools/spu_lifter.py spu/images/wwsjob_pm_at_0069CD80.elf \
  --auto-functions spu/images/wwsjob_pm_at_0069CD80.elf --symbol-prefix wwsjob_pm_at_0069CD80_ -o $T \
  --extra-funcs 0x3258,0x3260 | tail -2
D=spu/wwsjob_pm_at_0069CD80
sed 's|#include "../../runtime/spu/spu_helpers.h"|#include "spu_helpers.h"|' $T/spu_recomp.c > $D/spu_recomp.c
sed 's|#include "../../runtime/spu/spu_context.h"|#include "spu_context.h"|' $T/spu_recomp.h > $D/spu_recomp.h
rm -rf $T
