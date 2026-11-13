#!/usr/bin/env python3
"""rewrite_vshuf.py -- inFAMOUS 1 lifted sources: vspltw / vsldoi blocks -> PPU_VSPLTW / PPU_VSLDOI macros.

The macros (recompiled/ppu_recomp.h, if1_header.patch) expand to one 16-byte load + pshufd/palignr + one 16-byte store
when PPU_VMX_SHUF is on, and to the exact original text when it is off (-DPPU_VMX_SHUF=0). Straight-line code both
ways, no select, no branch: the IR-PGO CFG hash of every function stays the same (checked: mb/pgo_hash.sh).

Usage:  rewrite_vshuf.py --check  DIR     count only, writes nothing
        rewrite_vshuf.py --apply  DIR     rewrite DIR/ppu_recomp_0*.cpp in place, backup *.pre-vshuf-<date>
        rewrite_vshuf.py --out OUTDIR DIR write rewritten copies to OUTDIR
Only the exact emitter text is matched (ppu_lifter.py vspltw / vsldoi forms); anything else is left alone.
"""
import re, sys, glob, os, shutil, time
SPLTW = re.compile(r'\{ uint32_t\* d = \(uint32_t\*\)&ctx->vr\[(\d+)\]; uint32_t val = \(\(uint32_t\*\)&ctx->vr\[(\d+)\]\)\[([0-3])\]; '
                   r'd\[0\] = d\[1\] = d\[2\] = d\[3\] = val; \}')
SLDOI = re.compile(r'\{ uint8_t tmp\[32\]; memcpy\(tmp, &ctx->vr\[(\d+)\], 16\); memcpy\(tmp\+16, &ctx->vr\[(\d+)\], 16\); '
                   r'memcpy\(&ctx->vr\[(\d+)\], tmp \+ ([0-9]|1[0-5]), 16\); \}')
def conv(s):
    s, n1 = SPLTW.subn(lambda m: 'PPU_VSPLTW(%s, %s, %s)' % (m.group(1), m.group(2), m.group(3)), s)
    s, n2 = SLDOI.subn(lambda m: 'PPU_VSLDOI(%s, %s, %s, %s)' % (m.group(3), m.group(1), m.group(2), m.group(4)), s)
    return s, n1, n2
def main():
    mode = sys.argv[1]; d = sys.argv[-1]
    out = sys.argv[2] if mode == '--out' else None
    tag = time.strftime('%Y%m%d')
    t1 = t2 = 0
    for fn in sorted(glob.glob(os.path.join(d, 'ppu_recomp_0*.cpp'))):
        s = open(fn).read()
        if 'PPU_VSPLTW(' in s or 'PPU_VSLDOI(' in s:
            print('%s: already rewritten, skipped' % fn); continue
        r, n1, n2 = conv(s)
        t1 += n1; t2 += n2
        print('%s: vspltw %d vsldoi %d' % (os.path.basename(fn), n1, n2))
        if mode == '--apply':
            shutil.copy2(fn, fn + '.pre-vshuf-' + tag); open(fn, 'w').write(r)
        elif mode == '--out':
            os.makedirs(out, exist_ok=True); open(os.path.join(out, os.path.basename(fn)), 'w').write(r)
    print('total vspltw %d vsldoi %d' % (t1, t2))
if __name__ == '__main__':
    main()
