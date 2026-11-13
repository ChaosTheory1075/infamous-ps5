# tdump waits: the guest thread dump (debug server `threads`, PS3_THREAD_DUMP) names what each guest
# thread is blocked in. The dispatchers already kept the in-flight lv2 syscall number (g_sc_inflight)
# and HLE import name (g_hle_inflight) per guest thread id; now the syscall's first arguments and
# both start times are kept too, and the dump prints "in sys N(r3,r4,r5) 12.3 s" / "in <hle> 4.0 s".
# A stall at a load screen (FoB after a death, 2026-11-01) then reads off the semaphore / lwmutex /
# event queue each thread sits on, without a debugger.
LDR = "runtime/ppu/ppu_loader.cpp"
HLE = "runtime/ppu/ppu_hle.cpp"
PPT = "runtime/syscalls/sys_ppu_thread.c"
edit(LDR,
     '''extern "C" uint32_t g_sc_inflight[PS3_SC_INFLIGHT_MAX] = { 0 };''',
     '''extern "C" uint32_t g_sc_inflight[PS3_SC_INFLIGHT_MAX] = { 0 };
/* tdump waits: the in-flight syscall's r3..r5 and its start (ps3_ft_now ns). */
extern "C" uint32_t g_sc_inflight_arg[PS3_SC_INFLIGHT_MAX][3] = { { 0 } };
extern "C" uint64_t g_sc_inflight_t0[PS3_SC_INFLIGHT_MAX] = { 0 };''',
     "tdump waits: sc arrays")
edit(LDR,
     '''      if (t < PS3_SC_INFLIGHT_MAX) g_sc_inflight[t] = (uint32_t)num; }''',
     '''      if (t < PS3_SC_INFLIGHT_MAX) {
          g_sc_inflight_arg[t][0] = (uint32_t)ctx->gpr[3]; g_sc_inflight_arg[t][1] = (uint32_t)ctx->gpr[4];
          g_sc_inflight_arg[t][2] = (uint32_t)ctx->gpr[5]; g_sc_inflight_t0[t] = ps3_ft_now();
          g_sc_inflight[t] = (uint32_t)num; } }''',
     "tdump waits: sc set")
edit(HLE,
     '''extern "C" const char* g_hle_inflight[PS3_HLE_INFLIGHT_MAX] = { nullptr };''',
     '''extern "C" const char* g_hle_inflight[PS3_HLE_INFLIGHT_MAX] = { nullptr };
extern "C" uint64_t g_hle_inflight_t0[PS3_HLE_INFLIGHT_MAX] = { 0 };   /* tdump waits */
static inline uint64_t tdw_now(void)   /* the clock of ps3_ft_now (CLOCK_MONOTONIC ns) */
{
#ifdef _WIN32
    return 0;
#else
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
#endif
}''',
     "tdump waits: hle array")
edit(HLE,
     '''      if (t < PS3_HLE_INFLIGHT_MAX) g_hle_inflight[t] = e->name; }''',
     '''      if (t < PS3_HLE_INFLIGHT_MAX) { g_hle_inflight_t0[t] = tdw_now(); g_hle_inflight[t] = e->name; } }''',
     "tdump waits: hle set")
edit(PPT,
     '''void ps3_thread_dump_to(FILE* o, const char* why)
{''',
     '''#define TDW_MAX 64
extern uint32_t g_sc_inflight[TDW_MAX];
extern uint32_t g_sc_inflight_arg[TDW_MAX][3];
extern uint64_t g_sc_inflight_t0[TDW_MAX];
extern const char* g_hle_inflight[TDW_MAX];
extern uint64_t g_hle_inflight_t0[TDW_MAX];
/* tdump waits: what guest thread `tid` is inside right now (syscall / HLE import), and for how long. */
static void tdump_wait_of(FILE* o, unsigned tid)
{
    if (tid >= TDW_MAX) return;
    const uint64_t now = ps3_ft_now();
    const uint32_t sc = __atomic_load_n(&g_sc_inflight[tid], __ATOMIC_RELAXED);
    const char* h = __atomic_load_n(&g_hle_inflight[tid], __ATOMIC_RELAXED);
    if (sc) {
        const uint64_t t0 = g_sc_inflight_t0[tid];
        fprintf(o, " | in sys %u(0x%X,0x%X,0x%X) %.1fs", sc, g_sc_inflight_arg[tid][0], g_sc_inflight_arg[tid][1],
                g_sc_inflight_arg[tid][2], t0 && now > t0 ? (double)(now - t0) / 1e9 : 0.0);
    }
    if (h) {
        const uint64_t t0 = g_hle_inflight_t0[tid];
        fprintf(o, " | in %s %.1fs", h, t0 && now > t0 ? (double)(now - t0) / 1e9 : 0.0);
    }
}
void ps3_thread_dump_to(FILE* o, const char* why)
{''',
     "tdump waits: printer")
edit(PPT,
     '''                fprintf(o, " 0x%x", td_rd32(next + 20)); /* low word of saved LR at +16 */
                sp = next;
            }
            fputc('\\n', o);''',
     '''                fprintf(o, " 0x%x", td_rd32(next + 20)); /* low word of saved LR at +16 */
                sp = next;
            }
            tdump_wait_of(o, (unsigned)(i + 1));
            fputc('\\n', o);''',
     "tdump waits: per thread")
