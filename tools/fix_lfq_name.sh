#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
sed -i 's/strcmp(m->name, "libsre")) return;/(strcmp(m->name, "libsre") \&\& strcmp(m->name, "cellSre_Library"))) return;/' $HOME/if2/ps3recomp-fork/runtime/syscalls/lv2_prx.c
grep -n 'cellSre_Library' $HOME/if2/ps3recomp-fork/runtime/syscalls/lv2_prx.c
grep -c cellSre_Library ${IF_ROOT:-$HOME/inFamous}/tools/if2_patch_toolkit.py ${IF_ROOT:-$HOME/inFamous}/tools/patch_lfq_poll.py
