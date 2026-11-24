/*
 * pad_triggers.inc -- the DualSense's adaptive triggers on the PS5 build, 2026-11-14.
 * Included by cellPad.c inside its __PROSPERO__ block, and by tests/pad_triggers_test.c on the test box (the plan
 * below is plain C: what the triggers are told for a given controller + game state).
 *
 * What the player feels (all three games; inFAMOUS drains with L2, inFAMOUS 2 / Festival of Blood lift with R2):
 *   L2  an even push from a little way down (the console's "feedback" mode);
 *   R2  a two-stage pull that gives way partway (the console's "weapon" mode);
 *   and while a trigger is held and the game runs its own rumble (draining, lifting, hits, blasts), that trigger
 *   buzzes with it (the console's "vibration" mode), stronger with a stronger rumble.
 * So the effects follow the game through its own motor requests: no game address is read, nothing per game to go
 * stale. Off with the DualSense extras (quick menu CONTROLLER row / launcher.ini dualsense = 0) or PS3_TRIGGERS=0.
 *
 * The console's layout and modes as the other PS5 ports use them:
 *   mode 0 off; 1 feedback (data: position 0-9, strength 1-8); 2 weapon (start 2-7, end start+1..8, strength 0-8);
 *   3 vibration (position 0-9, amplitude 0-8, frequency in Hz).
 */
typedef struct { int32_t mode, reserved; uint8_t data[48]; } ps5_trig_cmd;
typedef struct { uint8_t mask; uint8_t reserved[7]; ps5_trig_cmd l2, r2; } ps5_trig_param;
typedef char ps5_trig_cmd_size[sizeof(ps5_trig_cmd) == 56 ? 1 : -1];
typedef char ps5_trig_param_size[sizeof(ps5_trig_param) == 120 ? 1 : -1];

#define PAD_TRIG_HELD      40     /* a trigger counts as held from here (0-255) */
#define PAD_TRIG_MIN_MS    60     /* at least this long between two changes of the effects */
#define PAD_TRIG_BUZZ_MS  140     /* a buzz lasts at least this long (a one-frame rumble is still felt) */

/* The game's rumble (the host motors' 16-bit requests) as a buzz level 0-4. The PS3's small motor is on/off. */
static int pad_trig_level(unsigned lo, unsigned hi)
{
    const unsigned big = (lo >> 8) & 0xFF;
    int lv = big == 0 ? 0 : big < 64 ? 1 : big < 128 ? 2 : big < 192 ? 3 : 4;
    if (hi && lv < 2) lv = 2;
    return lv;
}

/* What the triggers should be doing now. on: the DualSense extras are on. level: pad_trig_level(). */
static void pad_trig_plan(int on, unsigned l2, unsigned r2, int level, ps5_trig_param* p)
{
    memset(p, 0, sizeof *p);
    p->mask = 1 | 2;
    if (!on) return;                                   /* both mode 0: the triggers as the system has them */
    if (level > 0 && l2 > PAD_TRIG_HELD) {
        p->l2.mode = 3; p->l2.data[0] = 1; p->l2.data[1] = (uint8_t)(2 * level); p->l2.data[2] = 40;
    } else {
        p->l2.mode = 1; p->l2.data[0] = 2; p->l2.data[1] = 3;
    }
    if (level > 0 && r2 > PAD_TRIG_HELD) {
        p->r2.mode = 3; p->r2.data[0] = 1; p->r2.data[1] = (uint8_t)(2 * level); p->r2.data[2] = 25;
    } else {
        p->r2.mode = 2; p->r2.data[0] = 3; p->r2.data[1] = 5; p->r2.data[2] = 5;
    }
}

/* The same over time: no flicker (PAD_TRIG_MIN_MS between changes), a buzz held PAD_TRIG_BUZZ_MS.
 * 1: *out differs from what was last sent and may be sent now. */
typedef struct {
    ps5_trig_param sent;          /* what the controller was last told */
    int have_sent;
    unsigned long long sent_ms;
    int buzz_level;               /* the level being held */
    unsigned long long buzz_ms;   /* when it was last asked for */
} pad_trig_state;

static int pad_trig_step(pad_trig_state* s, int on, unsigned l2, unsigned r2, unsigned lo, unsigned hi,
                         unsigned long long now, ps5_trig_param* out)
{
    int level = pad_trig_level(lo, hi);
    if (level >= s->buzz_level) { if (level) { s->buzz_level = level; s->buzz_ms = now; } }
    if (level < s->buzz_level) {
        if (now - s->buzz_ms < PAD_TRIG_BUZZ_MS) level = s->buzz_level;
        else { s->buzz_level = level; s->buzz_ms = now; }
    }
    pad_trig_plan(on, l2, r2, level, out);
    if (!s->have_sent) {
        if (!on) return 0;                             /* never switched on: nothing to switch off */
    } else {
        if (!memcmp(out, &s->sent, sizeof *out)) return 0;
        if (on && now - s->sent_ms < PAD_TRIG_MIN_MS) return 0;
    }
    return 1;
}
static void pad_trig_sent(pad_trig_state* s, const ps5_trig_param* p, unsigned long long now)
{
    s->sent = *p; s->have_sent = 1; s->sent_ms = now;
}
