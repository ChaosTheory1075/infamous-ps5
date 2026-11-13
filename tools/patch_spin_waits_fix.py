# spin waits fix: plain counters (the __atomic builtins reject C11 _Atomic objects under clang)
SPC = "runtime/spu/spu_channels.c"
edit(SPC,
     '''    static _Atomic unsigned n;
    static _Atomic int us = -1;''',
     '''    static unsigned n;
    static int us = -1;''',
     "spin waits fix: spu knob")
edit(SPC,
     '''static _Atomic unsigned long s_spin_hit, s_spin_miss;''',
     '''static unsigned long s_spin_hit, s_spin_miss;''',
     "spin waits fix: spu counters")
