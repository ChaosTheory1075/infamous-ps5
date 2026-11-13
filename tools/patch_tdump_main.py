
# tdump main thread live ctx: PS3_THREAD_DUMP read the main thread's table copy (lr/sp 0)
# The main guest thread runs on the loader's local ppu_context, not g_ppu_threads[0].ctx, so the
# dump showed it as lr=0 sp=0 -- and a main thread spinning in guest code is exactly what it is for.
edit("runtime/ppu/ppu_loader.cpp",
     '''    { extern uint64_t ppu_thread_register_main(void);
      ctx.thread_id = ppu_thread_register_main(); }''',
     '''    { extern uint64_t ppu_thread_register_main(void);
      ctx.thread_id = ppu_thread_register_main(); }
    { extern "C" ppu_context* g_ppu_main_ctx_live; g_ppu_main_ctx_live = &ctx; }   /* tdump */''',
     "tdump main live ctx set")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''int32_t g_ppu_primary_prio = 1001;''',
     '''int32_t g_ppu_primary_prio = 1001;
/* The main thread's live context (ppu_loader.cpp), for PS3_THREAD_DUMP. */
ppu_context* g_ppu_main_ctx_live;''',
     "tdump main live ctx def")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''            const ppu_context* c = &t->ctx;
            fprintf(stderr, "[tdump] tid=%-3d %-28s lr=0x%08X sp=0x%08X prof=0x%08X chain:",''',
     '''            const ppu_context* c = (i == 0 && g_ppu_main_ctx_live) ? g_ppu_main_ctx_live : &t->ctx;
            fprintf(stderr, "[tdump] tid=%-3d %-28s lr=0x%08X sp=0x%08X prof=0x%08X chain:",''',
     "tdump main live ctx use")
