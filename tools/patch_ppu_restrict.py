#!/usr/bin/env python3
# ppu restrict: the lifted PPU functions keep the guest registers in ctx->gpr/fpr/... (host memory)
# and, with -fno-strict-aliasing, every guest store (vm_base + ea) may alias ctx as far as clang
# knows, so every register is reloaded from ctx after each store and written back before it.
# Guest memory never overlaps the ppu_context, so the parameter is marked __restrict: clang may keep
# registers in host registers across guest loads/stores. Codegen only, same semantics.
#   patch_ppu_restrict.py [--undo] [recompiled dir]   (idempotent)
import sys, pathlib, re
args = [a for a in sys.argv[1:] if a != '--undo']; undo = '--undo' in sys.argv
d = pathlib.Path(args[0] if args else __import__("os").path.expanduser("~") + "/if1/infamous2-lle/recompiled")
a, b = re.compile(r'^(void func_[0-9A-F]+)\(ppu_context\* ctx\) \{$', re.M), r'\1(ppu_context* __restrict ctx) {'
if undo: a, b = re.compile(r'^(void func_[0-9A-F]+)\(ppu_context\* __restrict ctx\) \{$', re.M), r'\1(ppu_context* ctx) {'
tot = 0
for f in sorted(d.glob("ppu_recomp_*.cpp")):
    s = f.read_text(); s2, n = a.subn(b, s)
    if n: f.write_text(s2)
    tot += n
print("ppu restrict:", "undone on" if undo else "applied to", tot, "functions")
