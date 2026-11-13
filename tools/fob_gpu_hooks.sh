#!/bin/bash
# FoB's GPU light / SSAO hooks, made from inFamous 2's.
#   fob_gpu_hooks.sh <if2 port dir> <fob port dir>
# The SSAO job (jobmod_e6fe749031f8_e2060) is byte-identical in both games and only its lifted
# image id differs (226 -> 225). FoB's light job (jobmod_faff3c1dc9a7, image 226) is inFamous 2's
# (jobmod_c6e7383dc013, image 219) with every immediate and the op mix the same, the frame/light
# LS slots (0x9C80, 0x9CB0, 0x9E00..0x9E80, 0x9880) the same, and one compare fewer in the tile
# routine 0x4AC8 (the empty-tile test, inverted: it differs only on tiles whose bounds are equal),
# so the code from 0x4F00 on sits 8 bytes lower: the helpers 0x5610/0x5640/0x5AC8/0x5748 and the
# walk's call links 0x6394/0x639C/0x63A4/0x67C0/0x68E8. 0x4578, 0x45C4, 0x45E0, 0x4688, 0x9548
# are unchanged.
set -e
A=$1 B=$2
sed -e 's/jobmod_c6e7383dc013_e5400/jobmod_faff3c1dc9a7_e5400/g' \
    -e 's/jobmod_c6e7383dc013/jobmod_faff3c1dc9a7/g' \
    -e 's/#define LIGHT_JOB_IMAGE 219/#define LIGHT_JOB_IMAGE 226/' \
    -e 's/LJ(00005610)/LJ(00005608)/g; s/LJ(00005640)/LJ(00005638)/g' \
    -e 's/LJ(00005AC8)/LJ(00005AC0)/g; s/LJ(00005748)/LJ(00005740)/g' \
    -e 's/\b0x6394\b/0x638C/g' -e 's/\b0x639C\b/0x6394/g' -e 's/\b0x63A4\b/0x639C/g' \
    -e 's/\b0x67C0\b/0x67B8/g' -e 's/\b0x68E8\b/0x68E0/g' \
    -e "s|^ \* inFAMOUS 2's SPU light pass, moved to the GPU| * Festival of Blood's SPU light pass (inFamous 2's, made by tools/fob_gpu_hooks.sh), moved to the GPU|" \
    "$A/gpu_light.c" > "$B/gpu_light.c"
# ...and log, once, the buffers the job's pass table names: the engine's PS3RECOMP_ENG_GPU_LIGHT
# (normals:depth main-memory copies) and PS3RECOMP_ENG_GPU_SSAO (AO texture) values for this game.
sed -e 's/#define SSAO_JOB_IMAGE 226/#define SSAO_JOB_IMAGE 225/' \
    -e 's|^    const int npass = h\[8\] << 8 \| h\[9\];$|&\
    { static int dbg; if (dbg < 6 \&\& !(h[0] \| h[1] \| h[2] \| h[3])) { dbg++;\
        fprintf(stderr, "[gpu ssao] tap: npass %d table 0x%08X\\n", npass, tab); } }|' \
    -e 's|^    if (ssao_consts_from_passes(pass, npass, 0, ssao_guest, 0, \&c, \&info) == 0)$|    if (ssao_consts_from_passes(pass, npass, 0, ssao_guest, 0, \&c, \&info) == 0) {\
        static int said;\
        if (!said++) fprintf(stderr, "[gpu ssao] pass table: normals 0x%08X depth 0x%08X (light) AO out 0x%08X\\n",\
                             info.normals_ea, info.depth_ea, info.out_ea);|' \
    -e 's|^        rsx_draw_engine_gpu_ssao_data(\&c, (uint32_t)sizeof c, c.dims\[0\], c.dims\[1\], c.dims\[2\], c.dims\[3\]);$|&\
    }|' \
    "$A/gpu_ssao.c" > "$B/gpu_ssao.c"
grep -q 'pass table: normals' "$B/gpu_ssao.c"
# The SSAO pass table names each pass by its plugin's guest address; FoB's five plugins are
# inFamous 2's bytes 0x48000 higher (tools/find_fob_ssao_dm.py, each found once).
sed -e 's/SSAO_DM_DEPTH    0x0087D500u/SSAO_DM_DEPTH    0x008C5500u/' \
    -e 's/SSAO_DM_AO       0x0087F880u/SSAO_DM_AO       0x008C7880u/' \
    -e 's/SSAO_DM_BLUR_H   0x0087D880u/SSAO_DM_BLUR_H   0x008C5880u/' \
    -e 's/SSAO_DM_BLUR_V   0x0087E480u/SSAO_DM_BLUR_V   0x008C6480u/' \
    -e 's/SSAO_DM_UPSAMPLE 0x0087EC80u/SSAO_DM_UPSAMPLE 0x008C6C80u/' \
    "$A/ssao_gpu.h" > "$B/ssao_gpu.h"
[ "$(grep -c '0x008C[5-7][0-9A-F]80u\|0x008C5500u' "$B/ssao_gpu.h")" = 5 ]
grep -q 'LIGHT_JOB_IMAGE 226' "$B/gpu_light.c" && grep -q 'SSAO_JOB_IMAGE 225' "$B/gpu_ssao.c"
grep -c 'c6e7383dc013\|0x63A4\|0x67C0\|0x68E8\|00005610\|00005AC8' "$B/gpu_light.c" | grep -qx 0
echo "fob gpu hooks: light image 226, SSAO image 225 -> $B"
