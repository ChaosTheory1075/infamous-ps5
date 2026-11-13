
# evq stall dump: PS3_EVQ_STALL=<seconds> -- a blocking sys_event_queue_receive (timeout 0) that has
# waited this long with nothing arriving prints, once per thread and queue (16 reports in all), the
# waiter's registers and a hex dump of every guest object its registers point at (128-byte aligned:
# a CellSpursEventFlag is), then keeps waiting. For the 21:22 console run's streaming stall: fios
# mediathread tid 14 sat in libsre cellSpursEventFlagWait -> receive on queue 5 "_spuEvF" from 593 s
# on (q5 pushes stop at 11363, [evqstat]), holding lwmutex 0x95000039 that tids 15/16 wait for; the
# dump shows whether the flag has the event set with a waiter registered (a lost wakeup) or no event
# at all (the SPU task never set it). For "_spuEvF" waits it also dumps the fios job table the caller
# keeps beside the flag (func_0048B818: flag = obj+0x2980, slot mask obj+0x2C00, slots obj+0x2C04).
# Only queues named PS3_EVQ_STALL_NAME (default "_spuEvF") are reported; only guest memory that is
# surely committed is read (main, sys_memory below the bump, the stack page the register is in).
# Off (no env) = the plain wait.
edit("runtime/syscalls/sys_event.c",
     '''    if (timeout_us == 0) {
        while (q->count == 0 && q->active && !q->cancelled) {
            pthread_cond_wait(&q->not_empty, &q->lock);
        }
    } else {
        struct timespec ts;''',
     '''    if (timeout_us == 0) {
        /* evq stall dump (tools/patch_evq_stall_dump.py) */
        static int s_stall = -1;
        if (s_stall < 0) { const char* e = getenv("PS3_EVQ_STALL"); s_stall = e ? atoi(e) : 0; }
        int reported = 0;
        while (q->count == 0 && q->active && !q->cancelled) {
            if (s_stall <= 0 || reported) { pthread_cond_wait(&q->not_empty, &q->lock); continue; }
            struct timespec ts;
            clock_gettime(CLOCK_REALTIME, &ts);
            ts.tv_sec += s_stall;
            if (pthread_cond_timedwait(&q->not_empty, &q->lock, &ts) == ETIMEDOUT &&
                q->count == 0 && q->active && !q->cancelled) {
                reported = 1;
                evq_stall_report(ctx, queue_id, q->name, s_stall);
            }
        }
    } else {
        struct timespec ts;''',
     "evq stall wait")
edit("runtime/syscalls/sys_event.c",
     '''int64_t sys_event_queue_receive(ppu_context* ctx)
{''',
     '''/* evq stall dump (tools/patch_evq_stall_dump.py) */
static int evq_stall_readable(uint32_t a, uint32_t n)
{
    extern uint32_t g_sys_mem_bump_ptr;
    if (vm_is_valid_addr(a) && vm_is_valid_addr(a + n - 1)) return 1;
    return a >= 0x40000000u && g_sys_mem_bump_ptr && a + n <= g_sys_mem_bump_ptr;
}
static void evq_stall_hex(const char* tag, uint32_t a, uint32_t n)
{
    /* guest stacks are committed one by one: never read past the page */
    if (a >= VM_STACK_BASE && a < VM_STACK_BASE + VM_STACK_REGION && n > 0x1000u - (a & 0xFFFu))
        n = 0x1000u - (a & 0xFFFu);
    if (!evq_stall_readable(a, n)) return;
    const uint8_t* p = (const uint8_t*)vm_to_host(a);
    for (uint32_t o = 0; o < n; o += 32) {
        char ln[128]; int k = snprintf(ln, sizeof ln, "[evq-stall]   %s %08X:", tag, a + o);
        for (uint32_t i = o; i < o + 32 && i < n; i += 4)
            k += snprintf(ln + k, sizeof ln - k, " %02X%02X%02X%02X", p[i], p[i + 1], p[i + 2], p[i + 3]);
        fprintf(stderr, "%s\\n", ln);
    }
}
static void evq_stall_report(ppu_context* ctx, uint32_t queue_id, const char* qname, int secs)
{
    static _Atomic int s_n;
    char nm[9]; memcpy(nm, qname, 8); nm[8] = 0;
    { const char* want = getenv("PS3_EVQ_STALL_NAME");   /* default: SPURS event flag queues */
      if (strncmp(nm, want ? want : "_spuEvF", 8)) return; }
    if (s_n++ >= 16) return;
    for (int i = 0; i < 8; i++) if (nm[i] && (nm[i] < 32 || nm[i] > 126)) nm[i] = '?';
    fprintf(stderr, "[evq-stall] tid=%llu blocked %d s on queue %u \\"%s\\" (nothing pending) lr=0x%08X\\n",
            (unsigned long long)ctx->thread_id, secs, queue_id, nm, (uint32_t)ctx->lr);
    for (int r = 0; r < 32; r += 8)
        fprintf(stderr, "[evq-stall]   r%-2d %08X %08X %08X %08X %08X %08X %08X %08X\\n", r,
                (uint32_t)ctx->gpr[r], (uint32_t)ctx->gpr[r + 1], (uint32_t)ctx->gpr[r + 2], (uint32_t)ctx->gpr[r + 3],
                (uint32_t)ctx->gpr[r + 4], (uint32_t)ctx->gpr[r + 5], (uint32_t)ctx->gpr[r + 6], (uint32_t)ctx->gpr[r + 7]);
    uint32_t done[32]; int nd = 0;
    for (int r = 3; r < 32; r++) {
        const uint32_t a = (uint32_t)ctx->gpr[r];
        if (a & 127u) continue;
        int seen = 0;
        for (int i = 0; i < nd; i++) if (done[i] == a) seen = 1;
        if (seen || !evq_stall_readable(a, 128)) continue;
        done[nd++] = a;
        char tag[8]; snprintf(tag, sizeof tag, "r%d", r);
        evq_stall_hex(tag, a, 128);
        if (!strcmp(nm, "_spuEvF") && a >= 0x2980u) evq_stall_hex("job", a - 0x2980u + 0x2C00u, 0x2C4u);
    }
    /* the guest stack: libsre's saved registers and its caller's frame */
    evq_stall_hex("sp", (uint32_t)ctx->gpr[1], 0x200);
}

int64_t sys_event_queue_receive(ppu_context* ctx)
{''',
     "evq stall report")
