
# audio raw8 (diagnostic): AUDIO_RAW8=<file> appends every mixed block of port 0 as the title wrote
# it, before the downmix: f32le, nChannel interleaved (8 for inFAMOUS 1), 48 kHz. For checking which
# channel holds what (the console's stereo image leans right; our BC-250 mix has L/R correlation 0.04
# where the real PS3's is 0.7-0.8). Off by default.
edit("libs/audio/cellAudio.c",
     '''        for (u32 s = 0; s < CELL_AUDIO_BLOCK_SAMPLES; s++) {
            float left, right;''',
     '''        if (p == 0) {   /* audio raw8 */
            static FILE* rf = (FILE*)-1;
            if (rf == (FILE*)-1) { const char* e = getenv("AUDIO_RAW8"); rf = e ? fopen(e, "wb") : NULL; }
            if (rf) { float tmp[CELL_AUDIO_BLOCK_SAMPLES * 8];
                      const u32 nn = CELL_AUDIO_BLOCK_SAMPLES * (nch < 8 ? nch : 8);
                      for (u32 k = 0; k < nn; k++) tmp[k] = ld_be_f32(&src[k]);
                      fwrite(tmp, sizeof(float), nn, rf); }
        }
        for (u32 s = 0; s < CELL_AUDIO_BLOCK_SAMPLES; s++) {
            float left, right;''',
     "audio raw8")
