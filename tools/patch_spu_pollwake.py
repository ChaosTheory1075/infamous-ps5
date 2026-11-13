
# spu pollwake probe: count SPU event waits that ended only because the 1 ms re-poll saw the
# reserved line change (its writer raised no SPU_EVENT_LR), and name the first lines it happened on.
edit("runtime/spu/spu_channels.c",
     '''    if (changed && spu_resv_break(ctx, rea & ~127u))
        spu_ev_raise(ctx, 0x400u);
}''',
     '''    if (changed && spu_resv_break(ctx, rea & ~127u)) {
        spu_ev_raise(ctx, 0x400u);
        /* No writer told us: report the line (each distinct one once, up to 32) and a running
         * count, so the store path that skips spu_coh_notify_write can be found. */
        static _Atomic unsigned long s_pw; static uint32_t s_pw_ea[32]; static _Atomic int s_pw_n;
        const unsigned long n = __atomic_add_fetch(&s_pw, 1, __ATOMIC_RELAXED);
        int known = 0; const int nn = s_pw_n;
        for (int i = 0; i < nn && i < 32; i++) if (s_pw_ea[i] == (rea & ~127u)) { known = 1; break; }
        if (!known && nn < 32) { s_pw_ea[nn] = rea & ~127u; s_pw_n = nn + 1;
            fprintf(stderr, "[spu pollwake] spu=%X line 0x%08X changed with no LR raised (pc 0x%05X, img %d)\\n",
                    ctx->spu_id, rea & ~127u, ctx->pc & SPU_LS_MASK, ctx->image_id); }
        if ((n & 4095) == 0)
            fprintf(stderr, "[spu pollwake] %lu wakes found by the poll; LR raised by writers %lu\\n",
                    n, g_spu_lr_raise);
    }
}''',
     "spu pollwake probe")
# ...and how each blocked event wait ended: woken by a producer, or by the timed re-poll.
edit("runtime/spu/spu_channels.c",
     '''            AcquireSRWLockExclusive((SRWLOCK*)&ctx->ch_wait_lock);
            if (!spu_ch_ready(ctx, channel))
                SleepConditionVariableSRW((CONDITION_VARIABLE*)&ctx->ch_wait_cv,
                                          (SRWLOCK*)&ctx->ch_wait_lock, spu_chwait_ms(), 0);
            ReleaseSRWLockExclusive((SRWLOCK*)&ctx->ch_wait_lock);''',
     '''            AcquireSRWLockExclusive((SRWLOCK*)&ctx->ch_wait_lock);
            if (!spu_ch_ready(ctx, channel))
                last_to = !SleepConditionVariableSRW((CONDITION_VARIABLE*)&ctx->ch_wait_cv,
                                          (SRWLOCK*)&ctx->ch_wait_lock, spu_chwait_ms(), 0);
            ReleaseSRWLockExclusive((SRWLOCK*)&ctx->ch_wait_lock);
            sleeps++;''',
     "spu pollwake wait end")
edit("runtime/spu/spu_channels.c",
     '''        unsigned long long start = GetTickCount64(), next_hb = 2000;
        while (!spu_ch_ready(ctx, channel)) {''',
     '''        unsigned long long start = GetTickCount64(), next_hb = 2000;
        int last_to = 0, sleeps = 0;
        while (!spu_ch_ready(ctx, channel)) {''',
     "spu pollwake wait vars")
edit("runtime/spu/spu_channels.c",
     '''                next_hb = ((waited / 2000) + 1) * 2000;
            }
        }
    }
    yz_lockstep_block_end(ctx);            /* rejoin the rotation, reacquire the token */''',
     '''                next_hb = ((waited / 2000) + 1) * 2000;
            }
        }
        /* Event waits: woken by a producer, or found ready by the timed re-poll. */
        if (channel == SPU_RdEventStat && sleeps) {
            static _Atomic unsigned long s_sig, s_to, s_tot;
            if (last_to) __atomic_add_fetch(&s_to, 1, __ATOMIC_RELAXED);
            else         __atomic_add_fetch(&s_sig, 1, __ATOMIC_RELAXED);
            if ((__atomic_add_fetch(&s_tot, 1, __ATOMIC_RELAXED) & 16383) == 0)
                fprintf(stderr, "[spu pollwake] event waits: %lu woken by a producer, %lu by the %u ms re-poll\\n",
                        s_sig, s_to, spu_chwait_ms());
        }
    }
    yz_lockstep_block_end(ctx);            /* rejoin the rotation, reacquire the token */''',
     "spu pollwake wait report")
