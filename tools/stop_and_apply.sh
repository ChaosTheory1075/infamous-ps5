#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Stop any PS5 build, apply pending toolkit edits, and build the Linux zen2 inFamous 2.
for p in $(pgrep -f 'relink_all|build_if2|build_all_ps5'); do [ "$p" != "$$" ] && kill $p 2>/dev/null; done
for p in $(pgrep -x ninja); do kill $p 2>/dev/null; done
sleep 2
bash ${IF_ROOT:-$HOME/inFamous}/tools/apply_patches.sh
cd $HOME/if2/infamous2-lle/build-zen2 && ninja 2>&1 | grep -E ' error|FAILED|Linking' | head -20
