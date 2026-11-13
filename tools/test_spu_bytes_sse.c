/* The SSSE3 SPU quadword byte shifts/rotates and cwd must be bit-identical to the scalar references
 * for every input and every count (all 64 low values of the count word, plus random words).
 *   clang -O2 -march=znver2 -I<toolkit>/runtime/spu ... test_spu_bytes_sse.c */
#include "spu_helpers.h"
#include <stdio.h>

static uint64_t s_rng = 0x2545F4914F6CDD1Dull;
static uint32_t rnd32(void) { s_rng ^= s_rng << 13; s_rng ^= s_rng >> 7; s_rng ^= s_rng << 17; return (uint32_t)(s_rng >> 16); }

int main(void)
{
#if !defined(SPU_BYTES_SSSE3)
    puts("test_spu_bytes_sse: no SSSE3 path, nothing to compare");
    return 0;
#else
    long bad = 0, n = 0;
    for (int it = 0; it < 200000; it++) {
        u128 a, b;
        for (int i = 0; i < 4; i++) { a._u32[i] = rnd32(); b._u32[i] = rnd32(); }
        const int k = it < 512 ? (it & 511) : (int)rnd32();
        b._u32[0] = it < 512 ? (uint32_t)(k - 256) : b._u32[0];
        const int imm = (it & 127) - 64;
        u128 got[10], ref[10];
        got[0] = spu_shlqbyi(a, imm);   ref[0] = spu_shlqbyi_ref(a, imm);
        got[1] = spu_rotqbyi(a, imm);   ref[1] = spu_rotqbyi_ref(a, imm);
        got[2] = spu_shlqby(a, b);      ref[2] = spu_shlqby_ref(a, b);
        got[3] = spu_rotqby(a, b);      ref[3] = spu_rotqby_ref(a, b);
        got[4] = spu_shlqbybi(a, b);    ref[4] = spu_shlqbybi_ref(a, b);
        got[5] = spu_rotqbybi(a, b);    ref[5] = spu_rotqbybi_ref(a, b);
        got[6] = spu_rotqmby(a, b);     ref[6] = spu_rotqmby_ref(a, b);
        got[7] = spu_rotqmbybi(a, b);   ref[7] = spu_rotqmbybi_ref(a, b);
        got[8] = spu_rotqmbyi(a, imm);  ref[8] = spu_rotqmbyi_ref(a, imm);
        got[9] = spu_cwd(a, imm);       ref[9] = spu_cwd_ref(a, imm);
        for (int op = 0; op < 10; op++, n++)
            if (memcmp(&got[op], &ref[op], 16) && bad++ < 10)
                printf("MISMATCH op=%d imm=%d a=%08X %08X %08X %08X b0=%08X got=%08X %08X %08X %08X ref=%08X %08X %08X %08X\n",
                       op, imm, a._u32[0], a._u32[1], a._u32[2], a._u32[3], b._u32[0],
                       got[op]._u32[0], got[op]._u32[1], got[op]._u32[2], got[op]._u32[3],
                       ref[op]._u32[0], ref[op]._u32[1], ref[op]._u32[2], ref[op]._u32[3]);
    }
    if (bad) { printf("test_spu_bytes_sse: %ld mismatches in %ld cases\n", bad, n); return 1; }
    printf("test_spu_bytes_sse: ok (%ld cases)\n", n);
    return 0;
#endif
}
