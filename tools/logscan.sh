#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# What the toolkit already logs (pad trace, file opens, fps line) and what ps5_app.c can call.
cd $HOME/if2/ps3recomp-fork
grep -n 'PAD_TRACE' -A6 libs/input/cellPad.c | head -40
echo ---- fs open
sed -n 862,880p runtime/ppu/ppu_fs.cpp
echo ---- fps
grep -rn 'rsx fps' --include=*.c --include=*.cpp --include=*.h . | grep -v build | head -3
echo ---- decls
grep -rn 'ppu_guest_callstack\|^extern.*vm_base\|g_active_ctx;' --include=*.h --include=*.cpp . | grep -v build | head -6
echo ---- kernel.h
H=$(find / -path /proc -prune -o -name kernel.h -path '*ps5platform*' -print 2>/dev/null | head -1); echo $H
grep -n 'Flexible\|DirectMemorySize\|sceKernelGetProcessTime\|Thread' $H | head -20
grep -rln 'ps5_app_setup' $HOME/if2/infamous2-lle/main.cpp
grep -rn 'mc_rip\|ucontext' $(dirname $H)/../ 2>/dev/null | head -3
SR=$HOME/mp3build/tri/.deps/pacbrew/v0.40.2/sysroot
ls $SR 2>/dev/null; find / -path /proc -prune -o -name ucontext.h -print 2>/dev/null | grep -iv 'linux\|gnu\|x86_64-linux\|wine' | head -5
