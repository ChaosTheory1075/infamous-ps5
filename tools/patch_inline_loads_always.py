#!/usr/bin/env python3
# always-inline guest access helpers: the generated loads (vm_read*_inl) and the store/coherence
# checks (vm_inl_ok, vm_coh_res_inl, vm_st_inl_ok) were plain `static inline`, and clang gives up
# inlining in the huge lifted PPU functions: perf annotate of func_003E0400 (if1 spawn, BC-250)
# shows `call vm_read32_inl` -- every guest load a real call. The stores already had
# always_inline. Same code, same semantics (no runtime switch possible: it is codegen only).
#   patch_inline_loads_always.py <file> ...   (idempotent; ppu_recomp.h, ppu_lifter.py, patch texts)
import sys, re
names = r'vm_inl_ok|vm_coh_res_inl|vm_st_inl_ok|vm_read8_inl|vm_read16_inl|vm_read32_inl|vm_read64_inl'
pat = re.compile(r'static inline ((?:int|uint8_t|uint16_t|uint32_t|uint64_t) (?:%s)\()' % names)
for p in sys.argv[1:]:
    s = open(p).read()
    n = len(pat.findall(s))
    s = pat.sub(r'static inline __attribute__((always_inline)) \1', s)
    open(p, 'w').write(s)
    print(p, n, "helpers made always_inline")
