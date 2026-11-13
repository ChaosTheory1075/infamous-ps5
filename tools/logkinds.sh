#!/bin/bash
# Most common line kinds (first bracketed tag) in a console log.
#   logkinds.sh <log> [n]
grep -ao '\[[A-Za-z0-9_ /.-]*\]' "$1" | sort | uniq -c | sort -rn | head -${2:-25}
