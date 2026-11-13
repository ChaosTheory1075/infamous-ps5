# spu contention fix reverted (BC-250, 2026-11-01): with it FoB stalls for good at the menu load (the
# step after load_menu_catalog.log never runs; SPUs idle, main thread pacing a loading screen); with
# -DSPU_NO_CONTENTION_FIX the same build plays on. Off by default now; -DSPU_CONTENTION_FIX brings it back.
for _f in (CHN, COH):
    edit(_f, '''#include''', '''#ifndef SPU_CONTENTION_FIX   /* spu contention fix off: it stalled FoB's menu load */
#  define SPU_NO_CONTENTION_FIX 1
#endif
#include''', "spu contention off: " + _f)
