# spin off: both spins default to 0 -- the console's condition-variable hand-off is 3.8 us, so spinning gained nothing, and inFAMOUS 1 hung at load with it
edit("runtime/spu/spu_channels.c",
     '''        us = ps3_toggle_get("PS3_SPU_SPIN_US", e ? atoi(e) : 40);''',
     '''        us = ps3_toggle_get("PS3_SPU_SPIN_US", e ? atoi(e) : 0);''',
     "spin off: spu default")
edit("runtime/spu/spu_coherency.c",
     '''        v = ps3_toggle_get("PS3_MK_SPIN_US", e ? atoi(e) : 40);''',
     '''        v = ps3_toggle_get("PS3_MK_SPIN_US", e ? atoi(e) : 0);''',
     "spin off: kick default")
