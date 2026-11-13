#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Copy the SPIR-V caches collected by the Linux test runs (PS3RECOMP_SPIRV_CACHE=~/spvcache/<game>)
# into the PS5 app folders, so the first start does not translate every shader on the console.
W=${IF_ROOT:-$HOME/inFamous}/ps5
for pair in if2:PPSA95460 fob:PPSA95461 if1:PPSA95462; do
    g=${pair%%:*}; id=${pair#*:}
    src=$HOME/spvcache/$g; dst=$W/$id/cache/shaders
    mkdir -p "$dst"
    n=$(ls "$src"/*.spv 2>/dev/null | wc -l)
    [ "$n" -gt 0 ] && cp -u "$src"/*.spv "$dst"/
    echo "$id ($g): $n collected, $(ls "$dst" | wc -l) in app, $(du -sh "$dst" | cut -f1)"
done
