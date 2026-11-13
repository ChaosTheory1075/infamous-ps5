#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# postlift.sh <if1|if2|fob>: the edits a port tree (~/<game>/infamous2-lle) gets AFTER a lift, in the order
# they were applied to the trees the test builds are made from (work/LOOP_PERF_ALL.md 2026-11-08 .. 11-11).
# A relift drops every one of them. Every step is idempotent and keeps its own backup.
# Prints the commands; GO=1 runs them. (2026-11-11: the list was written from the log and the trees' backups;
# each tool was checked alone, the whole chain has not been run on a fresh lift yet -- compare one tree first.)
G=$1; case $G in if1|if2|fob) ;; *) echo "usage: [GO=1] $0 if1|if2|fob" >&2; exit 1;; esac
T=$(cd "$(dirname "$0")" && pwd); W=$T/../work; P=$HOME/$G/infamous2-lle
J867=$P/spu/jobmod_867e5d2348b3_e2898
step() { echo "+ $*"; [ -z "$GO" ] || "$@" || { echo "FAILED: $*" >&2; exit 1; }; }

# 1. spu lsb: ctx->ls in a local per lifted function (needs SPU_LIFTED_LSB, step 9)
step python3 $T/spu_lsb.py $P/spu/*/spu_recomp.c $P/lle_spu/*/spu_recomp.c
# 2. const gates: no source edit, the SPU_LIFTED_CONST_GATES define (step 9)
# 3. spu jtab: jump tables -> switch of direct tail calls
step python3 $T/spu_jtab.py $P/spu
# 4. spu leaf: straight-line leaf callees without the call bracket
step python3 $T/spu_leaf.py $P/spu
# 5. spu shufb same: spu_shufb(r, r, c) -> spu_shufb_same(r, c)
step python3 $T/spu_shufsame.py $P/spu
# 5b. if1 only: RPCS3's "(Experimental) Unstable audio" in the lifted code, behind g_if1_unst_audio (defined in
#     game_patches.cpp by tools/if1_patch_port.py; PS3_IF1_AUDIO_PATCH=0, the ps5_app.c default, turns it off).
#     Before the PPU rewrites: it matches the lifter's own lines (applied 2026-11-07, before step 6).
if [ $G = if1 ]; then step python3 $T/patch_if1_unstable_audio.py $P/recompiled; fi
# 6. ppu sp fast: r1-relative guest accesses -> vm_sp_* (block: work/ppu_sp_block.h)
step python3 $W/ppu_sp_patch.py $P/recompiled
# 7. FoB only: ppu scan 346920 (after step 6)
[ $G = fob ] && step python3 $T/fob_ppu_scan346920.py $P/recompiled
# 8. if2 + FoB: native867e5 (compiled in, runs only with PS3_NATIVE_867E5=1)
if [ $G != if1 ]; then
  step cp $W/native867e5/native867e5.c $J867/native867e5.c
  step bash $W/native867e5/hook.sh $J867/spu_recomp.c
fi
# 9. the port's CMakeLists.txt: defines for 1 + 2, per-game float modes, native867e5 source
step python3 $T/patch_port_cmake.py $G $P
# 10. if1 only: the lifted headers' guest accesses through PPU_VMB (= vm_base unless the port is configured with
#     -DPPU_VM_BASE_CONST, step 9; main.cpp's side is tools/if1_patch_port.py)
if [ $G = if1 ]; then step python3 $T/patch_ppu_vmb_header.py $P; fi
# main.cpp is not part of this: tools/ps5/build_if2.sh patches ~/<game>/src/infamous2-lle/main.cpp with
# tools/if2_patch_rebuild.py (Vulkan, guest VM, PS5 entry, vblank 59.94, flip cap, rsx doorbell) -- for if1 then
# tools/if1_patch_port.py (constant guest base; also game_patches.cpp) -- and copies it into the port.
