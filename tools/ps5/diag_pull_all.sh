#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
for g in fob if2 if1; do bash ${IF_ROOT:-$HOME/inFamous}/tools/ps5/diag_pull.sh $g > ${IF_ROOT:-$HOME/inFamous}/work/diag/$g.summary.txt 2>&1; echo "$g pulled"; done
