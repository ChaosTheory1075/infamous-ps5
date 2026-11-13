#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Put the toolkit's Vulkan backend back to Noah's fork + erikomis's patch, forget the edits recorded
# for it, and re-apply tools/if2_patch_toolkit.py once.
set -e
TK=$HOME/if2/ps3recomp-fork
F=libs/video/rsx_vulkan_backend.c
P=$HOME/if2/src/infamous2-lle/patches/ps3recomp-fork-770660a-with-upstream-prs.patch
cd $TK
git checkout -- $F
git apply --include=$F $P 2>/dev/null || true
echo "patch lines touching $F: $(grep -c "^+++ b/$F" $P)"
# keep only the recorded tags that are not about this file (the others stay applied)
python3 - <<'EOF'
import re
src = open(__import__("os").environ.get("IF_ROOT", __import__("os").path.expanduser("~/inFamous")) + "/tools/if2_patch_toolkit.py").read()
vk_tags = set(re.findall(r'"([^"]+)"(?:, optional=True)?\)\s*$', src, re.M))
p = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/.if2_patches_applied"
import os
keep = []
if os.path.exists(p):
    keep = [t for t in open(p).read().split("\n") if t]
non_vk = {"PS5 SPU setjmp", "PS5 vm commit no-op"}
open(p, "w").write("\n".join(t for t in keep if t in non_vk) + "\n")
EOF
python3 ${IF_ROOT:-$HOME/inFamous}/tools/if2_patch_toolkit.py $TK | tail -3
echo "applied: $(wc -l < $TK/.if2_patches_applied) tags"
grep -c "^static int vk_batching" $TK/$F
grep -c "^static vk_eng_obj\* vk_eng_snap2" $TK/$F
grep -c "^#define PS5_LOAD_G" $TK/$F
