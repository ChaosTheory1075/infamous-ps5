
# icons ps5 default: on the PS5, "auto" button icons with no detected device are the PlayStation set
# The console run 2026-11-03 07:27 drew the prompt atlas in keyboard mode ("[button icons] prompt atlas
# found (mode keyboard)": mouse glyphs in "Hold [mouse] to aim"). The PS5 app sets
# PS3_BUTTON_ICONS=playstation, but with PS3_TOGGLE_FILE in env.txt the knob read back empty = auto,
# and auto with no SDL controller (the PS5 has none: cellPad reads the DualSense directly) resolved
# to KEYBOARD. On the PS5 there is no keyboard or mouse to follow: auto without a device = PlayStation.
edit("libs/video/rsx_button_icons.c",
     '''    static int headless = -1;
    if (headless < 0) { const char* hl = getenv("PS3RECOMP_METAL_HEADLESS"); headless = hl && *hl && *hl != '0'; }
    return headless ? PS3_ICONS_PLAYSTATION : PS3_ICONS_KEYBOARD;''',
     '''#if defined(__PROSPERO__)
    return PS3_ICONS_PLAYSTATION;   /* icons ps5 default: no keyboard/mouse on the console */
#endif
    static int headless = -1;
    if (headless < 0) { const char* hl = getenv("PS3RECOMP_METAL_HEADLESS"); headless = hl && *hl && *hl != '0'; }
    return headless ? PS3_ICONS_PLAYSTATION : PS3_ICONS_KEYBOARD;''',
     "icons ps5 default")
