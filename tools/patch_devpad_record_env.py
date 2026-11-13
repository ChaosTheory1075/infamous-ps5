
# devpad record env: PS3_DEVPAD_RECORD=<file.pad> records port 0 from the first pad poll (the time base
# PS3_DEVPAD_REPLAY uses with PS3_DEVPAD_REPLAY_AT=0), flushed per line so a killed run keeps it. For the
# user's BC-250 benchmark route. Unset = no recording (old).
edit("libs/input/cellPad.c",
     '''        { static int s_rp = -1; static unsigned long long s_rp_t0;   /* devpad replay env */''',
     '''        { static int s_rc = -1;                                        /* devpad record env */
          if (s_rc < 0) { const char* r = getenv("PS3_DEVPAD_RECORD"); s_rc = 0;
              if (r && *r) { const int rc = ps3_devpad_record(r); printf("[devpad] recording to %s (%d)\\n", r, rc); } } }
        { static int s_rp = -1; static unsigned long long s_rp_t0;   /* devpad replay env */''',
     "devpad record env: start")
edit("libs/input/cellPad.c",
     '''                fprintf(s_dp_rec, "%llu %u %u %u %u %u %u\\n", GetTickCount64() - s_dp_rec_t0, v[0], v[1], v[2], v[3], v[4], v[5]);''',
     '''                fprintf(s_dp_rec, "%llu %u %u %u %u %u %u\\n", GetTickCount64() - s_dp_rec_t0, v[0], v[1], v[2], v[3], v[4], v[5]);
                fflush(s_dp_rec);   /* devpad record env: a killed run keeps its recording */''',
     "devpad record env: flush")
