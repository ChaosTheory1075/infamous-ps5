/* The native SPU float forms (patch_spu_ffast.py) against the scalar exact forms (spu_*_ref), bit
 * for bit: random words over the whole exponent range, zeros, denormal and extended (exponent 255)
 * patterns, near-cancelling sums (y ~ -x, z ~ -x*y) and tiny/huge products.
 *   clang -O2 -march=znver2 -ffp-contract=off -I<fork>/runtime/spu test_spu_ffast.c -lm && ./a.out */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "spu_helpers.h"

static uint64_t s = 0x9E3779B97F4A7C15ull;
static uint64_t rn(void) { s ^= s << 13; s ^= s >> 7; s ^= s << 17; return s; }
static uint32_t word(void)
{
    static const uint32_t special[] = { 0, 0x80000000u, 1, 0x807FFFFFu, 0x00400000u, 0x7F800000u, 0xFF800000u,
                                        0x7FC00000u, 0x7F800001u, 0xFFFFFFFFu, 0x3F800000u, 0xBF800000u, 0x7F7FFFFFu,
                                        0x00800000u, 0x80800000u, 0x00800001u, 0x7F000000u, 0x4B000000u };
    const uint64_t r = rn();
    switch (r & 7) {
    case 0: return special[(r >> 8) % (sizeof special / sizeof special[0])];
    case 1: case 2: {   /* moderate exponents, where game data lives */
        const uint32_t e = 100 + (uint32_t)((r >> 8) % 56);
        return (uint32_t)(r >> 40 & 0x80000000u) | (e << 23) | (uint32_t)(r >> 16 & 0x7FFFFFu);
    }
    case 3: {           /* few significand bits: exact results, boundary cases */
        const uint32_t e = 110 + (uint32_t)((r >> 8) % 36);
        return (uint32_t)(r >> 40 & 0x80000000u) | (e << 23) | (uint32_t)(r >> 16 & 0x7F0000u);
    }
    default: return (uint32_t)(r >> 16);
    }
}
static float f_of(uint32_t w) { float f; memcpy(&f, &w, 4); return f; }
static uint32_t w_of(float f) { uint32_t w; memcpy(&w, &f, 4); return w; }
static u128 vec(uint32_t a, uint32_t b, uint32_t c, uint32_t d) { u128 v; v._u32[0] = a; v._u32[1] = b; v._u32[2] = c; v._u32[3] = d; return v; }

static long bad, n;
static void check(const char* op, u128 got, u128 want, u128 a, u128 b, u128 c)
{
    n++;
    if (memcmp(&got, &want, 16) == 0) return;
    if (bad++ < 12)
        for (int i = 0; i < 4; i++)
            if (got._u32[i] != want._u32[i])
                printf("%s lane %d: a=%08X b=%08X c=%08X got %08X want %08X\n", op, i, a._u32[i], b._u32[i],
                       c._u32[i], got._u32[i], want._u32[i]);
}

int main(void)
{
#ifndef SPU_FFAST
    printf("SPU_FFAST is not on (needs -mfma); nothing to test\n");
    return 1;
#endif
    for (long it = 0; it < 4000000; it++) {
        uint32_t A[4], B[4], C[4];
        for (int i = 0; i < 4; i++) {
            A[i] = word(); B[i] = word(); C[i] = word();
            switch (rn() % 6) {
            case 0: B[i] = A[i] ^ 0x80000000u ^ (uint32_t)(rn() & 3); break;              /* y ~ -x */
            case 1: { const float p = f_of(A[i]) * f_of(B[i]);                               /* z ~ -x*y */
                      C[i] = (w_of(p) ^ 0x80000000u) ^ (uint32_t)(rn() & 7); } break;
            case 2: C[i] = 0; break;
            default: break;
            }
        }
        /* a quarter of the vectors all-moderate, so the fast path itself is exercised a lot */
        if ((it & 3) == 0)
            for (int i = 0; i < 4; i++) {
                const uint64_t r = rn();
                A[i] = (uint32_t)(r & 0x80000000u) | ((110u + (uint32_t)(r >> 33) % 36) << 23) | (uint32_t)(r >> 8 & 0x7FFFFFu);
                B[i] = (uint32_t)(r >> 1 & 0x80000000u) | ((110u + (uint32_t)(r >> 40) % 36) << 23) | (uint32_t)(r >> 20 & 0x7FFFFFu);
                if (rn() & 1) C[i] = (w_of(f_of(A[i]) * f_of(B[i])) ^ ((rn() & 1) ? 0x80000000u : 0)) + (uint32_t)(rn() % 9) - 4;
            }
        const u128 a = vec(A[0], A[1], A[2], A[3]), b = vec(B[0], B[1], B[2], B[3]), c = vec(C[0], C[1], C[2], C[3]);
        check("fa", spu_fa(a, b), spu_fa_ref(a, b), a, b, c);
        check("fs", spu_fs(a, b), spu_fs_ref(a, b), a, b, c);
        check("fm", spu_fm(a, b), spu_fm_ref(a, b), a, b, c);
        check("fma", spu_fma(a, b, c), spu_fma_ref(a, b, c), a, b, c);
        check("fms", spu_fms(a, b, c), spu_fms_ref(a, b, c), a, b, c);
        check("fnms", spu_fnms(a, b, c), spu_fnms_ref(a, b, c), a, b, c);
    }
    printf("%ld of %ld vector results differ\n", bad, n);
    return bad != 0;
}
