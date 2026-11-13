
# dbgsrv runtime hooks: the thread dump to any FILE, SPU contexts by index, a screenshot on demand
# For the PS5 app's debug server (tools/ps5/ps5_app.c, PS5_DEBUG_PORT): the same dump PS3_THREAD_DUMP
# writes to the log, written to a file the server sends back; an SPU context's local store by its
# slot; and g_vk_dump_now, which makes the next present write a screenshot whatever the interval.
edit("runtime/syscalls/sys_ppu_thread.c",
     '''void ps3_thread_dump_now(const char* why)
{
    {
        fprintf(stderr, "[tdump] ---- guest threads%s%s ----\\n", why ? ": " : "", why ? why : "");''',
     '''void ps3_thread_dump_to(FILE* o, const char* why);
void ps3_thread_dump_now(const char* why) { ps3_thread_dump_to(stderr, why); }
void ps3_thread_dump_to(FILE* o, const char* why)
{
    {
        fprintf(o, "[tdump] ---- guest threads%s%s ----\\n", why ? ": " : "", why ? why : "");''',
     "dbgsrv tdump head")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''            fprintf(stderr, "[tdump] tid=%-3d %-28s lr=0x%08X sp=0x%08X prof=0x%08X chain:",''',
     '''            fprintf(o, "[tdump] tid=%-3d %-28s lr=0x%08X sp=0x%08X prof=0x%08X chain:",''',
     "dbgsrv tdump tid")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''                fprintf(stderr, " 0x%x", td_rd32(next + 20)); /* low word of saved LR at +16 */
                sp = next;
            }
            fputc('\\n', stderr);
        }
        { extern void spu_dump_contexts(void); spu_dump_contexts(); }''',
     '''                fprintf(o, " 0x%x", td_rd32(next + 20)); /* low word of saved LR at +16 */
                sp = next;
            }
            fputc('\\n', o);
        }
        { extern void spu_dump_contexts_to(FILE*); spu_dump_contexts_to(o); }''',
     "dbgsrv tdump chain")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''            fprintf(stderr, "[tdump] equeue %-3d type=%d name=%.8s key=0x%llX pending=%d%s\\n", q + 1, e->type,
                    e->name, (unsigned long long)e->key, e->count, e->cancelled ? " CANCELLED" : "");
        }
        fflush(stderr);''',
     '''            fprintf(o, "[tdump] equeue %-3d type=%d name=%.8s key=0x%llX pending=%d%s\\n", q + 1, e->type,
                    e->name, (unsigned long long)e->key, e->count, e->cancelled ? " CANCELLED" : "");
        }
        fflush(o);''',
     "dbgsrv tdump tail")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''#else
void ps3_thread_dump_now(const char* why) { (void)why; }
#endif''',
     '''#else
void ps3_thread_dump_now(const char* why) { (void)why; }
void ps3_thread_dump_to(FILE* o, const char* why) { (void)o; (void)why; }
#endif''',
     "dbgsrv tdump win stub")
edit("runtime/spu/spu_channels.c",
     '''void spu_dump_contexts(void)
{
    for (int i = 0; i < SPU_MAX_CONTEXTS; i++) {
        const spu_context* c = __atomic_load_n(&s_mfc_slots[i].ctx, __ATOMIC_ACQUIRE);
        if (!c) continue;
        fprintf(stderr, "[tdump] spu ctx%-3d''',
     '''void spu_dump_contexts_to(FILE* o);
void spu_dump_contexts(void) { spu_dump_contexts_to(stderr); }
/* The context in MFC slot i (the "ctx" number the dump prints), or NULL. */
const spu_context* spu_ctx_at(int i)
{
    if (i < 0 || i >= SPU_MAX_CONTEXTS) return NULL;
    return __atomic_load_n(&s_mfc_slots[i].ctx, __ATOMIC_ACQUIRE);
}
/* That context's local store (256 KB), for the debug server's "ls". */
const uint8_t* spu_ctx_ls(int i)
{
    const spu_context* c = spu_ctx_at(i);
    return c ? c->ls : NULL;
}
void spu_dump_contexts_to(FILE* o)
{
    for (int i = 0; i < SPU_MAX_CONTEXTS; i++) {
        const spu_context* c = __atomic_load_n(&s_mfc_slots[i].ctx, __ATOMIC_ACQUIRE);
        if (!c) continue;
        fprintf(o, "[tdump] spu ctx%-3d''',
     "dbgsrv spu ctx dump to")
edit("libs/video/rsx_vulkan_backend.c",
     '''static void vk_dump_ppm(const unsigned char* rgba)
{''',
     '''int g_vk_dump_now;   /* the PS5 debug server's "shot": the next present writes one */
static void vk_dump_ppm(const unsigned char* rgba)
{''',
     "dbgsrv shot flag")
edit("libs/video/rsx_vulkan_backend.c",
     '''        if (last_ns && now - last_ns < (unsigned long long)(every * 1e9)) return;''',
     '''        if (last_ns && now - last_ns < (unsigned long long)(every * 1e9) && !g_vk_dump_now) return;
        g_vk_dump_now = 0;''',
     "dbgsrv shot now")
