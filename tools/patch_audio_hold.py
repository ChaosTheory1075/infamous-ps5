
# audio hold: wait for a late guest block instead of playing it as silence (POSIX mixer loop).
# The mixer consumed one block per 5.33 ms of device time whether or not the title had written it,
# and zeroed it after. When the title's sound driver ran late (inFAMOUS 1's brbDriver, woken by a
# 5.33 ms lv2 timer), every block it had not written yet became silence: the console recording
# (work/live/if1_live_1103_audio) has ~1250 exact-silence gaps in 10 min, 743 of them a whole
# 8-block ring. Now, when every running port's next block is still all zero right after a block that
# had sound, the mixer holds the read index while the host queue still has more than
# PS3_AUDIO_HOLD_MIN blocks (default 2) to play; the reserve covers the wait. One hold per silent run
# (real silence costs one reserve's worth of delay, once). The host queue target is
# PS3_AUDIO_QUEUE blocks (default 8 on the PS5 = 43 ms, 4 elsewhere as before).
# PS3_AUDIO_HOLD=0 = off (default on on the PS5, off elsewhere; PS3_AUDIO_HOLD=1 turns it on).
edit("libs/audio/cellAudio.c",
     '''static void audio_mix_one_block(void)
{''',
     '''/* audio hold: is the next block of every running port still all zero (not written yet)?
 * 0 when no port is running. */
static int s_audio_last_had_data;
static int audio_next_blocks_empty(void)
{
    int running = 0;
    mutex_lock(&s_audio_mutex);
    for (int p = 0; p < CELL_AUDIO_PORT_MAX; p++) {
        AudioPortSlot* port = &s_ports[p];
        if (!port->in_use || !port->running || !port->buffer) continue;
        const u32 nch = (u32)port->param.nChannel, nblock = (u32)port->param.nBlock;
        if (!nblock) continue;
        running = 1;
        const u32* w = (const u32*)(port->buffer + (u32)(port->read_index % nblock) * CELL_AUDIO_BLOCK_SAMPLES * nch);
        for (u32 i = 0; i < CELL_AUDIO_BLOCK_SAMPLES * nch; i++)
            if (w[i]) { mutex_unlock(&s_audio_mutex); return 0; }
    }
    mutex_unlock(&s_audio_mutex);
    return running;
}

static void audio_mix_one_block(void)
{''',
     "audio hold helper")
edit("libs/audio/cellAudio.c",
     '''    /* Clip to [-1.0, 1.0] */
    for (u32 i = 0; i < CELL_AUDIO_BLOCK_SAMPLES * 2; i++) {
        if (s_mix_buffer[i] > 1.0f) s_mix_buffer[i] = 1.0f;
        if (s_mix_buffer[i] < -1.0f) s_mix_buffer[i] = -1.0f;
    }
}''',
     '''    /* Clip to [-1.0, 1.0] */
    int had = 0;   /* audio hold */
    for (u32 i = 0; i < CELL_AUDIO_BLOCK_SAMPLES * 2; i++) {
        if (s_mix_buffer[i] > 1.0f) s_mix_buffer[i] = 1.0f;
        if (s_mix_buffer[i] < -1.0f) s_mix_buffer[i] = -1.0f;
        if (s_mix_buffer[i] != 0.0f) had = 1;
    }
    s_audio_last_had_data = had;
}''',
     "audio hold track")
edit("libs/audio/cellAudio.c",
     '''    struct timespec t0; clock_gettime(CLOCK_MONOTONIC, &t0);
    unsigned long long mixed = 0;
    while (s_mix_thread_running) {
        struct timespec now; clock_gettime(CLOCK_MONOTONIC, &now);
        unsigned long long el_us = (unsigned long long)(now.tv_sec - t0.tv_sec) * 1000000ull
                                 + (unsigned long long)((now.tv_nsec - t0.tv_nsec) / 1000);
        unsigned long long ahead_us = mixed * CELL_AUDIO_BLOCK_SAMPLES * 1000000ull / 48000ull;
        if (audio_backend_queued_samples() >= CELL_AUDIO_BLOCK_SAMPLES * 4 ||
            ahead_us > el_us + 4ull * CELL_AUDIO_BLOCK_SAMPLES * 1000000ull / 48000ull) {
            usleep(1000);
            continue;
        }
        mixed++;''',
     '''    struct timespec t0; clock_gettime(CLOCK_MONOTONIC, &t0);
    unsigned long long mixed = 0;
    /* audio hold: queue target and hold settings (see tools/patch_audio_hold.py) */
#if defined(__PROSPERO__)
    int hold_on = 1; unsigned qblocks = 8;
#else
    int hold_on = 0; unsigned qblocks = 4;
#endif
    { const char* e = getenv("PS3_AUDIO_HOLD"); if (e && *e) hold_on = *e != '0';
      e = getenv("PS3_AUDIO_QUEUE"); if (e && atoi(e) >= 2 && atoi(e) <= 24) qblocks = (unsigned)atoi(e); }
    unsigned hold_min = 2;
    { const char* e = getenv("PS3_AUDIO_HOLD_MIN"); if (e && atoi(e) >= 0 && (unsigned)atoi(e) < qblocks) hold_min = (unsigned)atoi(e); }
    printf("[cellAudio] host queue %u blocks, hold %s (min %u)\\n", qblocks, hold_on ? "on" : "off", hold_min);
    int held = 0;                          /* this silent run was already waited for */
    unsigned long long n_hold = 0, n_hold_ok = 0, n_hold_gaveup = 0;
    struct timespec tr; clock_gettime(CLOCK_MONOTONIC, &tr);
    while (s_mix_thread_running) {
        struct timespec now; clock_gettime(CLOCK_MONOTONIC, &now);
        unsigned long long el_us = (unsigned long long)(now.tv_sec - t0.tv_sec) * 1000000ull
                                 + (unsigned long long)((now.tv_nsec - t0.tv_nsec) / 1000);
        unsigned long long ahead_us = mixed * CELL_AUDIO_BLOCK_SAMPLES * 1000000ull / 48000ull;
        if (audio_backend_queued_samples() >= CELL_AUDIO_BLOCK_SAMPLES * qblocks ||
            ahead_us > el_us + (unsigned long long)qblocks * CELL_AUDIO_BLOCK_SAMPLES * 1000000ull / 48000ull) {
            usleep(1000);
            continue;
        }
        if (hold_on && s_audio_last_had_data && audio_next_blocks_empty()) {
            if (!held) { held = 1; n_hold++; }
            if (audio_backend_queued_samples() > CELL_AUDIO_BLOCK_SAMPLES * hold_min) {
                usleep(500);               /* the title is late: let the reserve play while it writes */
                continue;
            }
            n_hold_gaveup++;               /* reserve used up: play it as silence */
        } else if (held && s_audio_last_had_data) {
            n_hold_ok++;                   /* the block arrived during the wait */
        }
        if (!hold_on || !s_audio_last_had_data || !audio_next_blocks_empty()) held = 0;
        if (hold_on && now.tv_sec - tr.tv_sec >= 30) {
            tr = now;
            printf("[cellAudio] hold: %llu late blocks waited for, %llu arrived in time, %llu played as silence\\n",
                   n_hold, n_hold_ok, n_hold_gaveup);
        }
        mixed++;''',
     "audio hold loop")
