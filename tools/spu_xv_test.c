/* Exactness check of the AVX2 SPU float fast path against the exact lanes (spu_*_ref).
 *   clang-18 -O2 -march=znver2 -I<fork>/runtime/spu -I<fork>/include tools/spu_xv_test.c -lm
 * Operands mix ordinary values, tiny ones (products/sums that underflow), denormals, zeros,
 * extended-range (exponent 255) values and near-cancelling pairs. Prints mismatches; exit 1 on any. */
#include "spu_helpers.h"
#include <stdio.h>
#include <stdlib.h>

static uint64_t s = 0x9E3779B97F4A7C15ull;
static uint32_t rnd(void) { s ^= s << 13; s ^= s >> 7; s ^= s << 17; return (uint32_t)s; }
static uint32_t operand(void)
{
    const uint32_t r = rnd(), sign = r & 0x80000000u, man = rnd() & 0x7FFFFFu;
    switch (rnd() % 10) {
    case 0: return sign;                                       /* +-0 */
    case 1: return sign | man;                                 /* denormal */
    case 2: return sign | (255u << 23) | man;                  /* extended range */
    case 3: return sign | ((1u + rnd() % 40) << 23) | man;     /* tiny: products underflow */
    case 4: return sign | ((215u + rnd() % 40) << 23) | man;   /* huge */
    case 5: return sign | (127u << 23) | (rnd() & 0xFu);       /* ~1, few bits: boundaries */
    default: return sign | ((1u + rnd() % 254) << 23) | man;   /* any normal */
    }
}
static int bad;
static void cmp(const char* op, u128 got, u128 want, u128 a, u128 b, u128 c)
{
    for (int i = 0; i < 4; i++)
        if (got._u32[i] != want._u32[i] && bad++ < 20)
            printf("%s lane %d: a=%08X b=%08X c=%08X got %08X want %08X\n", op, i,
                   a._u32[i], b._u32[i], c._u32[i], got._u32[i], want._u32[i]);
}
int main(int argc, char** argv)
{
    const long n = argc > 1 ? atol(argv[1]) : 20000000;
    for (long k = 0; k < n; k++) {
        u128 a, b, c;
        for (int i = 0; i < 4; i++) { a._u32[i] = operand(); b._u32[i] = operand(); c._u32[i] = operand(); }
        if (k & 1) for (int i = 0; i < 4; i++) b._u32[i] = a._u32[i] ^ 0x80000000u ^ (rnd() & 3u);   /* cancel */
        cmp("fa", spu_fa(a, b), spu_fa_ref(a, b), a, b, c);
        cmp("fs", spu_fs(a, b), spu_fs_ref(a, b), a, b, c);
        cmp("fm", spu_fm(a, b), spu_fm_ref(a, b), a, b, c);
        cmp("fma", spu_fma(a, b, c), spu_fma_ref(a, b, c), a, b, c);
        cmp("fms", spu_fms(a, b, c), spu_fms_ref(a, b, c), a, b, c);
        cmp("fnms", spu_fnms(a, b, c), spu_fnms_ref(a, b, c), a, b, c);
    }
    printf("%ld vectors x 6 ops: %d mismatching lanes\n", n, bad);
    return bad != 0;
}
