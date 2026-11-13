#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Summary of a console log (logs/infamous2.log from an app folder), crash report resolved to names.
#   readlog.sh <log> <if2|fob|if1>
L=$1; G=${2:-if2}
ELF=$HOME/if2/ps5/build-$G/Infamous2Recomp   # the unstripped link (eboot.elf is made from it)
echo "== start"; grep -a -m3 -E '^=== |\[ps5\] (anchor|guest memory)' "$L"
echo "== errors / failures (first 25)"
grep -a -iE 'failed|error|abort|stuck|CRASH' "$L" | grep -av 'status:' | head -25
echo "== last status lines"; grep -a '\[ps5\] status' "$L" | tail -3
echo "== frame rate (last 5)"; grep -a '\[rsx fps\] [0-9]' "$L" | tail -5
echo "== controller (last 5)"; grep -a -i 'pad' "$L" | grep -av 'env' | tail -5
echo "== last 15 lines"; tail -n 15 "$L" | cut -c1-200
grep -aq 'CRASH:' "$L" || exit 0
echo "== crash, resolved with nm $ELF"
base=$(nm "$ELF" | awk '$3=="ps5_app_setup"{print $1}')
nm -n "$ELF" | awk '$2 ~ /[tTwW]/' > /tmp/readlog.syms
offs=$(grep -a -A3 'CRASH:' "$L" | grep -aoE 'anchor[+-][0-9]+|addresses \(anchor\+offset\):.*' | grep -aoE '[+-][0-9]+')
for o in $offs; do
    a=$(( 0x$base + o ))
    printf '%+12d  0x%x  ' "$o" $a
    awk -v a=$a 'BEGIN{best=""} { v=strtonum("0x"$1); if (v<=a) best=$3; else exit } END{print best}' /tmp/readlog.syms
done
