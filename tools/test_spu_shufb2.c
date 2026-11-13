/* spu shufb2: spu_shufb (host byte order) against spu_shufb_ref (the byte loop): every control byte
 * value in every position, with random a/b.   clang -O2 -march=znver2 -I<fork>/runtime/spu test_spu_shufb2.c */
#include <stdio.h>
#include <string.h>
#include "spu_helpers.h"
static uint64_t s = 0x853C49E6748FEA9Bull;
static uint64_t rn(void) { s ^= s << 13; s ^= s >> 7; s ^= s << 17; return s; }
int main(void)
{
    long bad = 0, n = 0;
    for (long it = 0; it < 2000000; it++) {
        u128 a, b, c;
        for (int i = 0; i < 2; i++) { a._u64[i] = rn(); b._u64[i] = rn(); c._u64[i] = rn(); }
        if (it < 256 * 16) c._u8[(it >> 8) & 15] = (uint8_t)it;        /* every value, every position */
        else if (it & 1) for (int i = 0; i < 16; i++) c._u8[i] &= 0x1F;  /* plain selects */
        const u128 x = spu_shufb(a, b, c), y = spu_shufb_ref(a, b, c), z = spu_shufb_sw(a, b, c);
        n++;
        if (memcmp(&x, &y, 16) || memcmp(&z, &y, 16)) { if (bad++ < 5) printf("differ at %ld\n", it); }
    }
    printf("%ld of %ld differ\n", bad, n);
    return bad != 0;
}
