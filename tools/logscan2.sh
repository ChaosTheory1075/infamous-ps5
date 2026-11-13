#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
nm -u $HOME/if2/ps5/launcher/launcher | awk '{print $NF}' | sort -u > /tmp/lu.txt
nm -u $HOME/if2/ps5/build-if2/Infamous2Recomp | awk '{print $NF}' | sort -u > /tmp/gu.txt
echo "undefined in launcher, not in the game:"; comm -23 /tmp/lu.txt /tmp/gu.txt
