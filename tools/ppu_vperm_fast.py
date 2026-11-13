#!/usr/bin/env python3
"""Rewrite the lifter's scalar vperm byte loop into vmx_vperm() (runtime/ppu/ppu_vmx.h: pshufb, exact).
Usage: ppu_vperm_fast.py <recompiled dir>...   Idempotent; only touches files that change."""
import re, sys, glob, os
pat = re.compile(r'\{ uint8_t\* a = \(uint8_t\*\)&ctx->vr\[(\d+)\]; uint8_t\* b = \(uint8_t\*\)&ctx->vr\[(\d+)\]; '
                 r'uint8_t\* c = \(uint8_t\*\)&ctx->vr\[(\d+)\]; uint8_t\* d = \(uint8_t\*\)&ctx->vr\[(\d+)\]; '
                 r'uint8_t tmp\[16\]; for \(int i = 0; i < 16; i\+\+\) \{ uint8_t sel = c\[i\] & 0x1F; '
                 r'tmp\[i\] = \(sel < 16\) \? a\[sel\] : b\[sel - 16\]; \} memcpy\(d, tmp, 16\); \}')
tot = 0
for d in sys.argv[1:]:
    for f in sorted(glob.glob(os.path.join(d, 'ppu_recomp_*.cpp'))):
        s = open(f).read()
        t, n = pat.subn(lambda m: f'vmx_vperm(&ctx->vr[{m[4]}], &ctx->vr[{m[1]}], &ctx->vr[{m[2]}], &ctx->vr[{m[3]}]);', s)
        if n:
            st = os.stat(f); open(f, 'w').write(t); tot += n
    left = sum(open(f).read().count('uint8_t sel = c[i] & 0x1F') for f in glob.glob(os.path.join(d, 'ppu_recomp_*.cpp')))
    print(f'{d}: {tot} vperm rewritten so far, {left} scalar loops left')
