#!/bin/bash
# show.sh <file> <pattern> [lines]: print lines from the first match
f=$1; n=$(grep -n -m1 -- "$2" "$f" | cut -d: -f1); [ -z "$n" ] && { echo "no match"; exit 1; }
sed -n "${n},$((n + ${3:-15}))p" "$f"
