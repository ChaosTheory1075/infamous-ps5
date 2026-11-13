#!/usr/bin/env python3
# spu jtab (2026-11-10): jump tables in lifted SPU jobmods become a switch of direct tail calls.
# Pattern inside one lifted function: rT = ila TABLE; rX = lqx(rT + rK); rR = rotqby(rX, ..); a bound clgti(rI, N);
# ends in the computed jump `ctx->pc = ctx->gpr[R]._u32[0]; g_spu_trampoline_fn = spu_indirect_branch; return;`.
# The table (N+1 words at TABLE in the module image, loaded at LS 0x4000) names the cases; each case is the function
# lifted at that address, entered with SPU_DIRECT exactly like a static branch. Any other target takes the computed
# jump as before. Same results; replay digests must not change.
#   spu_jtab.py <spu dir> [module ...]   (in place, original kept as spu_recomp.c.pre-jtab; idempotent)
import re, sys, os, struct, glob, shutil
spu = sys.argv[1]; mods = sys.argv[2:] or [os.path.basename(d) for d in glob.glob(spu + '/jobmod_*') if os.path.isdir(d)]
FN = re.compile(r'^void (\w+_spu_func_([0-9A-F]{8}))\(spu_context\* ctx\) \{$', re.M)
JMP = re.compile(r'^(\s*)ctx->pc = ctx->gpr\[(\d+)\]\._u32\[0\]; g_spu_trampoline_fn = spu_indirect_branch; return;$', re.M)
tot_sites = 0
for m in sorted(mods):
    src = f'{spu}/{m}/spu_recomp.c'; binp = f'{spu}/jobmods/{m}.bin'
    if not os.path.exists(src) or not os.path.exists(binp): continue
    s = open(src).read()
    if 'spu jtab' in s: continue
    img = open(binp, 'rb').read()
    fns = {int(a, 16): n for n, a in FN.findall(s)}
    starts = [mm.start() for mm in FN.finditer(s)] + [len(s)]
    out = []; last = 0; sites = 0
    for i in range(len(starts) - 1):
        body = s[starts[i]:starts[i + 1]]
        if 'code_base' in body: continue
        j = JMP.search(body)
        if not j: continue
        R = j.group(2)
        rot = re.search(r'ctx->gpr\[' + R + r'\] = spu_rotqby\(ctx->gpr\[(\d+)\]', body)
        if not rot: continue
        X = rot.group(1)
        ld = re.search(r'ctx->gpr\[' + X + r'\] = spu_ls_read128\(ctx, ctx->gpr\[(\d+)\]\._u32\[0\] \+ ctx->gpr\[(\d+)\]\._u32\[0\]\)', body)
        if not ld: continue
        tab = None
        for T in ld.groups():
            t = re.search(r'ctx->gpr\[' + T + r'\] = spu_ila\(0x([0-9A-Fa-f]+)\)', body)
            if t: tab = int(t.group(1), 16)
        bound = re.search(r'spu_clgti\(ctx->gpr\[\d+\], (\d+)\)', body)
        if tab is None or not bound: continue
        n = int(bound.group(1)) + 1
        off = tab - 0x4000
        if off < 0 or off + 4 * n > len(img) or n > 256: continue
        words = struct.unpack('>%dI' % n, img[off:off + 4 * n])
        tg = sorted(set(w & 0x3FFFF for w in words if (w & 0x3FFFF) in fns))
        if not tg: continue
        ind = j.group(1)
        cases = ' '.join(f'case 0x{a:X}: SPU_DIRECT(ctx, 0x{a:X}, {fns[a]});' for a in tg)
        new = (f'{ind}switch (ctx->gpr[{R}]._u32[0] & SPU_LS_MASK) {{ /* spu jtab: table 0x{tab:X} ({n}) */ {cases} default: break; }}\n'
               f'{ind}ctx->pc = ctx->gpr[{R}]._u32[0]; g_spu_trampoline_fn = spu_indirect_branch; return;')
        a = starts[i] + j.start(); b = starts[i] + j.end()
        out.append(s[last:a]); out.append(new); last = b; sites += 1
    if sites:
        shutil.copy2(src, src + '.pre-jtab')
        out.append(s[last:]); open(src, 'w').write('/* spu jtab */\n' + ''.join(out))
        print(m, sites, 'jump tables'); tot_sites += sites
print('total', tot_sites)
