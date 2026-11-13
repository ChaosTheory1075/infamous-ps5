#!/usr/bin/env python3
# spu lsb: each lifted SPU function that touches local store copies ctx->ls into a local (_lsb) once;
# the LS helpers then index that local (spu_context.h, SPU_LIFTED_LSB). ctx->ls never changes while a
# lifted function runs (it is set when the context is made), but it is a field of the same struct the
# LS stores write into, so clang reloaded it after every store. Codegen only, same results.
#   spu_lsb.py <spu_recomp.c> ...   (in place, original kept as .pre-lsb; idempotent)   --undo restores
import re, sys, os
FN = re.compile(r'^void [A-Za-z0-9_]+\(spu_context\* ctx\) \{$')
args = sys.argv[1:]
if args and args[0] == "--undo":
    for p in args[1:]:
        if os.path.exists(p + ".pre-lsb"): os.replace(p + ".pre-lsb", p); print(p, "restored")
    sys.exit(0)
for p in args:
    s = open(p).read()
    if "spu lsb (tools/spu_lsb.py)" in s: print(p, "already"); continue
    lines = s.split("\n"); out = []; i = 0; n = 0
    while i < len(lines):
        out.append(lines[i])
        if FN.match(lines[i]):
            j = i + 1
            while j < len(lines) and lines[j] != "}": j += 1
            if any("spu_ls_read128(" in l or "spu_ls_write128(" in l for l in lines[i + 1:j]):
                out.append("    uint8_t* const _lsb = ctx->ls;   /* spu lsb (tools/spu_lsb.py) */"); n += 1
        i += 1
    open(p + ".pre-lsb", "w").write(s); open(p, "w").write("\n".join(out))
    print(p, n, "functions")
