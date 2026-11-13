#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# All thread stacks of a running port into ~/if2/stacks-<game>.txt, then a per-thread summary
# (thread name, top host frame, first lifted guest function). usage: allstacks.sh <if1|if2|fob>
pid=$(pgrep -f "^$HOME/$1/infamous2-lle/build/Infamous2Recomp")
out=$HOME/if2/stacks-$1.txt
gdb -q -batch -p $pid -ex "thread apply all bt 40" > $out 2>/dev/null
awk '
/^Thread /{ if (hdr) print hdr " | " top " | " guest; hdr=$0; sub(/ \(Thread.*LWP/," LWP",hdr); top=""; guest=""; next }
/^#[0-9]/{ f=$0; sub(/^#[0-9]+ +(0x[0-9a-f]+ in )?/,"",f); sub(/ \(.*$/,"",f);
           if (top=="") top=f;
           else if (index(top, f)==0 && length(top) < 120 && f !~ /^(ps3_|ppu_|vm_|lv2_|DRAIN)/ && guest=="") top=top " < " f;
           if (guest=="" && f ~ /func_/) guest=f }
END{ print hdr " | " top " | " guest }' $out | cut -c1-260
