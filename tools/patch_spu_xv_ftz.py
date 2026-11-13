# spu xv ftz: the AVX2 exact-float fast path (spu__xv_fa/fm/fma) now takes two more cases itself
# instead of the per-lane scalar fix-up (spu__xv_*_fix -> spu__fa/fm/fma_any), bit-identical to it:
#  - a denormal operand (biased exponent 0) is the SPU's zero (spu__sf_split): flushed to +0 first;
#  - a result below the normal range (|r| < 2^-126, not zero) is the SPU's +0 (truncation toward
#    zero; the fma boundary case -- a rounded double exactly at 2^-126 -- keeps its exact path).
# Counted on inFAMOUS 1's crater (BC-250, 2026-11-01): ~2.3M fix-up calls per second over the SPU
# threads; of the slow lanes 78% were plain operands with an underflowing result, 10% denormal
# operands. Extended-range lanes (exponent 255 in or out) still take the fix-up.
# Checked against spu_fa/fs/fm/fma/fms/fnms_ref on random and edge operands (tools/spu_xv_test.c).
H = "runtime/spu/spu_helpers.h"
edit(H,
     '''SPU__XV_INLINE __m256d spu__xv_wide(__m128i x) { return _mm256_cvtps_pd(_mm_castsi128_ps(x)); }''',
     '''SPU__XV_INLINE __m256d spu__xv_wide(__m128i x) { return _mm256_cvtps_pd(_mm_castsi128_ps(x)); }
/* spu xv ftz: a denormal operand is the SPU's zero (spu__sf_split): +0. */
SPU__XV_INLINE __m128i spu__xv_ftz(__m128i x) {
    return _mm_andnot_si128(_mm_cmpeq_epi32(spu__xv_bexp(x), _mm_setzero_si128()), x);
}''',
     "spu xv ftz: ftz")
edit(H,
     '''    const __m256i lo32 = _mm256_setr_epi32(0, 2, 4, 6, 0, 2, 4, 6);
    *ok = _mm256_castsi256_si128(_mm256_permutevar8x32_epi32(_mm256_or_si256(good, az), lo32));
    *zm = _mm256_castsi256_si128(_mm256_permutevar8x32_epi32(az, lo32));
    const __m256d t = _mm256_castsi256_pd(_mm256_and_si256(u, _mm256_set1_epi64x(~0x1FFFFFFFll)));
    return _mm_castps_si128(_mm256_cvtpd_ps(t));''',
     '''    /* spu xv ftz: below the normal range (and not zero) truncates to the SPU's +0 */
    const __m256i under = _mm256_andnot_si256(az, _mm256_cmpgt_epi64(_mm256_set1_epi64x(-126), e));
    const __m256i zero = _mm256_or_si256(az, under);
    const __m256i lo32 = _mm256_setr_epi32(0, 2, 4, 6, 0, 2, 4, 6);
    *ok = _mm256_castsi256_si128(_mm256_permutevar8x32_epi32(_mm256_or_si256(good, zero), lo32));
    *zm = _mm256_castsi256_si128(_mm256_permutevar8x32_epi32(zero, lo32));
    const __m256d t = _mm256_castsi256_pd(_mm256_andnot_si256(under, _mm256_and_si256(u, _mm256_set1_epi64x(~0x1FFFFFFFll))));
    return _mm_castps_si128(_mm256_cvtpd_ps(t));''',
     "spu xv ftz: underflow")
edit(H,
     '''    const __m128i xa = spu__xv_ld(a), yb = spu__xv_ld(b);
    const __m128i x = xa, y = _mm_xor_si128(yb, _mm_set1_epi32((int)negb));''',
     '''    const __m128i xa = spu__xv_ld(a), yb = spu__xv_ld(b);
    const __m128i x = spu__xv_ftz(xa), y = _mm_xor_si128(spu__xv_ftz(yb), _mm_set1_epi32((int)negb));''',
     "spu xv ftz: fa")
edit(H,
     '''SPU__FX u128 spu__xv_fm_x(u128 a, u128 b) {
    const __m128i x = spu__xv_ld(a), y = spu__xv_ld(b);''',
     '''SPU__FX u128 spu__xv_fm_x(u128 a, u128 b) {
    const __m128i x = spu__xv_ftz(spu__xv_ld(a)), y = spu__xv_ftz(spu__xv_ld(b));''',
     "spu xv ftz: fm")
edit(H,
     '''    const __m128i xa = spu__xv_ld(a), y = spu__xv_ld(b), zc = spu__xv_ld(c);
    const __m128i x = _mm_xor_si128(xa, _mm_set1_epi32((int)negp)), z = _mm_xor_si128(zc, _mm_set1_epi32((int)negc));
    const __m256d p = _mm256_mul_pd(spu__xv_wide(x), spu__xv_wide(y)), zd = spu__xv_wide(z);''',
     '''    const __m128i xa = spu__xv_ld(a), y = spu__xv_ftz(spu__xv_ld(b)), zc = spu__xv_ld(c);
    const __m128i x = _mm_xor_si128(spu__xv_ftz(xa), _mm_set1_epi32((int)negp)),
                  z = _mm_xor_si128(spu__xv_ftz(zc), _mm_set1_epi32((int)negc));
    const __m256d p = _mm256_mul_pd(spu__xv_wide(x), spu__xv_wide(y)), zd = spu__xv_wide(z);''',
     "spu xv ftz: fma")
