
# tdump main live ctx linkage: extern "C" is file-scope only in C++
edit("runtime/ppu/ppu_loader.cpp",
     '''    { extern "C" ppu_context* g_ppu_main_ctx_live; g_ppu_main_ctx_live = &ctx; }   /* tdump */''',
     '''    g_ppu_main_ctx_live = &ctx;   /* tdump */''',
     "tdump main live ctx set2")
edit("runtime/ppu/ppu_loader.cpp",
     '''extern "C" int32_t  g_ppu_primary_prio;   /* main thread priority (sys_ppu_thread.c) */''',
     '''extern "C" int32_t  g_ppu_primary_prio;   /* main thread priority (sys_ppu_thread.c) */
extern "C" ppu_context* g_ppu_main_ctx_live; /* PS3_THREAD_DUMP (sys_ppu_thread.c) */''',
     "tdump main live ctx decl")
