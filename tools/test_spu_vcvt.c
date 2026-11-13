/* spu vcvt: the SSE cflts/cfltu/csflt/cuflt, fi and float compares (patch_spu_vcvt.py) against the
 * scalar forms, bit for bit, under spu fz's MXCSR (and cflts/cfltu/fi/compares also without it):
 * random words weighted to the edges (zeros, denormals, exponent 255, the saturation points), every
 * i8 scale.   clang -O2 -march=znver2 -I<fork>/runtime/spu test_spu_vcvt.c -lm && ./a.out */
#include <stdio.h>
#include <string.h>
#include "spu_helpers.h"

static uint64_t s = 0x2545F4914F6CDD1Dull;
static uint64_t rn(void) { s ^= s << 13; s ^= s >> 7; s ^= s << 17; return s; }
static uint32_t word(void)
{
    static const uint32_t special[] = { 0, 0x80000000u, 1, 0x7FFFFFFFu, 0xFFFFFFFFu, 0x00800000u, 0x807FFFFFu,
                                        0x7F800000u, 0xFF800000u, 0x7F7FFFFFu, 0x4F000000u, 0xCF000000u,
                                        0x4F800000u, 0x4EFFFFFFu, 0x3F800000u, 0xBF800000u, 0x0000FFFFu, 0xFFFF0000u };
    const uint64_t r = rn();
    switch (r & 7) {
    case 0: return special[(r >> 8) % (sizeof special / sizeof special[0])] + (uint32_t)((r >> 40) % 3) - 1;
    case 1: case 2: {   /* exponents around the integer range */
        const uint32_t e = 100 + (uint32_t)((r >> 8) % 70);
        return (uint32_t)(r >> 40 & 0x80000000u) | (e << 23) | (uint32_t)(r >> 16 & 0x7FFFFFu);
    }
    case 3: return (uint32_t)(r >> 16) & (0xFFFFFFFFu >> ((r >> 50) % 32));   /* small integers */
    default: return (uint32_t)(r >> 16);
    }
}
static u128 vec(const uint32_t* w) { u128 v; memcpy(v._u32, w, 16); return v; }
static long bad, n;
static void check(const char* op, int i8, u128 got, u128 want, u128 a, u128 b)
{
    n++;
    if (memcmp(&got, &want, 16) == 0) return;
    if (bad++ < 12)
        for (int i = 0; i < 4; i++)
            if (got._u32[i] != want._u32[i])
                printf("%s i8=%d lane %d: a=%08X b=%08X got %08X want %08X\n", op, i8, i, a._u32[i], b._u32[i],
                       got._u32[i], want._u32[i]);
}

int main(void)
{
#ifndef SPU_FZ_MXCSR
    printf("spu fz/vcvt not built (needs AVX2)\n");
    return 1;
#else
    for (int mode = 0; mode < 2; mode++) {
        g_spu_fz = mode;
        _mm_setcsr(mode ? SPU_FZ_MXCSR : 0x1F80u);
        for (long it = 0; it < 3000000; it++) {
            uint32_t A[4], B[4];
            for (int i = 0; i < 4; i++) { A[i] = word(); B[i] = word(); }
            const u128 a = vec(A), b = vec(B);
            const int i8 = (int)(rn() & 0xFF);
            check("cflts", i8, spu_cflts(a, i8), spu_cflts_exact(a, i8), a, b);
            check("cfltu", i8, spu_cfltu(a, i8), spu_cfltu_exact(a, i8), a, b);
            check("csflt", i8, spu_csflt(a, i8), spu_csflt_exact(a, i8), a, b);
            check("cuflt", i8, spu_cuflt(a, i8), spu_cuflt_exact(a, i8), a, b);
            check("fi", 0, spu_fi(a, b), spu_fi_exact(a, b), a, b);
            check("fceq", 0, spu_fceq(a, b), spu_fceq_ref(a, b), a, b);
            check("fcgt", 0, spu_fcgt(a, b), spu_fcgt_ref(a, b), a, b);
            check("fcmeq", 0, spu_fcmeq(a, b), spu_fcmeq_ref(a, b), a, b);
            check("fcmgt", 0, spu_fcmgt(a, b), spu_fcmgt_ref(a, b), a, b);
            const u128 bb = vec((uint32_t[4]){ A[0] ^ (uint32_t)(rn() & 1), A[1], B[2], A[3] ^ 0x80000000u });
            check("fceq=", 0, spu_fceq(a, bb), spu_fceq_ref(a, bb), a, bb);
            check("fcgt=", 0, spu_fcgt(a, bb), spu_fcgt_ref(a, bb), a, bb);
        }
    }
    printf("%ld of %ld vector results differ\n", bad, n);
    return bad != 0;
#endif
}
