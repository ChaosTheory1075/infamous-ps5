# tdump regs: PS3_TDUMP_REGS=1 -- in the guest thread dump, a thread blocked in one syscall for more
# than 5 s also shows r3..r31 and, for each of r14..r31 that points into guest memory, the first
# 32 bytes of its 128-byte line. For a lost wake-up the waited-on object (an event flag, a queue
# owner) is in a callee-saved register of the waiting thread; its line shows who forgot whom.
# inFAMOUS 1's boot stall: fios tid 15 in sys_event_queue_receive(_spuEvF) for good (2026-11-02).
SPT = "runtime/syscalls/sys_ppu_thread.c"
edit(SPT,
     '''            tdump_wait_of(o, (unsigned)(i + 1));
            fputc('\\n', o);''',
     '''            tdump_wait_of(o, (unsigned)(i + 1));
            fputc('\\n', o);
            {   /* tdump regs (tools/patch_tdump_regs.py) */
                static int regs = -1;
                if (regs < 0) { const char* e = getenv("PS3_TDUMP_REGS"); regs = e && *e == '1'; }
                const unsigned tid = (unsigned)(i + 1);
                const uint64_t t0 = tid < TDW_MAX ? g_sc_inflight_t0[tid] : 0, now = ps3_ft_now();
                if (regs && tid < TDW_MAX && g_sc_inflight[tid] && t0 && now > t0 && now - t0 > 5000000000ull) {
                    fprintf(o, "[tdump]   regs:");
                    for (int r = 3; r < 32; r++) fprintf(o, " r%d=%08X", r, (uint32_t)c->gpr[r]);
                    fputc('\\n', o);
                    for (int r = 14; r < 32; r++) {
                        const uint32_t v = (uint32_t)c->gpr[r];
                        if (v < 0x10000u || v >= 0xE0000000u) continue;
                        const uint32_t l = v & ~127u;
                        fprintf(o, "[tdump]   r%d line 0x%08X:", r, l);
                        for (int k = 0; k < 32; k += 4) fprintf(o, " %08X", td_rd32(l + (uint32_t)k));
                        fputc('\\n', o);
                    }
                }
            }''',
     "tdump regs")
