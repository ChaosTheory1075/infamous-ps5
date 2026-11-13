#!/usr/bin/env python3
# ppu reglocal (2026-11-10): guest GPRs as C locals inside each lifted PPU function.
# Locals live across guest memory accesses (vm_* never touch ctx). At every call that runs other guest code
# (f(ctx), ps3_indirect_call, lv2_syscall, ps3_hle_call) the registers this function writes go back to ctx first,
# and the volatile/argument ones (r0..r13) are reloaded after: r14..r31 are callee-saved by the PPU ABI. Every
# return writes back all written registers. Functions with &ctx->gpr / computed indices are left as they are.
#   ppu_reglocal.py <recompiled dir>   (originals kept in <dir>.pre-rl-<date>; idempotent)
import re, sys, os, glob, shutil, datetime
d = sys.argv[1].rstrip('/')
bk = d + '.pre-rl-' + datetime.date.today().strftime('%Y%m%d')
FN = re.compile(r'^void (func_[0-9A-Fa-f_]+)\(ppu_context\* ctx\) \{$', re.M)
GPR = re.compile(r'ctx->gpr\[(\d+)\]')
WR = re.compile(r'ctx->gpr\[(\d+)\]\s*(?:[-+*/|&^]|<<|>>)?=(?!=)')
CALL = re.compile(r'(ctx->lr = 0x[0-9A-Fa-f]+; )((?:func_[0-9A-Fa-f_]+|ps3_indirect_call)\(ctx\); DRAIN_TRAMPOLINE\(ctx\);)')
SYS = re.compile(r'\blv2_syscall\(ctx\);')
RET = re.compile(r'\breturn;')
stats = [0, 0, 0]
def spill(regs): return ''.join(f'ctx->gpr[{n}] = r_{n}; ' for n in sorted(regs))
def reload(regs): return ''.join(f'r_{n} = ctx->gpr[{n}]; ' for n in sorted(regs))
for f in sorted(glob.glob(d + '/ppu_recomp_*.cpp')):
    s = open(f).read()
    if 'ppu reglocal' in s: continue
    if not os.path.exists(bk):
        os.makedirs(bk)
    shutil.copy2(f, bk)
    out = []; last = 0
    for m in FN.finditer(s):
        b = m.end(); e = s.find('\n}\n', b)
        body = s[b:e]
        stats[0] += 1
        if '&ctx->gpr' in body or re.search(r'ctx->gpr\[[^0-9\]]', body) or 'setjmp' in body:
            stats[1] += 1; continue
        U = set(int(x) for x in GPR.findall(body))
        if not U: continue
        W = set(int(x) for x in WR.findall(body))
        R13 = {n for n in U if n <= 13}
        sp_all = spill(W)
        nb = GPR.sub(lambda mm: 'r_' + mm.group(1), body)
        # the patterns above were matched on ctx->gpr; after substitution calls/returns look the same
        nb = CALL.sub(lambda mm: mm.group(1) + '{ ' + sp_all + mm.group(2) + ' ' + reload(R13) + '}', nb)
        nb = SYS.sub(lambda mm: '{ ' + sp_all + 'lv2_syscall(ctx); ' + reload(R13) + '}', nb)
        nb = RET.sub(lambda mm: '{ ' + sp_all + 'return; }', nb)
        decl = '\n        /* ppu reglocal */ ' + ' '.join(f'uint64_t r_{n} = ctx->gpr[{n}];' for n in sorted(U))
        nb = decl + nb + '\n        ' + sp_all + '/* ppu reglocal: fall-through end */'
        out.append(s[last:b]); out.append(nb); last = e
        stats[2] += 1
    out.append(s[last:])
    open(f, 'w').write('/* ppu reglocal */\n' + ''.join(out))
print('functions', stats[0], 'skipped', stats[1], 'converted', stats[2])
