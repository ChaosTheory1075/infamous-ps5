
# kb not connected: no keyboard until the host sends a key (inFAMOUS 2 showed PC mouse prompts)
# cellKbInit marked keyboard 0 connected unconditionally. if2 calls cellKbInit(7) and, seeing a keyboard,
# switches its button prompts to the keyboard/mouse set ("Use [mouse] to aim" instead of "Hold [L1] to
# aim"; console run 2026-11-02, work/console_if2_20261102/4_fight_mouse_prompts.jpg). The real PS3 has
# no keyboard. Now a port connects on its first cellKb_keyEvent (as cellMouse already did); nothing on
# the PS5 sends one. PS3_KB_CONNECTED=1 restores the old always-connected keyboard 0.
edit("libs/input/cellKb.c",
     '''    /* Assume keyboard 0 is always connected on the host */
    s_kb_ports[0].connected = 1;
''',
     '''    /* kb not connected: keyboard 0 connects on its first host key event (PS3_KB_CONNECTED=1: at once) */
    { const char* e = getenv("PS3_KB_CONNECTED"); s_kb_ports[0].connected = e && *e == '1'; }
''',
     "kb not connected")
edit("libs/input/cellKb.c",
     '''#include <string.h>
#include <stdint.h>
''',
     '''#include <string.h>
#include <stdint.h>
#include <stdlib.h>   /* kb not connected: getenv */
''',
     "kb not connected include")
