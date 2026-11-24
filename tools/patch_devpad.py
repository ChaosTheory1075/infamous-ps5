# devpad: controller input for development tools, in memory (no file polling), port 0 only.
#  - inject: ps3_devpad_press(mask, polls, lx, ly, rx, ry): hold buttons (PAD_SCRIPT mask encoding,
#    DIGITAL2 << 8 | DIGITAL1) and the sticks (0..255, 128 centred; -1 leaves a stick alone) for
#    `polls` reads of the pad. The PS5 debugger's `pad` command drives it.
#  - record: ps3_devpad_record(path) writes every change of the final pad state (the player's and
#    anything injected) as "t_ms d1 d2 lx ly rx ry"; ps3_devpad_record(NULL) stops.
#  - replay: ps3_devpad_replay(path) plays such a file back from now (time-based), on top of the
#    player's input; it ends by itself at the file's end.
# A recorded play session can then be replayed on the console or the BC-250 to reproduce what the
# player saw (FoB's fall through an unloaded building, 2026-11-01).
PAD = "libs/input/cellPad.c"
edit(PAD,
     '''s32 cellPadGetData(u32 port_no, CellPadData* data_guest)''',
     '''/* devpad (tools/patch_devpad.py) */
static volatile unsigned s_dp_mask; static volatile int s_dp_polls, s_dp_l[2] = { -1, -1 }, s_dp_r[2] = { -1, -1 };
void ps3_devpad_press(unsigned mask, int polls, int lx, int ly, int rx, int ry)
{
    s_dp_l[0] = lx; s_dp_l[1] = ly; s_dp_r[0] = rx; s_dp_r[1] = ry;
    s_dp_mask = mask;
    __atomic_store_n(&s_dp_polls, polls > 0 ? polls : 6, __ATOMIC_RELEASE);
}
static FILE* s_dp_rec; static unsigned long long s_dp_rec_t0; static unsigned s_dp_last[6] = { ~0u };
static FILE* s_dp_play; static unsigned long long s_dp_play_t0; static int s_dp_next_ok;
static unsigned s_dp_next_t, s_dp_next[6], s_dp_cur[6] = { 0, 0, 128, 128, 128, 128 };
static void* s_dp_lock_dummy;
int ps3_devpad_record(const char* path)
{
    if (s_dp_rec) { fclose(s_dp_rec); s_dp_rec = NULL; }
    if (!path || !*path) return 0;
    s_dp_rec = fopen(path, "w");
    s_dp_rec_t0 = GetTickCount64();
    s_dp_last[0] = ~0u;
    return s_dp_rec ? 0 : -1;
}
static int dp_read_next(void)
{
    char line[128];   /* fgets + sscanf: fscanf would be a new import on the PS5 */
    return s_dp_play && fgets(line, sizeof line, s_dp_play) &&
           sscanf(line, "%u %u %u %u %u %u %u", &s_dp_next_t, &s_dp_next[0], &s_dp_next[1],
                  &s_dp_next[2], &s_dp_next[3], &s_dp_next[4], &s_dp_next[5]) == 7;
}
int ps3_devpad_replay(const char* path)
{
    if (s_dp_play) { fclose(s_dp_play); s_dp_play = NULL; }
    if (!path || !*path) return 0;
    s_dp_play = fopen(path, "r");
    if (!s_dp_play) return -1;
    s_dp_play_t0 = GetTickCount64();
    s_dp_cur[0] = s_dp_cur[1] = 0; s_dp_cur[2] = s_dp_cur[3] = s_dp_cur[4] = s_dp_cur[5] = 128;
    s_dp_next_ok = dp_read_next();
    (void)s_dp_lock_dummy;
    return 0;
}

s32 cellPadGetData(u32 port_no, CellPadData* data_guest)''',
     "devpad: api")
edit(PAD,
     '''    data->button[CELL_PAD_BTN_OFFSET_ANALOG_RIGHT_X] = hs->analog_rx;
    data->button[CELL_PAD_BTN_OFFSET_ANALOG_RIGHT_Y] = hs->analog_ry;
    data->button[CELL_PAD_BTN_OFFSET_ANALOG_LEFT_X]  = hs->analog_lx;
    data->button[CELL_PAD_BTN_OFFSET_ANALOG_LEFT_Y]  = hs->analog_ly;''',
     '''    /* devpad: injected presses and a replay, then the recorder (port 0) */
    if (port_no == 0) {
        if (s_dp_play) {
            const unsigned long long el = GetTickCount64() - s_dp_play_t0;
            while (s_dp_next_ok && el >= s_dp_next_t) { memcpy(s_dp_cur, s_dp_next, sizeof s_dp_cur); s_dp_next_ok = dp_read_next(); }
            data->button[CELL_PAD_BTN_OFFSET_DIGITAL1] |= (u16)s_dp_cur[0];
            data->button[CELL_PAD_BTN_OFFSET_DIGITAL2] |= (u16)s_dp_cur[1];
            hs->analog_lx = (u8)s_dp_cur[2]; hs->analog_ly = (u8)s_dp_cur[3];
            hs->analog_rx = (u8)s_dp_cur[4]; hs->analog_ry = (u8)s_dp_cur[5];
            if (!s_dp_next_ok) { fclose(s_dp_play); s_dp_play = NULL; printf("[devpad] replay finished\\n"); }
        }
        if (__atomic_load_n(&s_dp_polls, __ATOMIC_ACQUIRE) > 0) {
            __atomic_sub_fetch(&s_dp_polls, 1, __ATOMIC_ACQ_REL);
            data->button[CELL_PAD_BTN_OFFSET_DIGITAL1] |= (u16)(s_dp_mask & 0xFF);
            data->button[CELL_PAD_BTN_OFFSET_DIGITAL2] |= (u16)((s_dp_mask >> 8) & 0xFF);
            if (s_dp_l[0] >= 0) { hs->analog_lx = (u8)s_dp_l[0]; hs->analog_ly = (u8)s_dp_l[1]; }
            if (s_dp_r[0] >= 0) { hs->analog_rx = (u8)s_dp_r[0]; hs->analog_ry = (u8)s_dp_r[1]; }
        }
        if (s_dp_rec) {
            const unsigned v[6] = { data->button[CELL_PAD_BTN_OFFSET_DIGITAL1] & 0xFFu,
                                    data->button[CELL_PAD_BTN_OFFSET_DIGITAL2] & 0xFFu,
                                    hs->analog_lx, hs->analog_ly, hs->analog_rx, hs->analog_ry };
            if (memcmp(v, s_dp_last, sizeof v)) {
                memcpy(s_dp_last, v, sizeof v);
                fprintf(s_dp_rec, "%llu %u %u %u %u %u %u\\n", GetTickCount64() - s_dp_rec_t0, v[0], v[1], v[2], v[3], v[4], v[5]);
            }
        }
    }
    data->button[CELL_PAD_BTN_OFFSET_ANALOG_RIGHT_X] = hs->analog_rx;
    data->button[CELL_PAD_BTN_OFFSET_ANALOG_RIGHT_Y] = hs->analog_ry;
    data->button[CELL_PAD_BTN_OFFSET_ANALOG_LEFT_X]  = hs->analog_lx;
    data->button[CELL_PAD_BTN_OFFSET_ANALOG_LEFT_Y]  = hs->analog_ly;''',
     "devpad: hook")
