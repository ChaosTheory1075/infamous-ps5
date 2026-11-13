# ppu fast float: the recompiled PPU code's float semantics as RPCS3's defaults (its "Accurate PPU vector NaN" /
# "Accurate non-Java mode" are off): scalar fadd/fsub/fmul/fdiv/fmadd skip the operand-order NaN propagation and the
# positive default QNaN (x86's own NaN results instead); frsp is a plain convert; VMX vaddfp/vsubfp/vmaddfp/vnmsubfp
# skip the NJ denormal flush and the NaN fix-up. fma stays fused and float->int stays exact (saturating). Profile
# 2026-11-07: the NaN/flush masks were the hottest instructions of the main thread's hot functions.
# Switch: PPU_FAST_FLOAT (defined at the top of recompiled/ppu_recomp.h); remove the define for the exact forms.
#   patch_ppu_fast_float.py [~/if1/infamous2-lle]   (idempotent)
import sys, pathlib, glob
root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else __import__("os").path.expanduser("~") + "/if1/infamous2-lle")
def edit_file(p, pairs, tag):
    s = p.read_text()
    if tag in s: return 0
    for old, new in pairs:
        if s.count(old) != 1: print("SKIP (not found once):", p, old[:50]); return 0
        s = s.replace(old, new)
    p.write_text(s); return 1
FP = [("static inline double ppu_fp_bin(double a, double b, double r)\n{\n",
       "static inline double ppu_fp_bin(double a, double b, double r)\n{\n#ifdef PPU_FAST_FLOAT   /* ppu fast float */\n    (void)a; (void)b; return r;\n#endif\n"),
      ("static inline double ppu_fmadd_core(double a, double c, double b, int neg_b, int neg_res)\n{\n",
       "static inline double ppu_fmadd_core(double a, double c, double b, int neg_b, int neg_res)\n{\n#ifdef PPU_FAST_FLOAT   /* ppu fast float: still fused */\n    { const double r = fma(a, c, neg_b ? -b : b); return neg_res ? -r : r; }\n#endif\n"),
      ("static inline double ppu_frsp(double b)\n{\n",
       "static inline double ppu_frsp(double b)\n{\n#ifdef PPU_FAST_FLOAT   /* ppu fast float */\n    return (double)(float)b;\n#endif\n")]
n = 0
files = sorted(glob.glob(str(root / "recompiled" / "ppu_recomp_0*.cpp"))) + sorted(glob.glob(str(root / "lle" / "*" / "*_recomp_0*.cpp")))
for f in files:
    s = pathlib.Path(f).read_text()
    if "static inline double ppu_fp_bin" not in s: continue
    n += edit_file(pathlib.Path(f), FP, "ppu fast float")
print("lifted files patched:", n, "of", len(files))
h = root / "recompiled" / "ppu_recomp.h"
s = h.read_text()
if "PPU_FAST_FLOAT" not in s:
    i = s.index("#include <stdint.h>")
    s = s[:i] + "/* ppu fast float (tools/patch_ppu_fast_float.py): RPCS3-default float semantics in the lifted code */\n#ifndef PPU_EXACT_FLOAT\n#define PPU_FAST_FLOAT 1\n#endif\n" + s[i:]
    h.write_text(s); print("ppu_recomp.h: define added")
v = pathlib.Path(__import__("os").path.expanduser("~") + "/if2/ps3recomp-fork/runtime/ppu/ppu_vmx.h")
s = v.read_text()
if "ppu fast float" not in s:
    old = "VMX_XV void vmx_vaddfp(VMX_D, VMX_A, VMX_B, uint32_t vscr) {"
    assert s.count(old) == 1
    fast = '''#ifdef PPU_FAST_FLOAT   /* ppu fast float: no NJ flush, no NaN fix-up (RPCS3 defaults) */
VMX_XV void vmx_vaddfp(VMX_D, VMX_A, VMX_B, uint32_t vscr) { (void)vscr;
    vmx__st(d_, _mm_castps_si128(_mm_add_ps(_mm_castsi128_ps(vmx__ld(a_)), _mm_castsi128_ps(vmx__ld(b_))))); }
VMX_XV void vmx_vsubfp(VMX_D, VMX_A, VMX_B, uint32_t vscr) { (void)vscr;
    vmx__st(d_, _mm_castps_si128(_mm_sub_ps(_mm_castsi128_ps(vmx__ld(a_)), _mm_castsi128_ps(vmx__ld(b_))))); }
VMX_XV void vmx_vmaddfp(VMX_D, VMX_A, VMX_B, VMX_C, uint32_t vscr) { (void)vscr;
    vmx__st(d_, _mm_castps_si128(_mm_fmadd_ps(_mm_castsi128_ps(vmx__ld(a_)), _mm_castsi128_ps(vmx__ld(c_)), _mm_castsi128_ps(vmx__ld(b_))))); }
VMX_XV void vmx_vnmsubfp(VMX_D, VMX_A, VMX_B, VMX_C, uint32_t vscr) { (void)vscr;
    vmx__st(d_, _mm_xor_si128(_mm_castps_si128(_mm_fmsub_ps(_mm_castsi128_ps(vmx__ld(a_)), _mm_castsi128_ps(vmx__ld(c_)), _mm_castsi128_ps(vmx__ld(b_)))),
                              _mm_set1_epi32((int)0x80000000u))); }
#else
'''
    s = s.replace(old, fast + old, 1)
    old_end = "#else\n#define vmx_vaddfp   vmx_vaddfp_ref"
    assert s.count(old_end) == 1
    s = s.replace(old_end, "#endif   /* ppu fast float */\n" + old_end, 1)
    v.write_text(s); print("ppu_vmx.h patched")
