# spu putllc diff: a committing PUTLLC writes back only the 8-byte words the SPU changed against its
# GETLLAR snapshot, not the whole 128-byte line.
# A plain PPU store (inline vm_write*_inl and VM_WRITE_COH alike) takes the lock-line lock only when
# it sees an SPU reservation on the line; a store whose check came before the SPU's GETLLAR, but whose
# write lands after PUTLLC's compare (the PPU thread preempted between the two), was overwritten by
# the full-line copy -- a lost update hardware cannot produce. inFAMOUS 1's load-screen stall
# (BC-250, ~1 boot in 4, 2026-11-02): the game's zlib manager waits on an event flag for a job the
# WWS job manager on spu 2005 never sees; that SPU polls the job-list header at 0x9EAF00 ~3,700 times
# a second and finds it empty, i.e. the PPU's write to the list was lost.
# Writing only changed words keeps every other word's concurrent store: the result is the PPU store
# ordered after the PUTLLC, which hardware allows. A store to a word the SPU itself changed is still
# overwritten; that is counted ("[putllc] word conflicts").
# Alone it did not stop the stall (1 of 3 boots); together with tools/resv_note_first.py (reserve
# before load) 24 of 24 boots had no stall (that fix alone: 1 in 10). DEFAULT ON; PS3_SPU_PUTLLC_DIFF=0 = old copy.
CHN = "runtime/spu/spu_channels.c"
edit(CHN,
     '''            gm_copy_to(mem, ls, MFC_ATOMIC_LINE);      /* commit local store */
            /* A committing PUTLLC is a line write like any other, so every''',
     '''            {   /* spu putllc diff (tools/patch_spu_putllc_diff.py): only the words this SPU changed */
                static int s_full = -1;
                if (s_full < 0) { const char* e = getenv("PS3_SPU_PUTLLC_DIFF"); s_full = e && *e == '0'; }   /* default on since 2026-11-02 (24/24 boots without the stall) */
                if (s_full || ((uintptr_t)mem & 7u)) gm_copy_to(mem, ls, MFC_ATOMIC_LINE);
                else {
                    static unsigned long s_conf;
                    for (unsigned w = 0; w < MFC_ATOMIC_LINE; w += 8) {
                        uint64_t nv, ov;
                        memcpy(&nv, (const uint8_t*)ls + w, 8);
                        memcpy(&ov, (const uint8_t*)ctx->resv_line + w, 8);
                        if (nv == ov) continue;
                        uint64_t* p = (uint64_t*)((uint8_t*)mem + w);
                        uint64_t exp = ov;
                        if (!__atomic_compare_exchange_n(p, &exp, nv, 0, __ATOMIC_SEQ_CST, __ATOMIC_RELAXED)) {
                            __atomic_store_n(p, nv, __ATOMIC_SEQ_CST);   /* same word written by both: ours */
                            const unsigned long c = __atomic_add_fetch(&s_conf, 1, __ATOMIC_RELAXED);
                            if ((c & (c - 1)) == 0)
                                fprintf(stderr, "[putllc] word conflicts: %lu (ea 0x%08X +%u)\\n", c, ea, w);
                        }
                    }
                }
            }
            /* A committing PUTLLC is a line write like any other, so every''',
     "spu putllc diff")
