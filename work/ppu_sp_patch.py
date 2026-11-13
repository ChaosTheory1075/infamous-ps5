#!/usr/bin/env python3
# ppu sp fast: ppu_sp_patch.py <recompiled dir>: adds vm_sp_* helpers to ppu_recomp.h and rewrites the lifted
# vm_read/vm_write calls addressed off r1 (ctx->gpr[1]) to them. Originals kept in <dir>.pre-sp-<date>. Idempotent.
import re, glob, os, sys, shutil, datetime
d = sys.argv[1].rstrip('/')
bk = d + '.pre-sp-' + datetime.date.today().strftime('%Y%m%d')
h = os.path.join(d, 'ppu_recomp.h'); s = open(h).read()
if 'vm_sp_write8' not in s:
    if not os.path.exists(bk):
        os.makedirs(bk); [shutil.copy2(f, bk) for f in glob.glob(d + '/ppu_recomp*')]
    anchor = '#define vm_write64(a, v) vm_write64_inl(a, v)\n#endif\n'
    assert anchor in s, 'anchor missing in ' + h
    blk = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ppu_sp_block.h')).read()
    open(h, 'w').write(s.replace(anchor, anchor + blk, 1))
rw = re.compile(r'\bvm_(write|read)(8|16|32|64)\(ctx->gpr\[1\](?=[ )])')
tot = 0
for f in sorted(glob.glob(d + '/ppu_recomp_*.cpp')):
    t = open(f).read(); t2, n = rw.subn(lambda m: 'vm_sp_%s%s(ctx->gpr[1]' % (m.group(1), m.group(2)), t); tot += n
    if n: open(f, 'w').write(t2)
print(d, 'patched', tot)
