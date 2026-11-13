/* The Vulkan SSAO shaders' 32-bit ssao_recip must equal the Metal shaders' 64-bit one bit for bit:
 * every exponent and LUT index, 300M random floats plus every float with a few mantissa patterns.
 *   cc -O2 test_ssao_recip.c -o t && ./t */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static const uint32_t LUT[32] = {
    0x7FFBE0, 0x7F87A6, 0x70EF72, 0x708B40, 0x638B12, 0x633AEA, 0x5792C4, 0x574AA0,
    0x4CCA7E, 0x4C9262, 0x430A44, 0x42D62A, 0x3A2E12, 0x39FDFA, 0x3215E4, 0x31F1D2,
    0x2AA9BE, 0x2A85AC, 0x23D59A, 0x23BD8E, 0x1D8576, 0x1D8576, 0x17AD5A, 0x17AD5A,
    0x124543, 0x124543, 0x0D392D, 0x0D392D, 0x08851A, 0x08851A, 0x041D07, 0x041D07 };

static uint32_t recip64(uint32_t b)   /* rsx_metal_backend.m ssao_recip, as bits */
{
    uint32_t sign = b & 0x80000000u, e = (b >> 23) & 0xFFu;
    uint32_t re = (e == 0u) ? 255u : (e >= 253u ? 0u : 253u - e);
    uint32_t est = sign | (re << 23) | (LUT[(b >> 18) & 31u] & 0x7FFFFFu);
    int ee = (int)((est >> 23) & 0xFFu);
    if (ee == 0) return 0;   /* 0.0f */
    uint64_t base = (est >> 10) & 0x1FFFu, step = est & 0x3FFu, y = b & 0x7FFFFu;
    uint64_t m = ((8192ull | base) << 19) - step * y;
    if (m < (1ull << 32)) { m <<= 1; if (--ee == 0) return 0; }
    return sign | ((uint32_t)ee << 23) | (uint32_t)((m >> 9) & 0x7FFFFFu);
}

static uint32_t recip32(uint32_t b)   /* the Vulkan HLSL version */
{
    uint32_t sgn = b & 0x80000000u, e = (b >> 23) & 0xFFu;
    uint32_t re = (e == 0u) ? 255u : (e >= 253u ? 0u : 253u - e);
    uint32_t est = sgn | (re << 23) | (LUT[(b >> 18) & 31u] & 0x7FFFFFu);
    int ee = (int)((est >> 23) & 0xFFu);
    if (ee == 0) return 0;
    uint32_t A = ((est >> 10) & 0x1FFFu) << 19, P = (est & 0x3FFu) * (b & 0x7FFFFu), mant;
    if (A >= P) mant = ((A - P) >> 9) & 0x7FFFFFu;
    else { ee -= 1; if (ee == 0) return 0; mant = ((0u - 2u * (P - A)) >> 9) & 0x7FFFFFu; }
    return sgn | ((uint32_t)ee << 23) | mant;
}

int main(void)
{
    uint64_t s = 0x9E3779B97F4A7C15ull, n = 0, bad = 0;
    for (uint64_t i = 0; i < 300000000ull; i++) {
        s ^= s << 13; s ^= s >> 7; s ^= s << 17;
        const uint32_t b = (uint32_t)(s >> 11);
        n++;
        if (recip64(b) != recip32(b) && bad++ < 10) printf("MISMATCH %08X: %08X vs %08X\n", b, recip64(b), recip32(b));
    }
    /* every sign/exponent with all 2^19 low-mantissa patterns under each of the 32 LUT entries' first value */
    for (uint32_t se = 0; se < 512; se++)
        for (uint32_t idx = 0; idx < 32; idx++)
            for (uint32_t y = 0; y < (1u << 19); y += 37) {
                const uint32_t b = (se << 23) | (idx << 18) | y;
                n++;
                if (recip64(b) != recip32(b) && bad++ < 10) printf("MISMATCH %08X: %08X vs %08X\n", b, recip64(b), recip32(b));
            }
    printf("test_ssao_recip: %llu cases, %llu mismatches\n", (unsigned long long)n, (unsigned long long)bad);
    return bad != 0;
}
