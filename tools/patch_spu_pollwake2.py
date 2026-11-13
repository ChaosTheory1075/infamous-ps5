
# spu pollwake probe counters: plain unsigned long with __atomic builtins (clang refuses _Atomic there)
edit("runtime/spu/spu_channels.c",
     '''static _Atomic unsigned long s_pw; static uint32_t s_pw_ea[32]; static _Atomic int s_pw_n;''',
     '''static unsigned long s_pw; static uint32_t s_pw_ea[32]; static int s_pw_n;''',
     "spu pollwake counters plain")
edit("runtime/spu/spu_channels.c",
     '''            static _Atomic unsigned long s_sig, s_to, s_tot;''',
     '''            static unsigned long s_sig, s_to, s_tot;''',
     "spu pollwake wait counters plain")
