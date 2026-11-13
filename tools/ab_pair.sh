#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# ab_pair.sh <name> <TOGGLE_NAME> <off value> <on value> [VAR=value ...]
# In-run A/B on the BC-250 route (the user's route1 recording from their PS3 save): the toggle line
# switches every 1.5 s from 98 s, a 60 s ftrace window from 100 s records RSX drain per frame, and each
# "on" stretch is compared with the mean of its two "off" neighbours (scene drift between stretches made
# 4 s alternation and whole-run A/Bs unreliable, 2026-11-05). Prints the paired median/mean change.
name=$1; knob=$2; off=$3; on=$4; shift 4
WIN=${WIN:-60}; NSW=$(( WIN * 2 / 3 + 4 ))   # window seconds; switches (1.5 s each) to cover it
T=$HOME/if1/$name.toggles; echo "$knob=$off" > $T
( sleep 98; v=0; for i in $(seq 1 $NSW); do v=$((1-v)); if [ $v = 1 ]; then echo "$knob=$on" > $T.tmp; else echo "$knob=$off" > $T.tmp; fi; mv $T.tmp $T; sleep 1.5; done ) &
D=$HOME/if1/gamedata/dev_hdd0/home/00000001/savedata; rm -rf $D/BCES00220_INFAMOUS_*; cp -a $HOME/if1/savedata_ps3_user/BCES00220_INFAMOUS_* $D/
cd ~/inFamous/work
IF1_PAD="0:0x0000" timeout $((WIN + 250)) bash bc_if1_run.sh $name $((WIN + 115)) PS3_DEVPAD_REPLAY=$HOME/if1/route1.pad PS3_DEVPAD_REPLAY_AT=0 \
  PS3_FTRACE=100:$WIN:$HOME/if1/$name PS3_FTRACE_CAP=8000000 PS3_TOGGLE_FILE=$T "$@" > /dev/null 2>&1
wait
grep -a -i 'Segmentation\|SIGSEGV\|VK_ERROR_DEVICE_LOST\|device lost' $HOME/if2/runs/$name/run.log | head -2
python3 -I $HOME/if2/infamous2-lle/tools/ftrace_report.py $HOME/if1/$name --phases --settle 300 2>&1 | grep -A1 ' s  ' | paste - - | \
  python3 -I -c "
import sys, re, statistics
seg = []
for l in sys.stdin:
    m = re.search(r'=(-?\d+).*?(\d+) frames.*?drain\s+([\d.]+)', l)
    if m: seg.append((m.group(1) == '$on', int(m.group(2)), float(m.group(3))))
r = [seg[i][2] / ((seg[i-1][2] + seg[i+1][2]) / 2) - 1 for i in range(1, len(seg) - 1)
     if seg[i][0] and not seg[i-1][0] and not seg[i+1][0] and seg[i][1] >= 8]
on = [d for k, n, d in seg if k]; off = [d for k, n, d in seg if not k]
if r: print('$name: %d segments, paired n=%d: median %+.1f%%, mean %+.1f%%; drain off %.1f on %.1f ms/frame' % (
    len(seg), len(r), 100 * statistics.median(r), 100 * statistics.mean(r), statistics.mean(off), statistics.mean(on)))
else: print('$name: no paired segments (game not in gameplay?)')
"
