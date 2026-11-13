#!/bin/bash
# show_fn.sh <file> <regex of the definition line> <lines before> <lines after>
F=$1; n=$(grep -n "$2" $F | head -1 | cut -d: -f1)
sed -n "$((n-$3)),$((n+$4))p" $F
