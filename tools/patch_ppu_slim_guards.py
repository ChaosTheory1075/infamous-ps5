# ppu slim guards: the inline guest load/store checks of the lifted code with the values that are constant in a
# game build (profile 2026-11-07: ~11% of the main thread's hottest functions sat on reloads of these globals,
# which -fno-strict-aliasing makes the compiler re-read after every guest store):
#   ppu_vm_size == 0 (PS5/Linux map the whole space), ppu_hle_inject_base == 0x20000000 (cellGcmSys default;
#   if1 never moves it), vm_inline_ok == 1 and g_barrier_sync_watch / g_null_sweep_hi == 0 (diagnostics only),
#   s_coh_armed (the bitmap alone answers: it is all zero until an SPU reserves a line).
# Kept: the null-page / MMIO range check, the RSX reference poll address (inject + 0x2008), the coherence bitmap
# before and after a store. PPU_SLIM_GUARDS is defined with PPU_FAST_FLOAT in ppu_recomp.h; PPU_EXACT_GUARDS undoes it.
#   patch_ppu_slim_guards.py [~/if1/infamous2-lle]   (idempotent)
import sys, pathlib, glob
root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else __import__("os").path.expanduser("~") + "/if1/infamous2-lle")
heads = [root / "recompiled" / "ppu_recomp.h"] + [pathlib.Path(p) for p in glob.glob(str(root / "lle" / "*" / "*_recomp.h"))]
OLD_OK = '''static inline int vm_inl_ok(uint32_t ea, uint32_t n)
{
    return __builtin_expect(vm_inline_ok, 1) && ea >= 0x10000u && ea < 0xE0000000u &&
           ea != ppu_hle_inject_base + 0x2008u &&
           (ppu_vm_size == 0 || (uint64_t)ea + n <= ppu_vm_size);
}'''
NEW_OK = '''#if !defined(PPU_EXACT_GUARDS)   /* ppu slim guards (tools/patch_ppu_slim_guards.py) */
static inline int vm_inl_ok(uint32_t ea, uint32_t n)
{
    (void)n;
    return ea - 0x10000u < 0xE0000000u - 0x10000u && ea != 0x20000000u + 0x2008u;
}
#else
static inline int vm_inl_ok(uint32_t ea, uint32_t n)
{
    return __builtin_expect(vm_inline_ok, 1) && ea >= 0x10000u && ea < 0xE0000000u &&
           ea != ppu_hle_inject_base + 0x2008u &&
           (ppu_vm_size == 0 || (uint64_t)ea + n <= ppu_vm_size);
}
#endif'''
OLD_COH = '''static inline int vm_coh_res_inl(uint32_t ea)
{
    if (!__atomic_load_n(&s_coh_armed, __ATOMIC_ACQUIRE)) return 0;'''
NEW_COH = '''static inline int vm_coh_res_inl(uint32_t ea)
{
#if defined(PPU_EXACT_GUARDS)
    if (!__atomic_load_n(&s_coh_armed, __ATOMIC_ACQUIRE)) return 0;
#endif'''
OLD_ST = '''    return vm_inl_ok(ea, n) && __builtin_expect(!g_barrier_sync_watch && !g_null_sweep_hi, 1) &&
           !vm_coh_res_inl(ea);'''
NEW_ST = '''#if !defined(PPU_EXACT_GUARDS)
    return vm_inl_ok(ea, n) && !vm_coh_res_inl(ea);   /* ppu slim guards */
#else
    return vm_inl_ok(ea, n) && __builtin_expect(!g_barrier_sync_watch && !g_null_sweep_hi, 1) &&
           !vm_coh_res_inl(ea);
#endif'''
for h in heads:
    s = h.read_text()
    if "ppu slim guards" in s: print("already:", h); continue
    done = []
    for old, new, nm in ((OLD_OK, NEW_OK, "ok"), (OLD_COH, NEW_COH, "coh"), (OLD_ST, NEW_ST, "st")):
        if s.count(old) == 1: s = s.replace(old, new); done.append(nm)
    h.write_text(s); print(h.name, h.parent.name, "patched:", done)
