# audio ps5 prio: on the PS5 every thread runs SCHED_FIFO at priority 700, so under heavy load (explosions:
# particles, physics, the SPU audio job all at once) our mixer thread and the sceAudioOut feeder wait their
# turn behind busy game threads -- and the feeder fills whatever the ring lacks with silence mid-frame,
# uncounted. Both threads mostly sleep (sceAudioOutOutput blocks; the mixer sleeps 0.5-1 ms between blocks),
# so they get priority 640 (lower = higher on Orbis): they run when due without taking cores from anyone.
# Also counted now, with the hold line every 30 s: frames the feeder padded with silence, and samples padded.
# The user hears distortion on explosions only (2026-11-05); our own mix never clips on the route
# ([audio-clip], peak 0.82). PS3_AUDIO_PRIO=<n> (256..767) picks the priority, 0 leaves 700.
import sys
C = __import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/libs/audio/cellAudio.c"
c = open(C).read()
if "audio ps5 prio" in c: print("already"); sys.exit(0)
def edit(s, old, new):
    if s.count(old) != 1: print("NOT FOUND/UNIQUE:", old[:80]); sys.exit(1)
    return s.replace(old, new)
c = edit(c, '''static void* ps5a_main(void* arg)
{
    (void)arg;
    int16_t pcm[PS5A_FRAME * 2];
    while (s_ps5a_run) {
        u32 rd = __atomic_load_n(&s_ps5a_rd, __ATOMIC_ACQUIRE);
        const u32 wr = __atomic_load_n(&s_ps5a_wr, __ATOMIC_ACQUIRE);
        for (u32 i = 0; i < PS5A_FRAME; i++) {
            float l = 0.0f, r = 0.0f;
            if (rd != wr) { const u32 k = (rd % PS5A_RING) * 2u; l = s_ps5a_ring[k]; r = s_ps5a_ring[k + 1]; rd++; }''',
'''/* audio ps5 prio: the audio threads above the game's FIFO 700 */
static unsigned long long s_ps5a_pad_frames, s_ps5a_pad_samples;   /* frames the feeder padded with silence */
static void ps5a_raise_prio(const char* who)
{
    static int prio = -1;
    if (prio < 0) { const char* e = getenv("PS3_AUDIO_PRIO"); prio = e && *e ? atoi(e) : 640; }
    if (prio < 256 || prio > 767) return;
    int policy = 0; struct sched_param sp = { 0 };
    pthread_getschedparam(pthread_self(), &policy, &sp);
    const int was = sp.sched_priority;
    sp.sched_priority = prio;
    const int rc = pthread_setschedparam(pthread_self(), policy, &sp);
    printf("[cellAudio] %s thread priority %d -> %d (rc %d)\\n", who, was, prio, rc);
}
static void* ps5a_main(void* arg)
{
    (void)arg;
    int16_t pcm[PS5A_FRAME * 2];
    ps5a_raise_prio("output");
    while (s_ps5a_run) {
        u32 rd = __atomic_load_n(&s_ps5a_rd, __ATOMIC_ACQUIRE);
        const u32 wr = __atomic_load_n(&s_ps5a_wr, __ATOMIC_ACQUIRE);
        if (wr - rd < PS5A_FRAME) { s_ps5a_pad_frames++; s_ps5a_pad_samples += PS5A_FRAME - (wr - rd); }   /* the mixer always submits, so short = late */
        for (u32 i = 0; i < PS5A_FRAME; i++) {
            float l = 0.0f, r = 0.0f;
            if (rd != wr) { const u32 k = (rd % PS5A_RING) * 2u; l = s_ps5a_ring[k]; r = s_ps5a_ring[k + 1]; rd++; }''')
c = edit(c, '''    printf("[cellAudio] host queue %u blocks, hold %s (min %u)\\n", qblocks, hold_on ? "on" : "off", hold_min);''',
'''    printf("[cellAudio] host queue %u blocks, hold %s (min %u)\\n", qblocks, hold_on ? "on" : "off", hold_min);
#if defined(__PROSPERO__)
    ps5a_raise_prio("mixer");   /* audio ps5 prio */
#endif''')
c = edit(c, '''            printf("[cellAudio] hold: %llu late blocks waited for, %llu arrived in time, %llu played as silence\\n",
                   n_hold, n_hold_ok, n_hold_gaveup);''', '''            printf("[cellAudio] hold: %llu late blocks waited for, %llu arrived in time, %llu played as silence\\n",
                   n_hold, n_hold_ok, n_hold_gaveup);
#if defined(__PROSPERO__)
            printf("[cellAudio] output: %llu frames padded with silence (%llu samples) since boot\\n",
                   s_ps5a_pad_frames, s_ps5a_pad_samples);   /* audio ps5 prio */
#endif''')
open(C, "w").write(c); print("patched")
