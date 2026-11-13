#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
F=$HOME/cdbuild/fw-clean/glue/rexglue-sdk-main
grep -rlE '^int main|PS5_MAIN|ps5_main' $F/src $F/gta4-recomp/src 2>/dev/null | head -5
grep -rhoE 'sce[A-Z][A-Za-z]+\(' $F/src/core/*ps5* $F/src/app/*ps5* $F/gta4-recomp/src/ps5/*.cpp $F/src/*/ps5/*.cpp 2>/dev/null | sort | uniq -c | sort -rn | head -40
