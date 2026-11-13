
# audio out ch: PS3_AUDIO_OUT_CH=2|6|8 caps the LPCM channel count the audio-output queries report
# (cellAudioOutGetSoundAvailability/2, cellAudioOutGetDeviceInfo's mode list). Unset = as before
# (2/5.1/7.1 listed, 5.1 available). The host is stereo: a title told 5.1/7.1 exists places its
# sounds for surround speakers, and our fixed 7.1 -> stereo fold (rear 0.5, side 0.3) loses most
# of the side and rear placement. inFAMOUS 1's raw port data (AUDIO_RAW8, run raw1) is a 5.1 mix
# (ch 2 dialog, ch 4/5 surround, ch 6/7 silent); the console's stereo image leans right (L-R
# balance p10 -9.2 dB vs -1.8/-4.6 on the real PS3 capture) and the user hears left sounds only
# when far left. The real PS3 capture went over HDMI to a stereo capture card: stereo LPCM.
# Also logs the configuration the title asks cellAudioOutConfigure for.
edit("libs/misc/cellAvconfExt.c",
     '''s32 cellAudioOutGetSoundAvailability(u32 audioOut, u32 type, u32 fs, u32 option)
{
    (void)audioOut;
    (void)option;
''',
     '''/* audio out ch: PS3_AUDIO_OUT_CH caps the LPCM channels reported (0 = unset, as before) */
static int audio_out_ch_cap(void)
{
    static int cap = -1;
    if (cap < 0) { const char* e = getenv("PS3_AUDIO_OUT_CH"); cap = e ? atoi(e) : 0;
                   if (cap != 2 && cap != 6 && cap != 8) cap = 0;
                   if (cap) printf("[cellAvconfExt] PS3_AUDIO_OUT_CH=%d: audio output reported as %d channels\\n", cap, cap); }
    return cap;
}

s32 cellAudioOutGetSoundAvailability(u32 audioOut, u32 type, u32 fs, u32 option)
{
    (void)audioOut;
    (void)option;
    if (audio_out_ch_cap()) {   /* audio out ch */
        printf("[cellAvconfExt] GetSoundAvailability(type=%u fs=0x%X) -> %d\\n", type, fs,
               type == CELL_AUDIO_OUT_CODING_TYPE_LPCM && (fs & CELL_AUDIO_OUT_FS_48KHZ) ? audio_out_ch_cap() : 0);
        return type == CELL_AUDIO_OUT_CODING_TYPE_LPCM && (fs & CELL_AUDIO_OUT_FS_48KHZ) ? audio_out_ch_cap() : 0;
    }
''',
     "audio out ch avail")
edit("libs/misc/cellAvconfExt.c",
     '''    if (type == CELL_AUDIO_OUT_CODING_TYPE_LPCM &&
        (fs & CELL_AUDIO_OUT_FS_48KHZ) &&
        (ch == CELL_AUDIO_OUT_CHNUM_2 || ch == CELL_AUDIO_OUT_CHNUM_6 || ch == CELL_AUDIO_OUT_CHNUM_8))
        return 1; /* available */''',
     '''    if (type == CELL_AUDIO_OUT_CODING_TYPE_LPCM &&
        (fs & CELL_AUDIO_OUT_FS_48KHZ) &&
        (ch == CELL_AUDIO_OUT_CHNUM_2 || ch == CELL_AUDIO_OUT_CHNUM_6 || ch == CELL_AUDIO_OUT_CHNUM_8) &&
        (!audio_out_ch_cap() || (int)ch <= audio_out_ch_cap()))   /* audio out ch */
        return 1; /* available */''',
     "audio out ch avail2")
edit("libs/misc/cellAvconfExt.c",
     '''    info->availableModes[2].fs      = CELL_AUDIO_OUT_FS_48KHZ;

    return CELL_OK;''',
     '''    info->availableModes[2].fs      = CELL_AUDIO_OUT_FS_48KHZ;
    if (audio_out_ch_cap())   /* audio out ch: only the modes up to the cap */
        info->availableModeCount = audio_out_ch_cap() == 2 ? 1 : audio_out_ch_cap() == 6 ? 2 : 3;

    return CELL_OK;''',
     "audio out ch devinfo")
edit("libs/misc/cellAvconfExt.c",
     '''    (void)config; (void)option; (void)waitForEvent;
    printf("[cellAvconfExt] AudioOutConfigure(audioOut=%u) -> ok\\n", audioOut);''',
     '''    (void)option; (void)waitForEvent;
    { const uint32_t ea = (uint32_t)(uintptr_t)config;   /* audio out ch: what the title asks for */
      if (ea) printf("[cellAvconfExt] AudioOutConfigure: channel %u encoder %u downMixer %u\\n",
                     vm_read8(ea), vm_read8(ea + 1), vm_read32(ea + 12)); }
    printf("[cellAvconfExt] AudioOutConfigure(audioOut=%u) -> ok\\n", audioOut);''',
     "audio out ch configure log")
