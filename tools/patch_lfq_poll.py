# lfq poll: libsre's blocking LFQueue push/pop polls a non-blocking call instead of sleeping on lv2
edit("runtime/syscalls/lv2_prx.c",
     '''static void reg_fn(uint32_t addr, void (*fn)(void*)) { ppu_register_function(addr, (void (*)(ppu_context*))fn); }''',
     '''static void reg_fn(uint32_t addr, void (*fn)(void*)) { ppu_register_function(addr, (void (*)(ppu_context*))fn); }

/* libsre's SPURS LFQueue, blocking side. A blocking _cellSpursLFQueuePushBody /
 * PopBody that finds the queue full (empty) registers the PPU thread as a
 * waiter in the queue line (+0x20..) and sleeps in sys_event_queue_receive on
 * the queue's lv2 event queue until the SPU side wakes it. On the console that
 * path failed after a few minutes of streaming: the push returned an error,
 * inFAMOUS: Festival of Blood's EDGE zlib queue asserted
 * (edgezlib_inflate_queue.cpp:425, 0 == ret), and the inflate SPU later ran a
 * garbage request and branched into its own data (SPURS aborted).
 *
 * The non-blocking call returns CELL_SYNC_ERROR_AGAIN before it touches the
 * line when there is no room, so polling it does what a blocking call does
 * without the waiter registration or the event queue: the wrapper below calls
 * the lifted libsre function with the blocking bit clear and retries AGAIN
 * after a short sleep. Any other error is logged with the queue line.
 * PS3_LFQ_POLL=0 turns it off. */
#ifndef _WIN32
#include <unistd.h>
#endif
extern PPU_THREAD_LOCAL void (*g_trampoline_fn)(void*);
#define LFQ_NID_PUSH 0x8A85674Du
#define LFQ_NID_POP  0x35DAE22Bu
static void (*s_lfq_orig[2])(void*);

static void lfq_polled(ppu_context* ctx, int which)
{
    const uint64_t a3 = ctx->gpr[3], a4 = ctx->gpr[4], a5 = ctx->gpr[5], r2 = ctx->gpr[2], lr = ctx->lr;
    const int blocking = (int)(a5 & 1u);
    int32_t rc = 0;
    for (unsigned n = 0;; n++) {
        ctx->gpr[3] = a3; ctx->gpr[4] = a4; ctx->gpr[5] = blocking ? (a5 & ~1ull) : a5;
        ctx->gpr[2] = r2; ctx->lr = lr;
        s_lfq_orig[which]((void*)ctx);
        while (g_trampoline_fn) { void (*tf)(void*) = g_trampoline_fn; g_trampoline_fn = 0; tf((void*)ctx); }
        rc = (int32_t)ctx->gpr[3];
        if (!blocking || rc != (int32_t)0x80410101u) break;
        if (n == 20000) {
            static int s_full = 0;
            if (s_full++ < 8)
                fprintf(stderr, "[lfq] %s q=0x%08X still %s after ~2 s of polling\\n",
                        which ? "pop" : "push", (uint32_t)a3, which ? "empty" : "full");
        }
#ifndef _WIN32
        usleep(100);
#else
        Sleep(0);
#endif
    }
    if (rc != 0) {
        static int s_err = 0;
        if (s_err++ < 16) {
            const uint8_t* q = vm_base + (uint32_t)a3;
            fprintf(stderr, "[lfq] %s q=0x%08X flags=%u returned 0x%08X; line:", which ? "pop" : "push",
                    (uint32_t)a3, (unsigned)a5, (uint32_t)rc);
            for (int o = 0; o < 128; o += 4) fprintf(stderr, "%s%02X%02X%02X%02X", o % 32 ? " " : "\\n   ", q[o], q[o+1], q[o+2], q[o+3]);
            fprintf(stderr, "\\n");
        }
    }
    ctx->gpr[2] = r2;
    ctx->lr = lr;
}
static void lfq_push_polled(ppu_context* ctx) { lfq_polled(ctx, 0); }
static void lfq_pop_polled(ppu_context* ctx)  { lfq_polled(ctx, 1); }

/* After libsre is placed: put the wrappers at its push and pop functions. */
static void lfq_install(const prx_module* m)
{
    const char* e = getenv("PS3_LFQ_POLL");
    if ((e && *e == '0') || !m->name || (strcmp(m->name, "libsre") && strcmp(m->name, "cellSre_Library"))) return;
    for (uint32_t i = 0; i < m->export_count; i++) {
        const int which = m->exports[i].nid == LFQ_NID_PUSH ? 0 : m->exports[i].nid == LFQ_NID_POP ? 1 : -1;
        if (which < 0) continue;
        const uint32_t fn_ea = rd32(m->base + m->exports[i].vaddr);   /* the OPD's code address */
        for (uint64_t k = 0; k < m->func_count; k++)
            if ((uint32_t)m->funcs[k].addr == fn_ea) { s_lfq_orig[which] = m->funcs[k].func; break; }
        if (!s_lfq_orig[which]) { fprintf(stderr, "[lfq] %s at 0x%08X: no lifted function\\n", which ? "pop" : "push", fn_ea); continue; }
        ppu_register_function(fn_ea, which ? lfq_pop_polled : lfq_push_polled);
        fprintf(stderr, "[lfq] libsre LFQueue %s (0x%08X) polls instead of blocking\\n", which ? "pop" : "push", fn_ea);
    }
}''',
     "lfq poll: wrapper")
edit("runtime/syscalls/lv2_prx.c",
     '''    if (m) prx_place_module(&m->mod, reg_fn);''',
     '''    if (m) { prx_place_module(&m->mod, reg_fn); lfq_install(&m->mod); }''',
     "lfq poll: install")
