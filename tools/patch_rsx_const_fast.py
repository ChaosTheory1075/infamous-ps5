# rsx const fast: transform-constant words go straight to their handler in rsx_process_method.
# The method is matched by a ~60-test if-chain; the constant window (0x1EFC load + 0x1F00..0x1F7C) sat
# near its end. inFAMOUS 1's crater sends ~405k FIFO words per frame, most of them constant uploads
# (RSX_METHOD_HIST, 2026-11-02: 0x1EFC and each of 0x1F00..0x1F0C 2.4M per 10 s). No test before
# those handlers matches 0x1EFC..0x1F7C, so the jump changes nothing but the order.
CMD = "libs/video/rsx_commands.c"
edit(CMD,
     '''      if(_rt){ static int _m=0; if(PS3_LOG_FIRST(_m, _rt)) fprintf(stderr,"[rsxm] method=0x%04X data=0x%08X\\n", method, data); } }''',
     '''      if(_rt){ static int _m=0; if(PS3_LOG_FIRST(_m, _rt)) fprintf(stderr,"[rsxm] method=0x%04X data=0x%08X\\n", method, data); } }
    /* rsx const fast (tools/patch_rsx_const_fast.py): the constant window first */
    if (method >= NV4097_SET_TRANSFORM_CONSTANT_LOAD &&
        method <  NV4097_SET_TRANSFORM_CONSTANT + NV4097_SET_TRANSFORM_CONSTANT_DWORDS * 4) {
        if (method == NV4097_SET_TRANSFORM_CONSTANT_LOAD) goto rsxm_const_load;
        goto rsxm_const;
    }''',
     "rsx const fast: jump")
edit(CMD,
     '''    if (method == NV4097_SET_TRANSFORM_CONSTANT_LOAD) {
        { static int _n=0, _e=-1;''',
     '''rsxm_const_load:   /* rsx const fast */
    if (method == NV4097_SET_TRANSFORM_CONSTANT_LOAD) {
        { static int _n=0, _e=-1;''',
     "rsx const fast: load label")
edit(CMD,
     '''     * SET_TRANSFORM_CONSTANT_LOAD before each block. */
    if (method >= NV4097_SET_TRANSFORM_CONSTANT &&''',
     '''     * SET_TRANSFORM_CONSTANT_LOAD before each block. */
rsxm_const:   /* rsx const fast */
    if (method >= NV4097_SET_TRANSFORM_CONSTANT &&''',
     "rsx const fast: const label")
