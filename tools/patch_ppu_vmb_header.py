#!/usr/bin/env python3
"""ppu vmb header (if1, 2026-11-11): the inline guest-access helpers of the lifted PPU headers address guest memory
off PPU_VMB, which is the constant PPU_VM_BASE_CONST when the port is configured with -DPPU_VM_BASE_CONST=<addr>
(tools/patch_port_cmake.py) and plain vm_base otherwise (default: the same code as without this edit). main.cpp's
side is tools/if1_patch_port.py. Post-lift step (tools/postlift.sh); edits in place, idempotent, and stops on a
header whose preamble is not the expected one (never skips silently).
  patch_ppu_vmb_header.py <port dir (.../infamous2-lle)>
    -> recompiled/ppu_recomp.h and lle/*/*_recomp.h"""
import sys, re, glob, os

DECL = "extern uint8_t* vm_base;\n"
ALN = "(uintptr_t)_p & (sizeof(T) - 1)"
BLOCK = DECL + '''/* B1 constant guest base (2026-11-11). With -DPPU_VM_BASE_CONST=<address> the inline fast paths below address
 * guest memory off that constant instead of the vm_base global: the lifted code is built -fno-strict-aliasing,
 * so clang had to reload the global after every guest store (a load and a dependency per access). The global
 * stays for the runtime and for the direct uses in the lifted sources (dcbz, lvlx/lvrx); main.cpp maps the guest
 * window at the constant and stops at startup if it is anywhere else. ppu_vm_base_const_value is defined by
 * main.cpp only when main.cpp was built with the same switch, so a build that has the switch on the lifted code
 * alone fails at link instead of running with two different bases. Without the switch PPU_VMB is vm_base.
 *
 * PPU_VMB_ALIGN is the host address VM_RAW_LD/VM_RAW_ST test for alignment. With a constant 4 GB-aligned base
 * clang can fold that test wherever the guest address is known to be aligned (every lvx/stvx: ea & ~0xF), which
 * removes a branch -- and so changes the function's control flow, and an IR profile (-fprofile-use) collected
 * from a build without the fold no longer matches it ("hash mismatch", silenced by -Wno-profile-instr-out-of-date):
 * the function is then compiled without its profile. In if1 5,526 of 27,305 lifted functions use lvx/stvx and
 * they hold 36% of the lifted code's profile weight. So by default the test goes through an empty asm (no
 * instruction, but opaque to the optimizer): the control flow stays what it is without the switch and an
 * existing profile keeps matching (checked: 304 functions of ppu_recomp_015.cpp, 0 mismatches; 4 with the fold).
 * -DPPU_VM_BASE_CONST_FOLD lets the test fold; use it only with a profile collected from a build that had it. */
#ifdef PPU_VM_BASE_CONST
#  define PPU_VMB ((uint8_t*)(uintptr_t)(PPU_VM_BASE_CONST))
extern const uint64_t ppu_vm_base_const_value;
__attribute__((used)) static const uint64_t* const ppu_vm_base_const_ref = &ppu_vm_base_const_value;
#  ifdef PPU_VM_BASE_CONST_FOLD
#    define PPU_VMB_ALIGN(p) ((uintptr_t)(p))
#  else
static inline __attribute__((always_inline)) uintptr_t ppu_vmb_align(const uint8_t* p)
{ uintptr_t a = (uintptr_t)p; __asm__("" : "+r"(a)); return a; }
#    define PPU_VMB_ALIGN(p) ppu_vmb_align(p)
#  endif
#else
#  define PPU_VMB vm_base
#  define PPU_VMB_ALIGN(p) ((uintptr_t)(p))
#endif
'''


def patch(path):
    s = open(path, encoding='utf-8', newline='').read()
    if 'PPU_VMB' in s:
        print(f"{path}: already there")
        return
    if s.count(DECL) != 1:
        sys.exit(f"{path}: ppu vmb header: {s.count(DECL)} vm_base declarations, expected 1")
    head, tail = s.split(DECL)
    end = tail.find("void lv2_syscall(ppu_context* ctx);")
    if end < 0:
        sys.exit(f"{path}: ppu vmb header: end of the helper preamble (lv2_syscall prototype) not found")
    pre, rest = tail[:end], tail[end:]
    if 'vm_base' in rest or 'vm_base' in head:
        sys.exit(f"{path}: ppu vmb header: vm_base used outside the helper preamble")
    n = len(re.findall(r'\bvm_base\b', pre))
    pre = re.sub(r'\bvm_base\b', 'PPU_VMB', pre)
    if pre.count(ALN) != 2:
        sys.exit(f"{path}: ppu vmb header: alignment test found {pre.count(ALN)} times, expected 2 (VM_RAW_LD, VM_RAW_ST)")
    pre = pre.replace(ALN, "PPU_VMB_ALIGN(_p) & (sizeof(T) - 1)")
    open(path, 'w', encoding='utf-8', newline='').write(head + BLOCK + pre + rest)
    print(f"{path}: {n} vm_base uses -> PPU_VMB")


port = sys.argv[1] if len(sys.argv) > 1 else sys.exit(__doc__)
heads = [os.path.join(port, "recompiled", "ppu_recomp.h")] + sorted(glob.glob(os.path.join(port, "lle", "*", "*_recomp.h")))
if not os.path.isfile(heads[0]):
    sys.exit(f"{heads[0]}: not found")
for h in heads:
    patch(h)
