#!/usr/bin/env python3
"""if1_header_vmx.py [IF1_LLE_DIR] -- inFAMOUS 1 lifted header: PPU_VMX_VEC / PPU_VMX_SHUF switches and the
PPU_VSPLTW / PPU_VSLDOI macros used after rewrite_vshuf.py. Inserts our block right after the header's first
#include <stdint.h> (the lifter's own preamble). Idempotent. Default dir: ${IF1_LLE_DIR:-~/if1/infamous2-lle}."""
import os, sys, pathlib
root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("IF1_LLE_DIR", __import__("os").path.expanduser("~") + "/if1/infamous2-lle"))
h = root / "recompiled" / "ppu_recomp.h"
with open(h, newline="") as f:
    s = f.read()
if "PPU_VSPLTW" in s:
    print("if1 header vmx: already applied"); sys.exit(0)
BLOCK = r'''/* ppu vmx vec / shuf (2026-11-11, work/agent_if1hot; inFAMOUS 1 only -- this header is if1's own).
 * PPU_VMX_VEC: runtime/ppu/ppu_vmx.h uses SSE forms of vrefp/vrsqrtefp/vmaxfp/vminfp/vcmp{gt,ge,eq}fp/vcmpequw
 *   (bit-identical to the scalar loops; changes callers' CFG -> collect a new IR profile with it on).
 * PPU_VMX_SHUF: PPU_VSPLTW / PPU_VSLDOI (written into the lifted sources by work/agent_if1hot/patches/
 *   rewrite_vshuf.py) are one 16-byte load + pshufd/palignr + one 16-byte store instead of four 4-byte stores
 *   (vspltw into its own source register) or a 32-byte stack round trip (vsldoi): both made the next 16-byte read
 *   of the register a failed store-to-load forward on Zen 2. Straight-line both ways: PGO-neutral.
 * -DPPU_VMX_VEC=0 / -DPPU_VMX_SHUF=0 = the code as it was. */
#ifndef PPU_VMX_VEC
#define PPU_VMX_VEC 1
#endif
#ifndef PPU_VMX_SHUF
#define PPU_VMX_SHUF 1
#endif
#if PPU_VMX_SHUF && defined(__SSSE3__)
#include <immintrin.h>
#define PPU_VSPLTW(D, B, I) { _mm_storeu_si128((__m128i*)&ctx->vr[D], \
    _mm_shuffle_epi32(_mm_loadu_si128((const __m128i*)&ctx->vr[B]), (I) * 0x55)); }
#define PPU_VSLDOI(D, A, B, S) { const __m128i _vsa = _mm_loadu_si128((const __m128i*)&ctx->vr[A]); \
    _mm_storeu_si128((__m128i*)&ctx->vr[D], _mm_alignr_epi8(_mm_loadu_si128((const __m128i*)&ctx->vr[B]), _vsa, (S))); }
#else   /* the emitter's text */
#define PPU_VSPLTW(D, B, I) { uint32_t* d = (uint32_t*)&ctx->vr[D]; uint32_t val = ((uint32_t*)&ctx->vr[B])[I]; \
    d[0] = d[1] = d[2] = d[3] = val; }
#define PPU_VSLDOI(D, A, B, S) { uint8_t tmp[32]; memcpy(tmp, &ctx->vr[A], 16); memcpy(tmp+16, &ctx->vr[B], 16); \
    memcpy(&ctx->vr[D], tmp + S, 16); }
#endif
'''
A = "#include <stdint.h>\n"
assert A in s, "ppu_recomp.h: #include <stdint.h> not found"
i = s.index(A) + len(A)
assert i < 4096, "ppu_recomp.h: #include <stdint.h> not in the preamble"
s = s[:i] + BLOCK + s[i:]
with open(h, "w", newline="") as f:
    f.write(s)
print("if1 header vmx: applied to", h)
