
# devpad replay env: PS3_DEVPAD_REPLAY=<file.pad> replays a controller recording ("t d1 d2 lx ly
# rx ry", ms) from the first pad poll + PS3_DEVPAD_REPLAY_AT seconds (default 0), so a console run's
# input (work/live/if1_live_1103_fps/pad/fps1103.pad) can be re-driven on the BC-250 without the
# debugger. Unset = no replay (old).
edit("libs/input/cellPad.c",
     '''    /* devpad: injected presses and a replay, then the recorder (port 0) */
    if (port_no == 0) {''',
     '''    /* devpad: injected presses and a replay, then the recorder (port 0) */
    if (port_no == 0) {
        { static int s_rp = -1; static unsigned long long s_rp_t0;   /* devpad replay env */
          if (s_rp < 0) { s_rp = getenv("PS3_DEVPAD_REPLAY") ? 1 : 0; s_rp_t0 = GetTickCount64(); }
          if (s_rp == 1) {
              const char* at = getenv("PS3_DEVPAD_REPLAY_AT");
              if (GetTickCount64() - s_rp_t0 >= (unsigned long long)(at ? atoi(at) : 0) * 1000ull) {
                  s_rp = 2;
                  const int rc = ps3_devpad_replay(getenv("PS3_DEVPAD_REPLAY"));
                  printf("[devpad] replay of %s started (%d)\\n", getenv("PS3_DEVPAD_REPLAY"), rc);
              } } }''',
     "devpad replay env")
