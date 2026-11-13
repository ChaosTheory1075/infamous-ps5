#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
for g in if1 if2 fob; do
  E=$HOME/if2/ps5/build-$g/Infamous2Recomp.eboot.elf
  echo "$g slowpipe=$(strings $E | grep -c 'slow pipeline miss') vbuf=$(nm $HOME/if2/ps5/build-$g/Infamous2Recomp | grep -c 'vk_eng_vbuf_create')"
done
