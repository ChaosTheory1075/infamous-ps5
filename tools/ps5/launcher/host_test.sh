#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Draw the launcher's pages on the PC (stub system calls) into <app>/shot_N.ppm -> PNGs in work/dbg/.
A=${IF_ROOT:-$HOME/inFamous}/ps5/PPSA95463
S=${IF_ROOT:-$HOME/inFamous}/tools/ps5/launcher
cat > /tmp/lstubs.c << 'EOF'
#include <stdint.h>
int sceUserServiceInitialize(void* p) { (void)p; return 0; }
int sceUserServiceGetInitialUser(int32_t* u) { *u = -1; return -1; }
int scePadInit(void) { return 0; }
int scePadOpen(int32_t a, int32_t b, int32_t c, const void* d) { return -1; }
int scePadGetHandle(int32_t a, int32_t b, int32_t c) { return -1; }
int scePadReadState(int32_t h, void* d) { return -1; }
int sceSystemServiceLoadExec(const char* p, char* const a[]) { return -1; }
int sceSystemServiceHideSplashScreen(void) { return 0; }
#include <stdlib.h>
int sceSystemServiceParamGetInt(int id, int* v) { const char* e = getenv("PS5_LANG"); (void)id; *v = e ? atoi(e) : 1; return 0; }
int32_t sceAudioOutInit(void) { return 0; }
int32_t sceAudioOutOpen(int32_t a, int32_t b, int32_t c, uint32_t d, uint32_t e, uint32_t f) { return -1; }
int32_t sceAudioOutOutput(int32_t h, const void* p) { return 0; }
int32_t sceAudioOutClose(int32_t h) { return 0; }
EOF
gcc -O2 -DLAUNCHER_HOST -DAPP="\"$A\"" -Wno-unused-function \
  -I$HOME/cdbuild/fw-clean/glue/rexglue-sdk-main/thirdparty/stb -I$HOME/cdbuild/fw-clean/glue/rexglue-sdk-main/gta4-recomp/src/ps5/hub \
  -I$HOME/if2/ps3recomp-fork/libs/font -I${IF_ROOT:-$HOME/inFamous}/deps/Vulkan-Headers/include \
  $S/launcher.c /tmp/lstubs.c -o /tmp/launcher_host -lm -lpthread 2>&1 | grep -E 'error|warning' | head
/tmp/launcher_host && cat $A/logs/launcher.log
python3 -c "
from PIL import Image
for k in range(8):
    Image.open('$A/shot_%d.ppm' % k).save('${IF_ROOT:-$HOME/inFamous}/work/dbg/launcher_%d.png' % k)
"
rm -f $A/shot_*.ppm; rm -rf $A/logs
