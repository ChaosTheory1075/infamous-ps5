# spu evt fail log: an SPU user event (sys_spu_thread_send_event, port < 64) that could not be
# delivered -- empty outbound mailbox (EINVAL), no queue bound to the port (ENOTCONN), queue full
# (EBUSY) -- is logged (first 32, then every 1024th). Two of those paths were silent: the SPU gets
# the error in its inbound mailbox and libsre's event-flag set ignores it, so the PPU waiter sleeps
# forever. FoB's load-screen stall (2026-11-02): the flag's ppuWaitMask was cleared by the SPU set,
# yet the waiting thread never got its event and the queue held nothing.
LV2 = "runtime/syscalls/lv2_register.c"
edit(LV2,
     '''    if (code < 64) spu_channel_write(&spu->ch_in_mbox, result);
    return 1;
}''',
     '''    if (code < 64 && result != CELL_OK) {   /* spu evt fail log (tools/patch_spu_evt_fail_log.py) */
        static unsigned long n_fail;
        const unsigned long k = __atomic_add_fetch(&n_fail, 1, __ATOMIC_RELAXED);
        if (k <= 32 || (k & 1023) == 0)
            fprintf(stderr, "[spu-evt] FAILED #%lu: spu %X grp 0x%X img %d port %u value 0x%08X -> 0x%08X (out_mbox %u)\\n",
                    k, spu->spu_id, spu->spu_group_id, spu->image_id, code & 63, value, result,
                    (unsigned)spu_channel_count(&spu->ch_out_mbox));
    }
    if (code < 64) spu_channel_write(&spu->ch_in_mbox, result);
    return 1;
}''',
     "spu evt fail log")
