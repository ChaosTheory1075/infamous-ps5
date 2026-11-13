#!/bin/sh
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# INFAMOUS2_EXE=gdbwrap.sh: run the game under gdb, print every thread's backtrace on a crash.
exec gdb -q -batch -ex "handle SIGSEGV stop" -ex "handle SIGBUS stop" -ex "handle SIGUSR1 nostop noprint" -ex "handle SIGUSR2 nostop noprint" -ex run -ex "bt 30" -ex "info registers rip" -ex "thread apply all bt 6" --args $HOME/if2/infamous2-lle/build/Infamous2Recomp "$@"
