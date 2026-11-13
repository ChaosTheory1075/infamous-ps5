#!/usr/bin/env python3
# spu leaf (2026-11-10): direct lifted calls to straight-line leaf functions skip the call bracket.
# A leaf: one lifted function whose body is straight-line code ending in `SPU_RET(ctx);` -- no SPU_DIRECT, goto,
# return, trampoline, calls f(ctx), channel ops, stop/halt, r0 writes or spu_link. For such a callee the bracket
#   ctx->gpr[0] = spu_link(RET); { int32_t _si = ...; ctx->host_depth++; F(ctx); spu_drain_call(ctx, RET);
#   ctx->host_depth--; spu_img_restore(ctx, _si); }
# always ends the same way: pc = r0 (= RET), no trampoline, drain_ret_pc = 0, depth back, image restored (the leaf
# never changes image_id). So it becomes: link; F_leaf(ctx) (static inline copy, pc set as SPU_RET does);
# trampoline 0; drain_ret_pc 0; img_restore. Same results; replay digests must not change.
#   spu_leaf.py <spu dir> [module ...]   (in place, original kept as spu_recomp.c.pre-leaf; idempotent)
import re, sys, os, glob, shutil
spu = sys.argv[1]; mods = sys.argv[2:] or [os.path.basename(d) for d in glob.glob(spu + '/jobmod_*') if os.path.isdir(d)]
FN = re.compile(r'^void (\w+_spu_func_[0-9A-F]{8})\(spu_context\* ctx\) \{$', re.M)
BAD = re.compile(r'SPU_DIRECT|goto |return|g_spu_trampoline_fn|spu_(rdch|wrch|rchcnt|stop|halt|link)\(|ctx->gpr\[0\] =|\b\w+\(ctx\);|code_base|SPU_RET_REG|spu_indirect_branch|_spu_func_')
CALL = re.compile(r'ctx->gpr\[0\] = spu_link\((0x[0-9A-F]+)\); \{ int32_t _si = \(int32_t\)ctx->image_id; ctx->host_depth\+\+; (\w+_spu_func_[0-9A-F]{8})\(ctx\); spu_drain_call\(ctx, \1\); ctx->host_depth--; spu_img_restore\(ctx, _si\); \}')
total = 0
for m in sorted(mods):
    src = f'{spu}/{m}/spu_recomp.c'
    if not os.path.exists(src): continue
    s = open(src).read()
    if 'spu leaf' in s: continue
    starts = [(mm.start(), mm.end(), mm.group(1)) for mm in FN.finditer(s)]
    leaves = {}
    for i, (a, b, name) in enumerate(starts):
        e = s.find('\n}\n', b)
        body = s[b:e]
        lines = [l for l in body.strip('\n').split('\n')]
        if not lines or lines[-1].strip() != 'SPU_RET(ctx);': continue
        if BAD.search('\n'.join(lines[:-1])): continue
        leaves[name] = '\n'.join(lines[:-1])
    if not leaves: continue
    n = [0]
    def rep(mm):
        f = mm.group(2)
        if f not in leaves: return mm.group(0)
        n[0] += 1
        return (f'ctx->gpr[0] = spu_link({mm.group(1)}); {{ {f}_leaf(ctx); g_spu_trampoline_fn = 0; ctx->drain_ret_pc = 0; '
                f'spu_img_restore(ctx, (int32_t)ctx->image_id); }} /* spu leaf */')
    s2 = CALL.sub(rep, s)
    if not n[0]: continue
    used = set(re.findall(r'(\w+_spu_func_[0-9A-F]{8})_leaf\(ctx\)', s2))
    defs = ''.join(f'static inline __attribute__((always_inline)) void {f}_leaf(spu_context* ctx) {{\n{leaves[f]}\n    ctx->pc = ctx->gpr[0]._u32[0];   /* as SPU_RET */\n}}\n' for f in sorted(used))
    # put the leaf copies right after the includes (before the first lifted function)
    k = starts[0][0]
    s2 = s2[:k] + '/* spu leaf: inline copies of straight-line leaf callees */\n' + defs + s2[k:]
    shutil.copy2(src, src + '.pre-leaf'); open(src, 'w').write(s2)
    print(m, n[0], 'call sites ->', len(used), 'leaves'); total += n[0]
print('total', total)
