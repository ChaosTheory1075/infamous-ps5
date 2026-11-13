#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Shader-cache sizes and shader translation failures per run. usage: runcheck.sh <run> ...
date +%T
for g in if2 fob if1; do echo "cache $g: $(ls $HOME/spvcache/$g | wc -l)"; done
pat='out of range|translat.*fail|glslang.*(error|fail)|spirv.*fail|ERROR:'
for r in "$@"; do
    L=$HOME/if2/runs/$r/run.log
    echo "== $r: $(wc -l < $L) lines, $(grep -acE "$pat" $L) shader errors; $(ls $HOME/if2/runs/$r | grep -c ppm) frames"
    grep -aE "$pat" $L | cut -c1-200 | sort | uniq -c | sort -rn | head -5
    grep -a 'fps' $L | tail -1 | cut -c1-160
done
