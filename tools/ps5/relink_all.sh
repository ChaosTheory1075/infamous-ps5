#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Relink + repackage the given PS5 apps (default all three), e.g. after a ps5_app.c change.
for g in "${@:-if2 fob if1}"; do
    for one in $g; do bash ${IF_ROOT:-$HOME/inFamous}/tools/ps5/relink_if2.sh $one; done
done
