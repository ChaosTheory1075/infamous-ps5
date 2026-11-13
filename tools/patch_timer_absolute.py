
# timer absolute: periodic lv2 timers (sys_timer_start) fire on a fixed schedule instead of drifting.
# The POSIX timer thread waited "now + period" after handling each tick, so every tick ran late by the
# wake-up latency plus the event push, and the error added up: the timer ran slower than real time by
# that latency every period. inFAMOUS 1's sound driver (brbDriver, queue 9, src 0 d1 0) is woken by such
# a timer and refills its 8-block cellAudio port from it; the cellAudio consumer runs on the device
# clock. On the PS5 (larger wake latency under load) the driver fell a whole ring behind again and
# again: the console recording (work/live/if1_live_1103_audio) has ~1250 exact-silence gaps in 10 min,
# 743 of them exactly 8 blocks (42.7 ms) long = the user's "distorted audio". Now deadline += period,
# resynced only when more than 100 ms behind (a debugger stop). One "[timer] start" line per start.
# PS3_TIMER_ABS=0 = the old relative wait.
edit("runtime/syscalls/sys_timer.c",
     '''    pthread_mutex_lock(&t->mtx);
    while (!t->stop_flag) {
        struct timespec ts;
        clock_gettime(CLOCK_REALTIME, &ts);
        ts.tv_sec  += (time_t)(t->period_usec / 1000000);
        ts.tv_nsec += (long)((t->period_usec % 1000000) * 1000);
        if (ts.tv_nsec >= 1000000000L) {
            ts.tv_sec++;
            ts.tv_nsec -= 1000000000L;
        }
''',
     '''    pthread_mutex_lock(&t->mtx);
    /* timer absolute: a fixed schedule (deadline += period), not "now + period" after each tick */
    static int s_abs = -1;
    if (s_abs < 0) { const char* e = getenv("PS3_TIMER_ABS"); s_abs = (e && *e == '0') ? 0 : 1; }
    struct timespec next;
    clock_gettime(CLOCK_REALTIME, &next);
    while (!t->stop_flag) {
        struct timespec ts;
        if (s_abs) {
            next.tv_sec  += (time_t)(t->period_usec / 1000000);
            next.tv_nsec += (long)((t->period_usec % 1000000) * 1000);
            if (next.tv_nsec >= 1000000000L) { next.tv_sec++; next.tv_nsec -= 1000000000L; }
            struct timespec now;
            clock_gettime(CLOCK_REALTIME, &now);
            const long long late_us = (long long)(now.tv_sec - next.tv_sec) * 1000000LL
                                    + (now.tv_nsec - next.tv_nsec) / 1000;
            if (late_us > 100000) next = now;   /* far behind (a debugger stop): start over from now */
            ts = next;
        } else {
        clock_gettime(CLOCK_REALTIME, &ts);
        ts.tv_sec  += (time_t)(t->period_usec / 1000000);
        ts.tv_nsec += (long)((t->period_usec % 1000000) * 1000);
        if (ts.tv_nsec >= 1000000000L) {
            ts.tv_sec++;
            ts.tv_nsec -= 1000000000L;
        }
        }
''',
     "timer absolute")
edit("runtime/syscalls/sys_timer.c",
     '''    t->period_usec = period;
    t->running     = 1;
''',
     '''    t->period_usec = period;
    t->running     = 1;
    printf("[timer] start id=%u period=%llu us queue=%d\\n", timer_id,   /* timer absolute */
           (unsigned long long)period, (int)t->event_queue_id);
''',
     "timer absolute log")
