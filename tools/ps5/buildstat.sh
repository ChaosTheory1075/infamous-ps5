#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Where the PS5 builds are: each game's .out time and the last ninja line of its log.
ls -la --time-style=+%H:%M $HOME/if2/ps5/build-*.out
for g in if2 fob if1; do
  echo "$g: $(grep -ao '\[[0-9]*/[0-9]*\]' $HOME/if2/ps5/build-$g.log | tail -1) $(grep -c '^FAILED' $HOME/if2/ps5/build-$g.log) failed, log $(stat -c %y $HOME/if2/ps5/build-$g.log | cut -c12-16)"
done
pgrep -fa 'build_if2.sh|build_all_ps5|ninja' | cut -c1-120 | head -5
