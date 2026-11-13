
# dbgsrv regs: a guest thread's registers for the PS5 debug server ("regs <tid>")
# A thread parked in a syscall keeps its arguments and callee-saved registers in its context; with
# them the object it waits on (an event flag, a queue, a lock) can be read from memory.
edit("runtime/syscalls/sys_ppu_thread.c",
     '''void ps3_thread_dump_to(FILE* o, const char* why);
void ps3_thread_dump_now(const char* why) { ps3_thread_dump_to(stderr, why); }''',
     '''void ps3_thread_dump_to(FILE* o, const char* why);
void ps3_thread_dump_now(const char* why) { ps3_thread_dump_to(stderr, why); }
/* One guest thread's registers (tid as the dump prints it). 0 = no such live thread. */
int ps3_thread_regs_to(FILE* o, int tid)
{
    if (tid < 1 || tid > PPU_THREAD_MAX) return 0;
    ppu_thread_info* t = &g_ppu_threads[tid - 1];
    if (t->state != PPU_THREAD_STATE_RUNNING && t->state != PPU_THREAD_STATE_DETACHED) return 0;
    const ppu_context* c = (tid == 1 && g_ppu_main_ctx_live) ? g_ppu_main_ctx_live : &t->ctx;
    fprintf(o, "tid=%d %s cia=0x%08X lr=0x%08X ctr=0x%08X cr=0x%08X xer=0x%llX\\n", tid, t->name,
            (uint32_t)c->cia, (uint32_t)c->lr, (uint32_t)c->ctr, (uint32_t)c->cr, (unsigned long long)c->xer);
    for (int r = 0; r < 32; r += 4)
        fprintf(o, "r%-2d %016llX  r%-2d %016llX  r%-2d %016llX  r%-2d %016llX\\n",
                r, (unsigned long long)c->gpr[r], r + 1, (unsigned long long)c->gpr[r + 1],
                r + 2, (unsigned long long)c->gpr[r + 2], r + 3, (unsigned long long)c->gpr[r + 3]);
    fflush(o);
    return 1;
}''',
     "dbgsrv regs")
edit("runtime/spu/spu_channels.c",
     '''/* That context's local store (256 KB), for the debug server's "ls". */''',
     '''/* That context's registers, for the debug server's "spuregs": pc, status and all 128 GPRs. */
int spu_ctx_regs_to(FILE* o, int i)
{
    const spu_context* c = spu_ctx_at(i);
    if (!c) return 0;
    fprintf(o, "spu ctx%d id=0x%X img=%d pc=0x%05X status=0x%X stop=0x%X evstat=0x%X evmask=0x%X\\n", i, c->spu_id,
            c->image_id, c->pc & SPU_LS_MASK, c->status, c->stop_code, c->event_status, c->event_mask);
    for (int r = 0; r < 128; r += 2)
        fprintf(o, "r%-3d %08X %08X %08X %08X   r%-3d %08X %08X %08X %08X\\n",
                r, c->gpr[r]._u32[0], c->gpr[r]._u32[1], c->gpr[r]._u32[2], c->gpr[r]._u32[3],
                r + 1, c->gpr[r + 1]._u32[0], c->gpr[r + 1]._u32[1], c->gpr[r + 1]._u32[2], c->gpr[r + 1]._u32[3]);
    fflush(o);
    return 1;
}
/* That context's local store (256 KB), for the debug server's "ls". */''',
     "dbgsrv spuregs")
