/* The AVX2/FMA VMX float forms (patch_ppu_fast.py) against the scalar *_ref forms, bit for bit:
 * random words plus zeros, denormals, infinities and NaNs, with VSCR NJ off and on.
 *   clang -O2 -march=znver2 -ffp-contract=off -I<fork>/runtime/ppu test_vmx_fast.c -lm && ./a.out */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ppu_vmx.h"

static uint32_t rnd(void)
{
    static uint64_t s = 0x9E3779B97F4A7C15ull;
    s ^= s << 13; s ^= s >> 7; s ^= s << 17;
    static const uint32_t special[] = { 0, 0x80000000u, 1, 0x807FFFFFu, 0x00400000u, 0x7F800000u, 0xFF800000u,
                                        0x7FC00000u, 0x7F800001u, 0xFFC00001u, 0x3F800000u, 0xBF800000u, 0x7F7FFFFFu };
    if ((s & 7) == 0) return special[(s >> 8) % (sizeof special / sizeof special[0])];
    return (uint32_t)(s >> 16);
}
static void fill(uint8_t* v) { for (int i = 0; i < 4; i++) { uint32_t w = rnd(); vmx_sw(v, i, w); } }

int main(void)
{
    long bad = 0, n = 0;
    for (int it = 0; it < 2000000; it++) {
        uint8_t a[16], b[16], c[16], r1[16], r2[16];
        fill(a); fill(b); fill(c);
        const uint32_t vscr = (it & 1) ? VMX_NJ : 0;
        vmx_vaddfp(r1, a, b, vscr);   vmx_vaddfp_ref(r2, a, b, vscr);   n++; if (memcmp(r1, r2, 16)) { if (bad++ < 5) printf("vaddfp mismatch\n"); }
        vmx_vsubfp(r1, a, b, vscr);   vmx_vsubfp_ref(r2, a, b, vscr);   n++; if (memcmp(r1, r2, 16)) { if (bad++ < 5) printf("vsubfp mismatch\n"); }
        vmx_vmaddfp(r1, a, b, c, vscr);  vmx_vmaddfp_ref(r2, a, b, c, vscr);  n++; if (memcmp(r1, r2, 16)) { if (bad++ < 5) printf("vmaddfp mismatch\n"); }
        vmx_vnmsubfp(r1, a, b, c, vscr); vmx_vnmsubfp_ref(r2, a, b, c, vscr); n++;
        if (memcmp(r1, r2, 16)) { if (bad++ < 5) printf("vnmsubfp mismatch a=%08X b=%08X c=%08X: %08X vs %08X\n", vmx_w(a,0), vmx_w(b,0), vmx_w(c,0), vmx_w(r1,0), vmx_w(r2,0)); }
    }
    printf("%ld of %ld vector results differ\n", bad, n);
    return bad != 0;
}
