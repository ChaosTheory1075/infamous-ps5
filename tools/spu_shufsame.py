#!/usr/bin/env python3
# spu shufb same (2026-11-10): spu_shufb(rN, rN, c) -> spu_shufb_same(rN, c) in lifted SPU sources (identical results:
# both sources are one register). spu_shufsame.py <spu dir>   (in place; idempotent)
import re, sys, glob
pat = re.compile(r'spu_shufb\((ctx->gpr\[(\d+)\]), ctx->gpr\[\2\], ')
tot = 0
for f in sorted(glob.glob(sys.argv[1].rstrip('/') + '/*/spu_recomp.c')):
    s = open(f).read(); s2, n = pat.subn(r'spu_shufb_same(\1, ', s)
    if n: open(f, 'w').write(s2); tot += n
print(sys.argv[1], 'shufb same sites', tot)
